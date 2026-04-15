import pathlib
import sys
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processing.Detection import DeepLungDetector, DeepLungDetectorConfig, GetPBB, nms_3d


class DeepLungDetectorTests(unittest.TestCase):
    def test_get_pbb_decodes_anchor_offsets(self):
        decoder = GetPBB(stride=4, anchors=(5.0, 10.0, 20.0))
        output = np.zeros((1, 1, 1, 3, 5), dtype=np.float32)
        output[0, 0, 0, 1] = np.array([2.0, 0.1, -0.2, 0.3, np.log(1.5)], dtype=np.float32)

        candidates = decoder(output, threshold=0.5)

        self.assertEqual(candidates.shape, (1, 5))
        self.assertAlmostEqual(float(candidates[0, 0]), 2.0, places=5)
        self.assertAlmostEqual(float(candidates[0, 1]), 1.5 + 0.1 * 10.0, places=5)
        self.assertAlmostEqual(float(candidates[0, 2]), 1.5 - 0.2 * 10.0, places=5)
        self.assertAlmostEqual(float(candidates[0, 3]), 1.5 + 0.3 * 10.0, places=5)
        self.assertAlmostEqual(float(candidates[0, 4]), 15.0, places=4)

    def test_nms_suppresses_overlapping_candidates(self):
        candidates = np.array(
            [
                [2.0, 10.0, 10.0, 10.0, 10.0],
                [1.9, 11.0, 10.5, 10.5, 10.0],
                [1.0, 40.0, 40.0, 40.0, 10.0],
            ],
            dtype=np.float32,
        )

        kept = nms_3d(candidates, nms_threshold=0.1)

        self.assertEqual(kept.shape[0], 2)
        self.assertAlmostEqual(float(kept[0, 0]), 2.0, places=5)
        self.assertAlmostEqual(float(kept[1, 0]), 1.0, places=5)

    def test_prepare_volume_builds_cropped_detector_input(self):
        config = DeepLungDetectorConfig()
        detector = DeepLungDetector.from_checkpoint(
            ROOT / "sandbox" / "checkpoints" / "detection" / "DeepLung.ckpt",
            config=DeepLungDetectorConfig(device="cpu"),
        )

        volume = np.full((48, 48, 24), -1000, dtype=np.int16)
        volume[10:38, 8:40, 4:20] = -700
        volume[14:34, 12:36, 6:18] = -300

        lung_mask = np.zeros_like(volume, dtype=bool)
        lung_mask[8:40, 6:42, 3:21] = True

        prepared = detector.prepare_volume(volume, (0.8, 0.8, 2.5), lung_mask)

        self.assertEqual(prepared.clean_volume_zyx.ndim, 4)
        self.assertEqual(prepared.clean_volume_zyx.shape[0], 1)
        self.assertTrue(np.all(prepared.extendbox_zyx[:, 0] < prepared.extendbox_zyx[:, 1]))
        self.assertGreater(int(np.prod(prepared.clean_volume_zyx.shape[1:])), 0)

    def test_checkpoint_loads_and_empty_mask_short_circuits(self):
        detector = DeepLungDetector.from_checkpoint(
            ROOT / "sandbox" / "checkpoints" / "detection" / "DeepLung.ckpt",
            config=DeepLungDetectorConfig(device="cpu"),
        )

        result = detector.detect(
            volume_hu_xyz=np.zeros((16, 16, 16), dtype=np.int16),
            spacing_xyz_mm=(1.0, 1.0, 1.0),
            lung_mask_xyz=np.zeros((16, 16, 16), dtype=bool),
        )

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["debug"]["reason"], "empty_lung_mask")

    def test_detect_returns_debug_artifacts_for_visualization(self):
        detector = DeepLungDetector.from_checkpoint(
            ROOT / "sandbox" / "checkpoints" / "detection" / "DeepLung.ckpt",
            config=DeepLungDetectorConfig(device="cpu"),
        )

        volume = np.full((32, 32, 16), -900, dtype=np.int16)
        lung_mask = np.zeros_like(volume, dtype=bool)
        lung_mask[4:28, 4:28, 2:14] = True

        result = detector.detect(
            volume_hu_xyz=volume,
            spacing_xyz_mm=(1.0, 1.0, 1.0),
            lung_mask_xyz=lung_mask,
            top_k=2,
        )

        self.assertIn("preprocess", result)
        self.assertIn("raw_candidates_zyx", result)
        self.assertIn("post_nms_candidates_zyx", result)
        self.assertIn("selected_candidates_zyx", result)
        self.assertEqual(result["preprocess"]["clean_volume_zyx"].ndim, 4)
        self.assertEqual(result["debug"]["top_k"], 2)
        self.assertIn("combined_output_shape", result["debug"])


if __name__ == "__main__":
    unittest.main()
