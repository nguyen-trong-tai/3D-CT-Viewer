import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.artifact_service import ArtifactService


class ArtifactServiceTests(unittest.TestCase):
    def test_mesh_delivery_prefers_presigned_url_when_remote_mesh_exists(self):
        repo = mock.Mock()
        repo.is_artifact_available.return_value = True
        repo.get_artifact_object_key.return_value = "cases/case-1/mesh/reconstruction.glb"

        object_store = mock.Mock()
        object_store.object_exists.return_value = True
        object_store.generate_download_url.return_value = "https://example.invalid/mesh.glb?sig=abc"

        service = ArtifactService(repo, object_store)

        delivery = service.get_mesh_delivery("case-1", expires_in_seconds=900)

        repo.sync_for_read.assert_called_once_with(scope="artifact")
        self.assertEqual(
            delivery,
            {
                "type": "redirect",
                "url": "https://example.invalid/mesh.glb?sig=abc",
            },
        )
        repo.get_mesh_path.assert_not_called()
        object_store.generate_download_url.assert_called_once_with(
            "cases/case-1/mesh/reconstruction.glb",
            expires_in_seconds=900,
        )

    def test_mesh_delivery_falls_back_to_local_file_when_remote_mesh_is_unavailable(self):
        repo = mock.Mock()
        repo.is_artifact_available.return_value = True
        repo.get_artifact_object_key.return_value = "cases/case-1/mesh/reconstruction.glb"
        local_mesh_path = pathlib.Path("/tmp/reconstruction.glb")
        repo.get_mesh_path.return_value = local_mesh_path

        object_store = mock.Mock()
        object_store.object_exists.return_value = False

        service = ArtifactService(repo, object_store)

        delivery = service.get_mesh_delivery("case-1", expires_in_seconds=900)

        self.assertEqual(
            delivery,
            {
                "type": "file",
                "path": local_mesh_path,
            },
        )
        repo.get_mesh_path.assert_called_once_with("case-1")
        object_store.generate_download_url.assert_not_called()

    def test_artifact_download_url_requires_remote_object(self):
        repo = mock.Mock()
        repo.is_artifact_available.return_value = True
        repo.get_artifact_object_key.return_value = "cases/case-1/ct/volume.npy"

        object_store = mock.Mock()
        object_store.object_exists.return_value = False

        service = ArtifactService(repo, object_store)

        with self.assertRaises(FileNotFoundError):
            service.get_artifact_download_url("case-1", "ct_volume", expires_in_seconds=600)

        object_store.generate_download_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
