import pathlib
import sys
import types
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.nodule_mask_pipeline import NoduleMaskPipeline, NoduleMaskPipelineConfig


def _build_direct_mapping(shape: tuple[int, int], center_y: float, center_x: float, patch_size: int = 128):
    height, width = shape
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

    crop_height = src_y1 - src_y0
    crop_width = src_x1 - src_x0
    dst_y0 = (patch_size - crop_height) // 2
    dst_x0 = (patch_size - crop_width) // 2
    return types.SimpleNamespace(
        slice_row_start=int(src_y0),
        slice_row_end=int(src_y1),
        slice_col_start=int(src_x0),
        slice_col_end=int(src_x1),
        patch_row_start=int(dst_y0),
        patch_row_end=int(dst_y0 + crop_height),
        patch_col_start=int(dst_x0),
        patch_col_end=int(dst_x0 + crop_width),
    )


class FakeDetector:
    def __init__(self, candidates):
        self._candidates = list(candidates)

    def detect(self, **kwargs):
        raw_candidates = np.asarray(
            [
                [
                    float(candidate.get("score_logit", 0.0)),
                    float(candidate.get("center_xyz", [0.0, 0.0, 0.0])[2]),
                    float(candidate.get("center_xyz", [0.0, 0.0, 0.0])[1]),
                    float(candidate.get("center_xyz", [0.0, 0.0, 0.0])[0]),
                    float(candidate.get("diameter_mm", 0.0)),
                ]
                for candidate in self._candidates
            ],
            dtype=np.float32,
        )
        return {
            "candidates": list(self._candidates),
            "preprocess": {
                "clean_volume_zyx": np.zeros((1, 8, 8, 8), dtype=np.uint8),
                "extendbox_zyx": np.zeros((3, 2), dtype=np.int32),
            },
            "raw_candidates_zyx": raw_candidates,
            "post_nms_candidates_zyx": raw_candidates,
            "debug": {"stub": True},
        }


class FakePatchSegmenter:
    def __init__(self, patch_size: int = 128, blob_half_size: int = 4, include_noise: bool = False, emit_empty: bool = False):
        self.patch_size = patch_size
        self.blob_half_size = blob_half_size
        self.include_noise = include_noise
        self.emit_empty = emit_empty
        self.config = types.SimpleNamespace(foreground_threshold=0.45)

    def segment_slice_with_mapping(self, slice_2d: np.ndarray, center_y: float, center_x: float):
        mapping = _build_direct_mapping(slice_2d.shape, center_y, center_x, patch_size=self.patch_size)
        patch = np.zeros((self.patch_size, self.patch_size), dtype=np.float32)
        input_patch = np.zeros((self.patch_size, self.patch_size), dtype=np.float32)
        if not self.emit_empty:
            center_row = int(round((mapping.patch_row_start + mapping.patch_row_end - 1) / 2.0))
            center_col = int(round((mapping.patch_col_start + mapping.patch_col_end - 1) / 2.0))
            y0 = max(0, center_row - self.blob_half_size)
            y1 = min(self.patch_size, center_row + self.blob_half_size + 1)
            x0 = max(0, center_col - self.blob_half_size)
            x1 = min(self.patch_size, center_col + self.blob_half_size + 1)
            patch[y0:y1, x0:x1] = 0.95
            input_patch[y0:y1, x0:x1] = 1.0
            if self.include_noise:
                patch[2:4, 2:4] = 0.9
        return types.SimpleNamespace(probability_patch=patch, mapping=mapping, input_patch=input_patch)

    def describe(self):
        return {"stub": True}


class OffsetBlobPatchSegmenter(FakePatchSegmenter):
    def __init__(self, offset_y: int = 0, offset_x: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.offset_y = int(offset_y)
        self.offset_x = int(offset_x)

    def segment_slice_with_mapping(self, slice_2d: np.ndarray, center_y: float, center_x: float):
        mapping = _build_direct_mapping(slice_2d.shape, center_y, center_x, patch_size=self.patch_size)
        patch = np.zeros((self.patch_size, self.patch_size), dtype=np.float32)
        input_patch = np.zeros((self.patch_size, self.patch_size), dtype=np.float32)
        if not self.emit_empty:
            center_row = int(round((mapping.patch_row_start + mapping.patch_row_end - 1) / 2.0)) + self.offset_y
            center_col = int(round((mapping.patch_col_start + mapping.patch_col_end - 1) / 2.0)) + self.offset_x
            center_row = int(np.clip(center_row, 0, self.patch_size - 1))
            center_col = int(np.clip(center_col, 0, self.patch_size - 1))
            y0 = max(0, center_row - self.blob_half_size)
            y1 = min(self.patch_size, center_row + self.blob_half_size + 1)
            x0 = max(0, center_col - self.blob_half_size)
            x1 = min(self.patch_size, center_col + self.blob_half_size + 1)
            patch[y0:y1, x0:x1] = 0.95
            input_patch[y0:y1, x0:x1] = 1.0
        return types.SimpleNamespace(probability_patch=patch, mapping=mapping, input_patch=input_patch)


class HollowCorePatchSegmenter(FakePatchSegmenter):
    def segment_slice_with_mapping(self, slice_2d: np.ndarray, center_y: float, center_x: float):
        mapping = _build_direct_mapping(slice_2d.shape, center_y, center_x, patch_size=self.patch_size)
        patch = np.zeros((self.patch_size, self.patch_size), dtype=np.float32)
        input_patch = np.zeros((self.patch_size, self.patch_size), dtype=np.float32)
        if not self.emit_empty:
            center_row = int(round((mapping.patch_row_start + mapping.patch_row_end - 1) / 2.0))
            center_col = int(round((mapping.patch_col_start + mapping.patch_col_end - 1) / 2.0))
            outer_y0 = max(0, center_row - 5)
            outer_y1 = min(self.patch_size, center_row + 6)
            outer_x0 = max(0, center_col - 5)
            outer_x1 = min(self.patch_size, center_col + 6)
            inner_y0 = max(0, center_row - 2)
            inner_y1 = min(self.patch_size, center_row + 3)
            inner_x0 = max(0, center_col - 2)
            inner_x1 = min(self.patch_size, center_col + 3)
            patch[outer_y0:outer_y1, outer_x0:outer_x1] = 0.72
            patch[inner_y0:inner_y1, inner_x0:inner_x1] = 0.22
            input_patch[outer_y0:outer_y1, outer_x0:outer_x1] = 1.0
        return types.SimpleNamespace(probability_patch=patch, mapping=mapping, input_patch=input_patch)


class NoduleMaskPipelineTests(unittest.TestCase):
    def test_coordinate_mapping_round_trips_to_original_shape(self):
        candidates = [
            {
                "center_xyz": [5.0, 10.0, 4.0],
                "score_logit": 1.0,
                "score_probability": 0.73,
                "diameter_mm": 4.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=FakePatchSegmenter(),
            config=NoduleMaskPipelineConfig(),
        )

        volume = np.zeros((32, 32, 12), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        result = pipeline.run(volume, spacing_xyz_mm=(2.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertEqual(result.final_mask_xyz.shape, volume.shape)
        self.assertEqual(result.final_mask_resampled_xyz.shape[0], 64)
        self.assertEqual(result.candidates[0]["center_xyz_resampled_rounded"][0], 10)
        self.assertGreater(int(result.final_mask_xyz.sum()), 0)

    def test_local_filter_removes_small_noise_and_keeps_center_component(self):
        candidates = [
            {
                "center_xyz": [24.0, 24.0, 6.0],
                "score_logit": 1.0,
                "score_probability": 0.73,
                "diameter_mm": 5.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=FakePatchSegmenter(include_noise=True),
            config=NoduleMaskPipelineConfig(),
        )

        volume = np.zeros((64, 64, 16), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertTrue(result.candidates[0]["accepted"])
        self.assertEqual(result.component_stats[0]["label_id"], 1)
        self.assertGreater(result.component_stats[0]["voxel_count"], 10)
        self.assertLess(result.component_stats[0]["voxel_count"], 5000)

    def test_probability_fusion_merges_overlapping_candidates(self):
        candidates = [
            {
                "center_xyz": [32.0, 32.0, 8.0],
                "score_logit": 2.0,
                "score_probability": 0.88,
                "diameter_mm": 8.0,
            },
            {
                "center_xyz": [36.0, 32.0, 8.0],
                "score_logit": 1.8,
                "score_probability": 0.85,
                "diameter_mm": 8.0,
            },
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=FakePatchSegmenter(blob_half_size=6),
            config=NoduleMaskPipelineConfig(),
        )

        volume = np.zeros((80, 80, 20), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertEqual(len(result.component_stats), 1)
        self.assertTrue(all(candidate["accepted"] for candidate in result.candidates))
        self.assertGreater(int(result.final_mask_resampled_xyz.sum()), 0)

    def test_empty_patch_predictions_are_rejected(self):
        candidates = [
            {
                "center_xyz": [16.0, 16.0, 4.0],
                "score_logit": 1.0,
                "score_probability": 0.73,
                "diameter_mm": 4.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=FakePatchSegmenter(emit_empty=True),
            config=NoduleMaskPipelineConfig(),
        )

        volume = np.zeros((32, 32, 12), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertFalse(result.candidates[0]["accepted"])
        self.assertEqual(result.candidates[0]["reason"], "empty_after_threshold")
        self.assertEqual(int(result.final_mask_xyz.sum()), 0)
        self.assertEqual(len(result.candidate_debug_volumes), 1)
        self.assertIsNone(result.candidate_debug_volumes[0]["filtered_probability_xyz"])

    def test_raw_candidate_probability_is_retained_for_debug_visualization(self):
        candidates = [
            {
                "center_xyz": [20.0, 18.0, 5.0],
                "score_logit": 1.2,
                "score_probability": 0.77,
                "diameter_mm": 6.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=FakePatchSegmenter(),
            config=NoduleMaskPipelineConfig(),
        )

        volume = np.zeros((48, 48, 16), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertEqual(len(result.candidate_debug_volumes), 1)
        debug_item = result.candidate_debug_volumes[0]
        self.assertEqual(debug_item["candidate_index"], 1)
        self.assertIn("raw_probability_xyz", debug_item)
        self.assertIn("filtered_probability_xyz", debug_item)
        self.assertIn("filtered_binary_xyz", debug_item)
        self.assertGreater(float(np.asarray(debug_item["raw_probability_xyz"]).max()), 0.0)
        self.assertGreater(float(np.asarray(debug_item["filtered_probability_xyz"]).max()), 0.0)
        bbox = debug_item["local_bbox_resampled_xyz"]
        raw_shape = np.asarray(debug_item["raw_probability_xyz"]).shape
        filtered_shape = np.asarray(debug_item["filtered_probability_xyz"]).shape
        filtered_binary_shape = np.asarray(debug_item["filtered_binary_xyz"]).shape
        self.assertEqual(raw_shape[0], bbox[0][1] - bbox[0][0])
        self.assertEqual(raw_shape[1], bbox[1][1] - bbox[1][0])
        self.assertEqual(raw_shape[2], bbox[2][1] - bbox[2][0])
        self.assertEqual(filtered_shape, raw_shape)
        self.assertEqual(filtered_binary_shape, raw_shape)
        self.assertIsNotNone(result.detector_output)
        self.assertEqual(result.detector_output.debug["stub"], True)
        self.assertEqual(result.detector_output.raw_candidates_zyx.shape[0], 1)
        self.assertIn("clean_volume_zyx", result.detector_output.preprocess)
        self.assertIsNotNone(result.segmentor_output)
        self.assertEqual(len(result.segmentor_output.candidates), 1)
        self.assertGreater(int(np.asarray(result.segmentor_output.binary_volume_resampled_xyz, dtype=np.uint8).sum()), 0)
        self.assertEqual(len(debug_item["segmentor_slices"]), raw_shape[2])
        self.assertIsNotNone(debug_item["segmentor_slices"][0]["input_patch_yx"])
        self.assertIn("mapping", debug_item["segmentor_slices"][0])

    def test_local_filter_keeps_near_center_small_component_as_fallback(self):
        candidates = [
            {
                "center_xyz": [20.0, 20.0, 5.0],
                "score_logit": 1.0,
                "score_probability": 0.73,
                "diameter_mm": 4.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=OffsetBlobPatchSegmenter(offset_y=5, offset_x=0, blob_half_size=1),
            config=NoduleMaskPipelineConfig(min_component_volume_mm3=10.0),
        )

        volume = np.zeros((48, 48, 16), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertTrue(result.candidates[0]["accepted"])
        self.assertEqual(result.candidates[0]["local_stats"]["selection_mode"], "probability_near_center")
        self.assertGreater(int(result.final_mask_xyz.sum()), 0)

    def test_local_filter_relaxes_lung_mask_to_keep_pleural_candidate(self):
        candidates = [
            {
                "center_xyz": [20.0, 20.0, 5.0],
                "score_logit": 1.0,
                "score_probability": 0.73,
                "diameter_mm": 5.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=OffsetBlobPatchSegmenter(offset_y=-4, offset_x=0, blob_half_size=2),
            config=NoduleMaskPipelineConfig(local_lung_mask_dilation_iters=1),
        )

        volume = np.zeros((48, 48, 16), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        lung_mask[18:23, 13:17, 2:9] = False
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertTrue(result.candidates[0]["accepted"])
        self.assertGreater(int(result.final_mask_xyz.sum()), 0)

    def test_local_filter_grows_and_fills_soft_core_near_center(self):
        candidates = [
            {
                "center_xyz": [24.0, 24.0, 6.0],
                "score_logit": 1.0,
                "score_probability": 0.73,
                "diameter_mm": 6.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=HollowCorePatchSegmenter(),
            config=NoduleMaskPipelineConfig(local_support_threshold=0.15),
        )

        volume = np.zeros((64, 64, 16), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertTrue(result.candidates[0]["accepted"])
        local_stats = result.candidates[0]["local_stats"]
        self.assertGreater(int(local_stats["grown_voxel_count"]), int(local_stats["selected_voxel_count"]))
        debug_item = result.candidate_debug_volumes[0]
        filtered_probability = np.asarray(debug_item["filtered_probability_xyz"], dtype=np.float32)
        filtered_binary = np.asarray(debug_item["filtered_binary_xyz"], dtype=np.uint8)
        bbox = debug_item["local_bbox_resampled_xyz"]
        center_resampled = np.asarray(result.candidates[0]["center_xyz_resampled_rounded"], dtype=int)
        local_center = center_resampled - np.array([bbox[0][0], bbox[1][0], bbox[2][0]], dtype=int)
        self.assertGreater(float(filtered_probability[local_center[0], local_center[1], local_center[2]]), 0.0)
        self.assertGreater(int(filtered_binary[local_center[0], local_center[1], local_center[2]]), 0)

    def test_final_postprocess_preserves_candidate_binary_across_lung_mask_hole(self):
        candidates = [
            {
                "center_xyz": [24.0, 24.0, 6.0],
                "score_logit": 1.4,
                "score_probability": 0.8,
                "diameter_mm": 6.0,
            }
        ]
        pipeline = NoduleMaskPipeline(
            detector=FakeDetector(candidates),
            patch_segmenter=HollowCorePatchSegmenter(),
            config=NoduleMaskPipelineConfig(
                local_support_threshold=0.15,
                postprocess_lung_mask_dilation_iters=0,
            ),
        )

        volume = np.zeros((64, 64, 16), dtype=np.int16)
        lung_mask = np.ones_like(volume, dtype=bool)
        lung_mask[18:31, 18:31, 3:10] = False
        result = pipeline.run(volume, spacing_xyz_mm=(1.0, 1.0, 1.0), lung_mask_xyz=lung_mask)

        self.assertTrue(result.candidates[0]["accepted"])
        self.assertGreater(int(np.asarray(result.segmentor_output.binary_volume_resampled_xyz, dtype=np.uint8).sum()), 0)
        self.assertGreater(int(result.final_mask_resampled_xyz.sum()), 0)
        self.assertGreater(int(result.final_mask_xyz.sum()), 0)


if __name__ == "__main__":
    unittest.main()
