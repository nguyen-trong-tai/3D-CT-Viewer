import pathlib
import sys
import unittest
from unittest import mock

import numpy as np
import pydicom


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processing import MedicalVolumeLoader, MeshProcessor, SDFProcessor
from processing.mesh import extract_mesh
from processing.sdf import compute_sdf_fast
from services.pipeline import PipelineService, PipelineStageStatus


class ProcessingClassTests(unittest.TestCase):
    @staticmethod
    def _make_dicom_like_dataset(
        series_uid: str,
        z_position: float,
        *,
        with_pixel_data: bool = False,
        slice_thickness: float = 1.25,
    ) -> pydicom.Dataset:
        ds = pydicom.Dataset()
        ds.Rows = 2
        ds.Columns = 2
        ds.SeriesInstanceUID = series_uid
        ds.ImagePositionPatient = [0.0, 0.0, float(z_position)]
        ds.PixelSpacing = [1.0, 1.0]
        ds.SliceThickness = slice_thickness
        if with_pixel_data:
            ds.PixelData = b"\x00\x00\x00\x00"
        return ds

    def test_loader_metadata_extraction_works_from_class_api(self):
        ds = pydicom.Dataset()
        ds.PatientID = "patient-1"
        ds.Modality = "CT"
        ds.SliceThickness = 1.25

        meta = MedicalVolumeLoader.extract_dicom_metadata(ds)

        self.assertEqual(meta["patient_id"], "patient-1")
        self.assertEqual(meta["modality"], "CT")
        self.assertEqual(meta["slice_thickness"], 1.25)

    def test_load_selected_dicom_datasets_reads_full_data_only_for_primary_series(self):
        header_entries = [
            {"source": "series-b-1.dcm", "header": self._make_dicom_like_dataset("series-b", 1.0)},
            {"source": "series-a-2.dcm", "header": self._make_dicom_like_dataset("series-a", 2.0)},
            {"source": "series-a-0.dcm", "header": self._make_dicom_like_dataset("series-a", 0.0)},
            {"source": "series-b-0.dcm", "header": self._make_dicom_like_dataset("series-b", 0.0)},
            {"source": "series-a-1.dcm", "header": self._make_dicom_like_dataset("series-a", 1.0)},
        ]
        datasets_by_path = {
            "series-a-0.dcm": self._make_dicom_like_dataset("series-a", 0.0, with_pixel_data=True),
            "series-a-1.dcm": self._make_dicom_like_dataset("series-a", 1.0, with_pixel_data=True),
            "series-a-2.dcm": self._make_dicom_like_dataset("series-a", 2.0, with_pixel_data=True),
            "series-b-0.dcm": self._make_dicom_like_dataset("series-b", 0.0, with_pixel_data=True),
            "series-b-1.dcm": self._make_dicom_like_dataset("series-b", 1.0, with_pixel_data=True),
        }

        with mock.patch.object(
            MedicalVolumeLoader,
            "_load_candidate_dicom_file_headers",
            return_value=header_entries,
        ):
            with mock.patch.object(
                MedicalVolumeLoader,
                "_load_candidate_dicom_datasets",
                side_effect=AssertionError("legacy fallback should not be used"),
            ):
                with mock.patch(
                    "processing.loader.pydicom.dcmread",
                    side_effect=lambda path: datasets_by_path[path],
                ) as dcmread_mock:
                    selected_datasets, spacing, representative_header = MedicalVolumeLoader.load_selected_dicom_datasets(
                        list(datasets_by_path.keys())
                    )

        self.assertEqual(
            [float(ds.ImagePositionPatient[2]) for ds in selected_datasets],
            [0.0, 1.0, 2.0],
        )
        self.assertEqual(spacing, (1.0, 1.0, 1.25))
        self.assertEqual(str(representative_header.SeriesInstanceUID), "series-a")
        self.assertEqual(
            {call.args[0] for call in dcmread_mock.call_args_list},
            {"series-a-0.dcm", "series-a-1.dcm", "series-a-2.dcm"},
        )

    def test_load_selected_dicom_datasets_falls_back_to_legacy_scan_when_selected_headers_are_not_decodable(self):
        header_entries = [
            {"source": "series-a-2.dcm", "header": self._make_dicom_like_dataset("series-a", 2.0)},
            {"source": "series-b-1.dcm", "header": self._make_dicom_like_dataset("series-b", 1.0)},
            {"source": "series-a-0.dcm", "header": self._make_dicom_like_dataset("series-a", 0.0)},
            {"source": "series-b-0.dcm", "header": self._make_dicom_like_dataset("series-b", 0.0)},
            {"source": "series-a-1.dcm", "header": self._make_dicom_like_dataset("series-a", 1.0)},
        ]
        full_datasets = {
            "series-a-0.dcm": self._make_dicom_like_dataset("series-a", 0.0, with_pixel_data=True),
            "series-a-1.dcm": self._make_dicom_like_dataset("series-a", 1.0, with_pixel_data=False),
            "series-a-2.dcm": self._make_dicom_like_dataset("series-a", 2.0, with_pixel_data=False),
        }
        fallback_entries = [
            {
                "source": "series-b-1.dcm",
                "header": self._make_dicom_like_dataset("series-b", 1.0, with_pixel_data=True),
                "dataset": self._make_dicom_like_dataset("series-b", 1.0, with_pixel_data=True),
            },
            {
                "source": "series-a-0.dcm",
                "header": self._make_dicom_like_dataset("series-a", 0.0, with_pixel_data=True),
                "dataset": self._make_dicom_like_dataset("series-a", 0.0, with_pixel_data=True),
            },
            {
                "source": "series-b-0.dcm",
                "header": self._make_dicom_like_dataset("series-b", 0.0, with_pixel_data=True),
                "dataset": self._make_dicom_like_dataset("series-b", 0.0, with_pixel_data=True),
            },
        ]

        with mock.patch.object(
            MedicalVolumeLoader,
            "_load_candidate_dicom_file_headers",
            return_value=header_entries,
        ):
            with mock.patch.object(
                MedicalVolumeLoader,
                "_load_candidate_dicom_datasets",
                return_value=fallback_entries,
            ) as fallback_mock:
                with mock.patch(
                    "processing.loader.pydicom.dcmread",
                    side_effect=lambda path: full_datasets[path],
                ):
                    selected_datasets, spacing, representative_header = MedicalVolumeLoader.load_selected_dicom_datasets(
                        list(full_datasets.keys())
                    )

        fallback_mock.assert_called_once()
        self.assertEqual(
            [float(ds.ImagePositionPatient[2]) for ds in selected_datasets],
            [0.0, 1.0],
        )
        self.assertTrue(all(str(ds.SeriesInstanceUID) == "series-b" for ds in selected_datasets))
        self.assertEqual(spacing, (1.0, 1.0, 1.25))
        self.assertEqual(str(representative_header.SeriesInstanceUID), "series-b")

    def test_sdf_class_api_matches_wrapper(self):
        mask = np.zeros((8, 8, 8), dtype=np.uint8)
        mask[2:6, 2:6, 2:6] = 1

        sdf_from_class = SDFProcessor.compute_fast(mask)
        sdf_from_wrapper = compute_sdf_fast(mask)

        np.testing.assert_allclose(sdf_from_class, sdf_from_wrapper)

    def test_mesh_class_api_matches_wrapper(self):
        mask = np.zeros((10, 10, 10), dtype=np.uint8)
        mask[3:7, 3:7, 3:7] = 1

        sdf = SDFProcessor.compute(mask)
        mesh_from_class = MeshProcessor.extract_mesh(sdf, (1.0, 1.0, 1.0))
        mesh_from_wrapper = extract_mesh(sdf, (1.0, 1.0, 1.0))

        self.assertGreater(len(mesh_from_class.vertices), 0)
        self.assertEqual(len(mesh_from_class.vertices), len(mesh_from_wrapper.vertices))
        self.assertEqual(len(mesh_from_class.faces), len(mesh_from_wrapper.faces))

    def test_mesh_scene_builder_keeps_named_components(self):
        left_mesh = MeshProcessor.apply_color(
            MeshProcessor._create_placeholder_mesh((4, 4, 4), (1.0, 1.0, 1.0)),
            (96, 165, 250, 255),
        )
        right_mesh = MeshProcessor.apply_color(
            MeshProcessor._create_placeholder_mesh((3, 3, 3), (1.0, 1.0, 1.0)),
            (52, 211, 153, 255),
        )

        scene = MeshProcessor.build_scene([
            ("left_lung", left_mesh),
            ("right_lung", right_mesh),
        ])

        self.assertEqual(set(scene.geometry.keys()), {"left_lung", "right_lung"})

    def test_pipeline_normalizes_component_aware_segmentation_output(self):
        combined = np.zeros((8, 8, 8), dtype=np.uint8)
        combined[1:7, 1:7, 1:7] = 1

        left = np.zeros_like(combined)
        left[4:7, 1:7, 1:7] = 1

        right = np.zeros_like(combined)
        right[1:4, 1:7, 1:7] = 1

        normalized_mask, components, manifest = PipelineService._normalize_segmentation_result(
            {
                "labeled_mask": combined,
                "manifest": {
                    "version": 1,
                    "has_labeled_mask": True,
                    "labels": [],
                },
                "components": {
                    "left_lung": {
                        "name": "Left Lung",
                        "mask": left,
                        "color": "#60a5fa",
                        "label_id": 1,
                        "render_2d": True,
                        "render_3d": True,
                    },
                    "right_lung": {
                        "name": "Right Lung",
                        "mask": right,
                        "color": "#34d399",
                        "label_id": 2,
                        "render_2d": True,
                        "render_3d": True,
                    },
                },
            }
        )

        np.testing.assert_array_equal(normalized_mask, combined)
        self.assertEqual([component.key for component in components], ["left_lung", "right_lung"])
        self.assertTrue(manifest["has_labeled_mask"])

    def test_stage_load_volume_prefers_memory_mapped_volume(self):
        repo = mock.Mock()
        volume = np.zeros((4, 4, 4), dtype=np.int16)
        metadata = {"spacing": [1.0, 1.0, 1.0], "hu_range": {"min": -900, "max": 1200}}
        repo.load_ct_metadata.return_value = metadata
        repo.load_ct_volume_mmap.return_value = volume

        pipeline = PipelineService(repo)

        stage_result, loaded_volume, loaded_metadata = pipeline._stage_load_volume("case-1")

        self.assertEqual(stage_result.status, PipelineStageStatus.COMPLETED)
        self.assertIs(loaded_volume, volume)
        self.assertEqual(loaded_metadata, metadata)
        repo.load_ct_volume_mmap.assert_called_once_with("case-1")
        repo.load_ct_volume.assert_not_called()
        self.assertIn("(mmap)", stage_result.message)

    def test_prepare_volume_for_segmentation_skips_clip_when_hu_range_is_safe(self):
        volume = np.array([[[-500, 1000]]], dtype=np.int16)
        metadata = {"hu_range": {"min": -500, "max": 1000}}

        prepared = PipelineService._prepare_volume_for_segmentation(volume, metadata)

        self.assertIs(prepared, volume)

    def test_prepare_volume_for_segmentation_clips_when_hu_range_exceeds_bounds(self):
        volume = np.array([[[-1500, 4000]]], dtype=np.int16)
        metadata = {"hu_range": {"min": -1500, "max": 4000}}

        prepared = PipelineService._prepare_volume_for_segmentation(volume, metadata)

        np.testing.assert_array_equal(prepared, np.array([[[-1024, 3071]]], dtype=np.int16))


if __name__ == "__main__":
    unittest.main()
