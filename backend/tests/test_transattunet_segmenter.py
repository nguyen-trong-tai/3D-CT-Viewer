import pathlib
import sys
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.transattunet import (
    TransAttUnet,
    TransAttUnetPatchSegmenter,
    TransAttUnetPatchSegmenterConfig,
)


def _reference_extract_patch(array: np.ndarray, center_y: float, center_x: float, patch_size: int, pad_value: float = 0.0):
    height, width = array.shape
    output = np.full((patch_size, patch_size), pad_value, dtype=array.dtype)
    half = patch_size // 2
    center_y_i = int(round(center_y))
    center_x_i = int(round(center_x))

    src_y0 = max(center_y_i - half, 0)
    src_x0 = max(center_x_i - half, 0)
    src_y1 = min(src_y0 + patch_size, height)
    src_x1 = min(src_x0 + patch_size, width)
    if src_y1 - src_y0 < patch_size:
        src_y0 = max(src_y1 - patch_size, 0)
    if src_x1 - src_x0 < patch_size:
        src_x0 = max(src_x1 - patch_size, 0)

    crop = array[src_y0:src_y1, src_x0:src_x1]
    dst_y0 = (patch_size - crop.shape[0]) // 2
    dst_x0 = (patch_size - crop.shape[1]) // 2
    output[dst_y0:dst_y0 + crop.shape[0], dst_x0:dst_x0 + crop.shape[1]] = crop
    target_y = float(dst_y0 + (center_y_i - src_y0))
    target_x = float(dst_x0 + (center_x_i - src_x0))
    return output, target_y, target_x


class TransAttUnetPatchSegmenterTests(unittest.TestCase):
    def test_checkpoint_loads_and_runs_forward_on_128_patch(self):
        segmenter = TransAttUnetPatchSegmenter.from_checkpoint(
            ROOT / "sandbox" / "checkpoints" / "segmentation" / "TransAttUnet_v2.pth",
            config=TransAttUnetPatchSegmenterConfig(device="cpu"),
        )

        patch = segmenter.segment_slice_patch(
            np.zeros((256, 256), dtype=np.float32),
            center_y=32.0,
            center_x=64.0,
        )

        self.assertEqual(patch.shape, (128, 128))
        self.assertGreaterEqual(float(patch.min()), 0.0)
        self.assertLessEqual(float(patch.max()), 1.0)

    def test_segment_slice_with_mapping_keeps_input_patch_for_debug(self):
        config = TransAttUnetPatchSegmenterConfig(device="cpu")
        segmenter = TransAttUnetPatchSegmenter(TransAttUnet(n_channels=1, n_classes=2), config=config)

        result = segmenter.segment_slice_with_mapping(
            np.zeros((256, 256), dtype=np.float32),
            center_y=40.0,
            center_x=80.0,
        )

        self.assertEqual(result.probability_patch.shape, (128, 128))
        self.assertEqual(result.input_patch.shape, (128, 128))
        self.assertEqual(result.logits_patch.shape[0], 2)

    def test_prepare_slice_patch_matches_reference_direct_crop(self):
        config = TransAttUnetPatchSegmenterConfig(device="cpu")
        segmenter = TransAttUnetPatchSegmenter(TransAttUnet(n_channels=1, n_classes=2), config=config)

        slice_hu = np.arange(64 * 64, dtype=np.float32).reshape(64, 64) - 500.0
        prepared = segmenter.prepare_slice_patch(slice_hu, center_y=3.0, center_x=5.0)

        normalized = segmenter.normalize_slice(slice_hu)
        expected_patch, target_y, target_x = _reference_extract_patch(
            normalized,
            center_y=3.0,
            center_x=5.0,
            patch_size=config.image_size,
            pad_value=0.0,
        )

        np.testing.assert_allclose(prepared.input_patch, expected_patch)
        self.assertEqual(prepared.mapping.slice_row_start, 0)
        self.assertEqual(prepared.mapping.slice_col_start, 0)
        self.assertGreater(prepared.mapping.slice_row_end, 0)
        self.assertGreater(prepared.mapping.slice_col_end, 0)
        self.assertAlmostEqual(prepared.mapping.target_center_y_in_roi, target_y)
        self.assertAlmostEqual(prepared.mapping.target_center_x_in_roi, target_x)

    def test_prepare_slice_patch_handles_interior_center_without_composed_roi_mapping(self):
        config = TransAttUnetPatchSegmenterConfig(device="cpu")
        segmenter = TransAttUnetPatchSegmenter(TransAttUnet(n_channels=1, n_classes=2), config=config)

        slice_hu = np.arange(256 * 256, dtype=np.float32).reshape(256, 256) - 1000.0
        prepared = segmenter.prepare_slice_patch(slice_hu, center_y=100.0, center_x=120.0)

        normalized = segmenter.normalize_slice(slice_hu)
        expected_patch = normalized[36:164, 56:184]

        np.testing.assert_allclose(prepared.input_patch, expected_patch)
        self.assertEqual(prepared.mapping.slice_row_start, 36)
        self.assertEqual(prepared.mapping.slice_row_end, 164)
        self.assertEqual(prepared.mapping.slice_col_start, 56)
        self.assertEqual(prepared.mapping.slice_col_end, 184)
        self.assertEqual(prepared.mapping.patch_row_start, 0)
        self.assertEqual(prepared.mapping.patch_row_end, 128)
        self.assertEqual(prepared.mapping.patch_col_start, 0)
        self.assertEqual(prepared.mapping.patch_col_end, 128)
        self.assertAlmostEqual(prepared.mapping.target_center_y_in_roi, 64.0)
        self.assertAlmostEqual(prepared.mapping.target_center_x_in_roi, 64.0)


if __name__ == "__main__":
    unittest.main()
