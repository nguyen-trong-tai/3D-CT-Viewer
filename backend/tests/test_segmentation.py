import pathlib
import sys
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processing.segmentation import LungSegmenter


class LungSegmenterTests(unittest.TestCase):
    def test_keeps_internal_air_when_lungs_touch_first_z_slice(self):
        segmenter = LungSegmenter(min_lung_volume=1, min_component_slices=1)

        volume = np.full((32, 32, 16), -1000, dtype=np.int16)
        volume[4:28, 4:28, :] = 50
        volume[8:14, 8:24, 0:12] = -800
        volume[18:24, 8:24, 0:12] = -800

        result = segmenter.segment(volume)

        self.assertGreater(int(result["lung_mask"].sum()), 0)
        self.assertGreater(int(result["left_mask"].sum()), 0)
        self.assertGreater(int(result["right_mask"].sum()), 0)
        self.assertTrue(result["lung_mask"][:, :, 0].any())
        self.assertIn("components", result)
        self.assertIn("left_lung", result["components"])
        self.assertIn("right_lung", result["components"])
        self.assertTrue(result["components"]["lung"]["render_2d"])
        self.assertFalse(result["components"]["lung"]["render_3d"])
        self.assertTrue(result["components"]["left_lung"]["render_3d"])
        self.assertTrue(result["components"]["right_lung"]["render_3d"])

    def test_left_right_split_uses_x_axis(self):
        segmenter = LungSegmenter()

        mask = np.zeros((24, 16, 8), dtype=bool)
        mask[2:7, 3:13, 1:7] = True
        mask[16:21, 3:13, 1:7] = True

        left_mask, right_mask = segmenter._separate_lobes(mask)

        left_coords = np.argwhere(left_mask)
        right_coords = np.argwhere(right_mask)

        self.assertGreater(left_coords.size, 0)
        self.assertGreater(right_coords.size, 0)
        self.assertGreater(left_coords[:, 0].min(), right_coords[:, 0].max())
        self.assertEqual(set(np.unique(left_coords[:, 2]).tolist()), set(range(1, 7)))
        self.assertEqual(set(np.unique(right_coords[:, 2]).tolist()), set(range(1, 7)))


if __name__ == "__main__":
    unittest.main()
