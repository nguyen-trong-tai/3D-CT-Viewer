import pathlib
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from unittest import mock

from fastapi import BackgroundTasks, UploadFile


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processing import MedicalVolumeLoader
from services.upload_service import UploadBackgroundProcessor, UploadService


class UploadServiceTests(unittest.TestCase):
    @staticmethod
    def _make_dicom_like_header(series_uid: str, z_position: float):
        header = mock.Mock()
        header.Rows = 2
        header.Columns = 2
        header.SeriesInstanceUID = series_uid
        header.ImagePositionPatient = [0.0, 0.0, float(z_position)]
        header.PixelSpacing = [1.0, 1.0]
        header.SliceThickness = 1.25
        return header

    def test_init_batch_upload_uses_object_store_when_runtime_is_distributed(self):
        repo = mock.Mock()
        repo.object_store = mock.Mock()
        state_store = mock.Mock()
        artifacts = mock.Mock()
        artifacts.object_store = repo.object_store

        service = UploadService(repo, state_store, artifacts=artifacts)

        with mock.patch("services.upload_service.has_distributed_runtime", return_value=True):
            with mock.patch("services.upload_service.commit_data_volume") as commit_mock:
                payload = service.init_batch_upload()

        self.assertEqual(payload["storage_kind"], "object_store")
        self.assertTrue(payload["direct_upload_enabled"])
        self.assertEqual(payload["preferred_upload_layout"], "raw_files")
        artifacts.create_temp_dir.assert_not_called()
        commit_mock.assert_not_called()

        _, session_payload, _ = state_store.create_batch_session.call_args.args
        self.assertEqual(session_payload["storage_kind"], "object_store")
        self.assertNotIn("temp_dir", session_payload)

    def test_init_batch_upload_uses_local_directory_without_distributed_runtime(self):
        repo = mock.Mock()
        repo.object_store = None
        state_store = mock.Mock()
        artifacts = mock.Mock()
        artifacts.object_store = None
        artifacts.create_temp_dir.return_value = "/tmp/batch_case"

        service = UploadService(repo, state_store, artifacts=artifacts)

        with mock.patch("services.upload_service.has_distributed_runtime", return_value=False):
            with mock.patch("services.upload_service.commit_data_volume") as commit_mock:
                payload = service.init_batch_upload()

        self.assertEqual(payload["storage_kind"], "local_dir")
        self.assertFalse(payload["direct_upload_enabled"])
        self.assertEqual(payload["preferred_upload_layout"], "archive_shards")
        artifacts.create_temp_dir.assert_called_once()
        commit_mock.assert_called_once_with(scope="upload_handoff")

        _, session_payload, _ = state_store.create_batch_session.call_args.args
        self.assertEqual(session_payload["storage_kind"], "local_dir")
        self.assertEqual(session_payload["temp_dir"], "/tmp/batch_case")

    def test_collect_dicom_files_keeps_extensionless_candidates_and_skips_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            (root / "scan.dcm").write_bytes(b"")
            (root / "IM0001").write_bytes(b"")
            (root / "archive.zip").write_bytes(b"zip")
            (root / "metadata.json").write_text("{}", encoding="utf-8")

            nested = root / "nested"
            nested.mkdir()
            (nested / "slice2").write_bytes(b"")

            collected = UploadBackgroundProcessor._collect_dicom_files(temp_dir)
            collected_names = [pathlib.Path(path).name for path in collected]

        self.assertIn("scan.dcm", collected_names)
        self.assertIn("IM0001", collected_names)
        self.assertIn("slice2", collected_names)
        self.assertNotIn("archive.zip", collected_names)
        self.assertNotIn("metadata.json", collected_names)
        self.assertLess(collected_names.index("scan.dcm"), collected_names.index("IM0001"))

    def test_expand_uploaded_archives_extracts_zip_shards_before_collection(self):
        repo = mock.Mock()
        processor = UploadBackgroundProcessor(repo)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            archive_path = root / "dicom-shard-001.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("dicom/IM0001", b"dicom")
                archive.writestr("metadata.json", "{}")

            expanded_count = processor._expand_uploaded_archives("case-1", temp_dir)
            collected = UploadBackgroundProcessor._collect_dicom_files(temp_dir)
            collected_names = [pathlib.Path(path).name for path in collected]

        self.assertEqual(expanded_count, 1)
        self.assertIn("IM0001", collected_names)
        self.assertNotIn("dicom-shard-001.zip", collected_names)
        self.assertNotIn("metadata.json", collected_names)

    def test_process_dicom_object_keys_prefers_header_first_ingest_for_raw_objects(self):
        repo = mock.Mock()
        repo.object_store = mock.Mock()
        artifacts = mock.Mock()
        artifacts.object_store = repo.object_store
        processor = UploadBackgroundProcessor(repo, artifacts)

        with mock.patch.object(
            processor,
            "_try_load_dicom_volume_from_object_keys_header_first",
            return_value=("volume", (1.0, 1.0, 1.0), {}),
        ) as header_first_mock:
            with mock.patch.object(
                processor,
                "_download_objects_to_directory_parallel",
                side_effect=AssertionError("fallback download should not run"),
            ):
                with mock.patch.object(
                    processor,
                    "_publish_preview_first_best_effort",
                    return_value=True,
                ):
                    processor.process_dicom_object_keys("case-1", ["slice-0.dcm", "slice-1.dcm"], {})

        header_first_mock.assert_called_once_with("case-1", ["slice-0.dcm", "slice-1.dcm"], {})
        repo.save_ct_volume.assert_called_once_with("case-1", "volume", (1.0, 1.0, 1.0), generate_preview=False)
        artifacts.create_temp_dir.assert_not_called()

    def test_header_first_object_ingest_downloads_only_selected_primary_series(self):
        repo = mock.Mock()
        repo.object_store = mock.Mock()
        artifacts = mock.Mock()
        artifacts.object_store = repo.object_store
        processor = UploadBackgroundProcessor(repo, artifacts)
        headers = [
            {"source": "series-b-1.dcm", "header": self._make_dicom_like_header("series-b", 1.0)},
            {"source": "series-a-0.dcm", "header": self._make_dicom_like_header("series-a", 0.0)},
            {"source": "series-a-1.dcm", "header": self._make_dicom_like_header("series-a", 1.0)},
        ]
        selected_datasets = [
            self._make_dicom_like_header("series-a", 0.0),
            self._make_dicom_like_header("series-a", 1.0),
        ]

        with mock.patch.object(
            processor,
            "_inspect_dicom_object_headers_from_object_store",
            return_value=headers,
        ):
            with mock.patch.object(
                processor,
                "_download_selected_datasets_from_object_store",
                return_value=selected_datasets,
            ) as download_selected_mock:
                with mock.patch.object(
                    MedicalVolumeLoader,
                    "build_volume_from_datasets",
                    return_value=("volume", (1.0, 1.0, 1.25)),
                ):
                    with mock.patch.object(
                        MedicalVolumeLoader,
                        "extract_dicom_metadata",
                        return_value={},
                    ):
                        result = processor._try_load_dicom_volume_from_object_keys_header_first(
                            "case-1",
                            ["series-b-1.dcm", "series-a-0.dcm", "series-a-1.dcm"],
                            {"source": "upload"},
                        )

        self.assertEqual(result, ("volume", (1.0, 1.0, 1.25), {"source": "upload"}))
        download_selected_mock.assert_called_once_with("case-1", ["series-a-0.dcm", "series-a-1.dcm"])

    def test_upload_dicom_files_accepts_extensionless_uploads(self):
        repo = mock.Mock()
        repo.object_store = None
        state_store = mock.Mock()
        artifacts = mock.Mock()
        artifacts.object_store = None
        artifacts.parse_metadata_payload.return_value = {}
        artifacts.create_temp_dir.return_value = "/tmp/dicom_case"

        service = UploadService(repo, state_store, artifacts=artifacts)
        upload_file = UploadFile(filename="IM0001", file=BytesIO(b"dicom"))

        with mock.patch.object(service, "_stage_uploads_to_directory", return_value=1) as stage_mock:
            with mock.patch.object(service, "_dispatch_dicom_directory") as dispatch_mock:
                with mock.patch("services.upload_service.commit_data_volume") as commit_mock:
                    payload = service.upload_dicom_files(
                        BackgroundTasks(),
                        [upload_file],
                        None,
                    )

        self.assertEqual(payload["status"], "uploading")
        staged_files = stage_mock.call_args.args[0]
        self.assertEqual(len(staged_files), 1)
        self.assertEqual(staged_files[0].filename, "IM0001")
        dispatch_mock.assert_called_once()
        commit_mock.assert_called_once_with(scope="upload_handoff")

    def test_load_dicom_series_with_metadata_includes_extensionless_zip_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = pathlib.Path(temp_dir) / "series.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("IM0001", b"dicom")
                archive.writestr("metadata.json", "{}")

            representative_header = object()
            with mock.patch.object(
                MedicalVolumeLoader,
                "load_selected_dicom_datasets",
                return_value=(["slice"], (1.0, 1.0, 1.0), representative_header),
            ) as load_mock:
                with mock.patch.object(
                    MedicalVolumeLoader,
                    "build_volume_from_datasets",
                    return_value=("volume", (1.0, 1.0, 1.0)),
                ):
                    with mock.patch.object(
                        MedicalVolumeLoader,
                        "_load_archive_metadata",
                        return_value={"source": "zip"},
                    ):
                        volume, spacing, header, metadata = MedicalVolumeLoader.load_dicom_series_with_metadata(
                            str(zip_path)
                        )

        collected_paths = load_mock.call_args.args[0]
        collected_names = [pathlib.Path(path).name for path in collected_paths]

        self.assertEqual(volume, "volume")
        self.assertEqual(spacing, (1.0, 1.0, 1.0))
        self.assertIs(header, representative_header)
        self.assertEqual(metadata, {"source": "zip"})
        self.assertIn("IM0001", collected_names)
        self.assertNotIn("metadata.json", collected_names)


if __name__ == "__main__":
    unittest.main()
