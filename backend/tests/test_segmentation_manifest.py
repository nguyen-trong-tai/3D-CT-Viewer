import pathlib
import sys
import tempfile
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.repository import CaseRepository
from services.ai_segmentation import AISegmentationService


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
                "nodule_entities": [
                    {
                        "id": "nodule_001",
                        "display_name": "Nodule 1",
                        "mesh_component_name": "nodule_001",
                        "voxel_count": 8,
                        "volume_mm3": 8.0,
                        "volume_ml": 0.008,
                        "centroid_xyz": [3.5, 3.5, 3.5],
                        "centroid_mm": [3.5, 3.5, 3.5],
                        "bbox_xyz": [[3, 5], [3, 5], [3, 5]],
                        "bbox_mm": [[3.0, 5.0], [3.0, 5.0], [3.0, 5.0]],
                        "extents_mm": [2.0, 2.0, 2.0],
                        "estimated_diameter_mm": 2.0,
                        "slice_range": [3, 4],
                    }
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
            self.assertEqual(loaded_manifest["nodule_entities"][0]["id"], "nodule_001")


class AISegmentationServiceNoduleEntityTests(unittest.TestCase):
    def test_build_nodule_components_splits_connected_components(self):
        service = AISegmentationService()

        nodule_mask = np.zeros((12, 12, 12), dtype=bool)
        nodule_mask[1:4, 1:4, 2:5] = True
        nodule_mask[7:10, 6:9, 7:10] = True

        nodule_components = service._build_nodule_components(nodule_mask, (1.0, 1.0, 2.0))

        self.assertEqual(len(nodule_components), 2)
        self.assertEqual(nodule_components[0]["entity"]["id"], "nodule_001")
        self.assertEqual(nodule_components[1]["entity"]["id"], "nodule_002")
        self.assertEqual(nodule_components[0]["entity"]["mesh_component_name"], "nodule_001")
        self.assertEqual(nodule_components[0]["entity"]["slice_range"], [2, 4])
        self.assertGreater(nodule_components[0]["entity"]["estimated_diameter_mm"], 0.0)
        self.assertEqual(tuple(nodule_components[0]["mask"].shape), (3, 3, 3))
        self.assertEqual(tuple(nodule_components[0]["mask_origin_xyz"]), (1, 1, 2))

    def test_build_nodule_components_prefers_candidate_matched_components(self):
        service = AISegmentationService()

        nodule_mask = np.zeros((16, 16, 16), dtype=bool)
        nodule_mask[2:6, 2:6, 3:7] = True
        nodule_mask[12:13, 12:13, 12:13] = True

        nodule_components = service._build_nodule_components(
            nodule_mask,
            (1.0, 1.0, 1.0),
            accepted_candidates=[
                {
                    "accepted": True,
                    "candidate_index": 3,
                    "score_probability": 0.91,
                    "score_logit": 2.0,
                    "center_xyz": [3.5, 3.5, 4.5],
                    "center_xyz_rounded": [4, 4, 4],
                    "diameter_mm": 4.0,
                }
            ],
        )

        self.assertEqual(len(nodule_components), 1)
        self.assertEqual(nodule_components[0]["entity"]["id"], "nodule_001")
        self.assertGreater(nodule_components[0]["entity"]["voxel_count"], 1)
        self.assertEqual(nodule_components[0]["entity"]["match_source"], "candidate_match")
        self.assertEqual(nodule_components[0]["entity"]["candidate_index"], 3)

    def test_build_nodule_components_orders_matches_by_candidate_priority(self):
        service = AISegmentationService()

        nodule_mask = np.zeros((20, 20, 20), dtype=bool)
        nodule_mask[2:8, 2:8, 2:8] = True
        nodule_mask[12:15, 12:15, 12:15] = True

        nodule_components = service._build_nodule_components(
            nodule_mask,
            (1.0, 1.0, 1.0),
            accepted_candidates=[
                {
                    "accepted": True,
                    "candidate_index": 1,
                    "score_probability": 0.99,
                    "center_xyz": [13.0, 13.0, 13.0],
                    "center_xyz_rounded": [13, 13, 13],
                    "diameter_mm": 3.0,
                },
                {
                    "accepted": True,
                    "candidate_index": 2,
                    "score_probability": 0.60,
                    "center_xyz": [4.0, 4.0, 4.0],
                    "center_xyz_rounded": [4, 4, 4],
                    "diameter_mm": 6.0,
                },
            ],
        )

        self.assertEqual(len(nodule_components), 2)
        self.assertEqual(nodule_components[0]["entity"]["candidate_index"], 1)
        self.assertEqual(nodule_components[0]["entity"]["bbox_xyz"], [[12, 15], [12, 15], [12, 15]])
        self.assertEqual(nodule_components[1]["entity"]["candidate_index"], 2)


if __name__ == "__main__":
    unittest.main()
