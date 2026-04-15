import pathlib
import sys
import tempfile
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.repository import CaseRepository


class SegmentationManifestRepositoryTests(unittest.TestCase):
    def test_save_mask_persists_manifest_and_labeled_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = CaseRepository(pathlib.Path(tmpdir), state_store=None, object_store=None)
            repo.create_case("case-1")
            repo.save_ct_volume("case-1", np.zeros((8, 8, 8), dtype=np.int16), (1.0, 1.0, 1.0))

            labeled_mask = np.zeros((8, 8, 8), dtype=np.uint8)
            labeled_mask[1:4, 1:4, 1:4] = 1
            labeled_mask[4:7, 1:4, 1:4] = 2
            labeled_mask[3:5, 3:5, 3:5] = 3
            manifest = {
                "version": 1,
                "has_labeled_mask": True,
                "labels": [
                    {"label_id": 1, "key": "left_lung", "display_name": "Left Lung", "color": "#60a5fa", "available": True, "visible_by_default": True, "render_2d": True, "render_3d": True, "voxel_count": 27, "mesh_component_name": "left_lung"},
                    {"label_id": 2, "key": "right_lung", "display_name": "Right Lung", "color": "#34d399", "available": True, "visible_by_default": True, "render_2d": True, "render_3d": True, "voxel_count": 27, "mesh_component_name": "right_lung"},
                    {"label_id": 3, "key": "nodule", "display_name": "Nodule", "color": "#f97316", "available": True, "visible_by_default": True, "render_2d": True, "render_3d": True, "voxel_count": 8, "mesh_component_name": "nodule"},
                ],
            }

            repo.save_mask("case-1", labeled_mask, manifest=manifest)

            loaded_mask = repo.load_mask("case-1")
            loaded_manifest = repo.load_mask_manifest("case-1")
            self.assertIsNotNone(loaded_mask)
            self.assertIsNotNone(loaded_manifest)
            np.testing.assert_array_equal(loaded_mask, labeled_mask)
            self.assertTrue(loaded_manifest["has_labeled_mask"])
            self.assertEqual(loaded_manifest["labels"][2]["key"], "nodule")


if __name__ == "__main__":
    unittest.main()
