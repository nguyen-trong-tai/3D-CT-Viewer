from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .candidate_filter import CandidateProbabilityFilter
from .models import (
    BBoxXYZ,
    CandidateMaskResult,
    CandidateSegmentationStageOutput,
    DetectorStageOutput,
    NoduleMaskPipelineConfig,
    PreparedPipelineInputs,
    SegmentorCandidateOutput,
    SegmentorSliceDebug,
)


@dataclass(frozen=True)
class _SliceSegmentationResult:
    z_index: int
    probability_patch: np.ndarray
    mapping: dict[str, Any]
    input_patch: np.ndarray | None


class CandidateSegmentationStage:
    def __init__(
        self,
        patch_segmenter: Any,
        config: NoduleMaskPipelineConfig,
        probability_filter: CandidateProbabilityFilter | None = None,
    ) -> None:
        self.patch_segmenter = patch_segmenter
        self.config = config
        self.probability_filter = probability_filter or CandidateProbabilityFilter(config)

    def run(
        self,
        prepared: PreparedPipelineInputs,
        detector_output: DetectorStageOutput,
    ) -> CandidateSegmentationStageOutput:
        probability_resampled_xyz = np.zeros_like(prepared.resampled_volume_xyz, dtype=np.float32)
        binary_resampled_xyz = np.zeros_like(prepared.resampled_volume_xyz, dtype=bool)
        candidate_records: list[dict[str, Any]] = []
        candidate_debug_volumes: list[dict[str, Any]] = []
        structured_candidates: list[SegmentorCandidateOutput] = []
        accepted_candidates = 0

        for candidate_index, candidate in enumerate(detector_output.candidates, start=1):
            candidate_result = self._process_candidate(prepared, dict(candidate), candidate_index)
            candidate_records.append(candidate_result.record)
            structured_candidates.append(self._build_structured_candidate(candidate_result))
            if candidate_result.raw_probability_xyz is not None and candidate_result.local_bbox_xyz is not None:
                candidate_debug_volumes.append(self._build_debug_volume(candidate_result))
            if (
                not candidate_result.accepted
                or candidate_result.local_probability_xyz is None
                or candidate_result.local_binary_xyz is None
                or candidate_result.local_bbox_xyz is None
            ):
                continue

            accepted_candidates += 1
            (x0, x1), (y0, y1), (z0, z1) = candidate_result.local_bbox_xyz
            probability_resampled_xyz[x0:x1, y0:y1, z0:z1] = np.maximum(
                probability_resampled_xyz[x0:x1, y0:y1, z0:z1],
                candidate_result.local_probability_xyz,
            )
            binary_resampled_xyz[x0:x1, y0:y1, z0:z1] |= np.asarray(candidate_result.local_binary_xyz, dtype=bool)

        return CandidateSegmentationStageOutput(
            probability_volume_resampled_xyz=probability_resampled_xyz,
            binary_volume_resampled_xyz=binary_resampled_xyz,
            candidate_records=candidate_records,
            candidate_debug_volumes=candidate_debug_volumes,
            candidates=structured_candidates,
            accepted_candidate_count=int(accepted_candidates),
        )

    def _process_candidate(
        self,
        prepared: PreparedPipelineInputs,
        candidate: dict[str, Any],
        candidate_index: int,
    ) -> CandidateMaskResult:
        center_original_xyz = np.asarray(candidate.get("center_xyz", (0.0, 0.0, 0.0)), dtype=np.float32)
        center_resampled_xyz = self._map_center_to_resampled(center_original_xyz, prepared.spacing_xyz_mm)
        center_resampled_xyz = np.clip(
            center_resampled_xyz,
            0.0,
            np.asarray(prepared.resampled_volume_xyz.shape, dtype=np.float32) - 1.0,
        )

        diameter_mm = max(1.0, float(candidate.get("diameter_mm", 1.0)))
        half_depth_vox = int(math.ceil(diameter_mm / 2.0) + 2)
        center_z = int(round(float(center_resampled_xyz[2])))
        z_start = max(0, center_z - half_depth_vox)
        z_end = min(prepared.resampled_volume_xyz.shape[2], center_z + half_depth_vox + 1)
        if z_start >= z_end:
            return CandidateMaskResult(
                accepted=False,
                record=self._build_candidate_record(
                    candidate_index,
                    candidate,
                    center_resampled_xyz,
                    False,
                    "invalid_z_window",
                    half_depth_vox,
                ),
            )

        reference_z = int(np.clip(center_z, z_start, z_end - 1))
        reference_result = self._segment_slice(
            prepared.resampled_volume_xyz[:, :, reference_z].T,
            center_y=float(center_resampled_xyz[1]),
            center_x=float(center_resampled_xyz[0]),
            z_index=reference_z,
        )

        x_start = int(reference_result.mapping["slice_col_start"])
        x_end = int(reference_result.mapping["slice_col_end"])
        y_start = int(reference_result.mapping["slice_row_start"])
        y_end = int(reference_result.mapping["slice_row_end"])
        if x_start >= x_end or y_start >= y_end:
            return CandidateMaskResult(
                accepted=False,
                record=self._build_candidate_record(
                    candidate_index,
                    candidate,
                    center_resampled_xyz,
                    False,
                    "empty_xy_window",
                    half_depth_vox,
                ),
            )

        local_prob_xyz = np.zeros((x_end - x_start, y_end - y_start, z_end - z_start), dtype=np.float32)
        local_lung_xyz = prepared.resampled_lung_mask_xyz[x_start:x_end, y_start:y_end, z_start:z_end]
        slice_outputs: list[SegmentorSliceDebug] = []

        for z_index in range(z_start, z_end):
            slice_result = reference_result if z_index == reference_z else self._segment_slice(
                prepared.resampled_volume_xyz[:, :, z_index].T,
                center_y=float(center_resampled_xyz[1]),
                center_x=float(center_resampled_xyz[0]),
                z_index=z_index,
            )
            self._merge_slice_probability(local_prob_xyz, slice_result, x_start, y_start, z_index - z_start)
            if self.config.capture_segmentor_debug:
                slice_outputs.append(
                    SegmentorSliceDebug(
                        z_index_resampled=int(z_index),
                        input_patch_yx=slice_result.input_patch,
                        probability_patch_yx=slice_result.probability_patch,
                        mapping=dict(slice_result.mapping),
                    )
                )

        local_bbox: BBoxXYZ = ((x_start, x_end), (y_start, y_end), (z_start, z_end))
        center_local_xyz = np.array(
            [
                float(center_resampled_xyz[0]) - x_start,
                float(center_resampled_xyz[1]) - y_start,
                float(center_resampled_xyz[2]) - z_start,
            ],
            dtype=np.float32,
        )
        filtered_prob_xyz, filtered_stats, filter_debug = self.probability_filter.filter(
            local_prob_xyz=local_prob_xyz,
            local_lung_xyz=local_lung_xyz,
            center_local_xyz=center_local_xyz,
        )

        if filtered_prob_xyz is None:
            return CandidateMaskResult(
                accepted=False,
                record=self._build_candidate_record(
                    candidate_index,
                    candidate,
                    center_resampled_xyz,
                    False,
                    str(filtered_stats.get("reason", "filtered_out")),
                    half_depth_vox,
                    local_bbox_xyz=local_bbox,
                    extra_stats=filtered_stats,
                ),
                raw_probability_xyz=local_prob_xyz.astype(np.float32, copy=False),
                filtered_probability_xyz=None,
                filter_debug={key: np.asarray(value) for key, value in filter_debug.items()},
                local_bbox_xyz=local_bbox,
                slice_outputs=slice_outputs,
            )

        filtered_prob_xyz = filtered_prob_xyz.astype(np.float32, copy=False)
        local_binary_xyz = np.asarray(filtered_prob_xyz > 0.0, dtype=bool)
        return CandidateMaskResult(
            accepted=True,
            record=self._build_candidate_record(
                candidate_index,
                candidate,
                center_resampled_xyz,
                True,
                "accepted",
                half_depth_vox,
                local_bbox_xyz=local_bbox,
                extra_stats=filtered_stats,
            ),
            local_probability_xyz=filtered_prob_xyz,
            local_binary_xyz=local_binary_xyz,
            raw_probability_xyz=local_prob_xyz.astype(np.float32, copy=False),
            filtered_probability_xyz=filtered_prob_xyz,
            filter_debug={key: np.asarray(value) for key, value in filter_debug.items()},
            local_bbox_xyz=local_bbox,
            slice_outputs=slice_outputs,
        )

    @staticmethod
    def _merge_slice_probability(
        local_prob_xyz: np.ndarray,
        slice_result: _SliceSegmentationResult,
        x_start: int,
        y_start: int,
        local_z_index: int,
    ) -> None:
        patch_rows = slice(slice_result.mapping["patch_row_start"], slice_result.mapping["patch_row_end"])
        patch_cols = slice(slice_result.mapping["patch_col_start"], slice_result.mapping["patch_col_end"])
        local_x0 = int(slice_result.mapping["slice_col_start"]) - x_start
        local_x1 = int(slice_result.mapping["slice_col_end"]) - x_start
        local_y0 = int(slice_result.mapping["slice_row_start"]) - y_start
        local_y1 = int(slice_result.mapping["slice_row_end"]) - y_start
        local_prob_xyz[local_x0:local_x1, local_y0:local_y1, local_z_index] = np.maximum(
            local_prob_xyz[local_x0:local_x1, local_y0:local_y1, local_z_index],
            slice_result.probability_patch[patch_rows, patch_cols].T,
        )

    def _segment_slice(self, slice_2d: np.ndarray, center_y: float, center_x: float, z_index: int) -> _SliceSegmentationResult:
        slice_result = self.patch_segmenter.segment_slice_with_mapping(
            np.asarray(slice_2d),
            center_y=center_y,
            center_x=center_x,
        )
        probability_patch = np.asarray(getattr(slice_result, "probability_patch"), dtype=np.float32)
        mapping = self._mapping_to_dict(getattr(slice_result, "mapping"))
        input_patch = getattr(slice_result, "input_patch", None)
        input_patch_array = None if input_patch is None else np.asarray(input_patch, dtype=np.float32)
        return _SliceSegmentationResult(
            z_index=int(z_index),
            probability_patch=probability_patch,
            mapping=mapping,
            input_patch=input_patch_array,
        )

    @staticmethod
    def _mapping_to_dict(mapping: Any) -> dict[str, Any]:
        fields = (
            "slice_row_start",
            "slice_row_end",
            "slice_col_start",
            "slice_col_end",
            "patch_row_start",
            "patch_row_end",
            "patch_col_start",
            "patch_col_end",
            "target_center_y_in_roi",
            "target_center_x_in_roi",
        )
        return {
            field_name: (
                float(getattr(mapping, field_name))
                if field_name.startswith("target_center_")
                else int(getattr(mapping, field_name))
            )
            for field_name in fields
            if hasattr(mapping, field_name)
        }

    def _map_center_to_resampled(self, center_xyz: np.ndarray, spacing_original_xyz: np.ndarray) -> np.ndarray:
        target_spacing = np.asarray(self.config.target_spacing_xyz, dtype=np.float32)
        return center_xyz * (np.asarray(spacing_original_xyz, dtype=np.float32) / target_spacing)

    def _build_structured_candidate(self, candidate_result: CandidateMaskResult) -> SegmentorCandidateOutput:
        return SegmentorCandidateOutput(
            candidate_index=int(candidate_result.record["candidate_index"]),
            accepted=bool(candidate_result.accepted),
            reason=str(candidate_result.record["reason"]),
            record=dict(candidate_result.record),
            raw_probability_xyz=(
                np.asarray(candidate_result.raw_probability_xyz, dtype=np.float32)
                if candidate_result.raw_probability_xyz is not None
                else None
            ),
            filtered_probability_xyz=(
                np.asarray(candidate_result.filtered_probability_xyz, dtype=np.float32)
                if candidate_result.filtered_probability_xyz is not None
                else None
            ),
            filtered_binary_xyz=(
                np.asarray(candidate_result.local_binary_xyz, dtype=np.uint8)
                if candidate_result.local_binary_xyz is not None
                else None
            ),
            filter_debug={key: np.asarray(value) for key, value in dict(candidate_result.filter_debug).items()},
            local_bbox_xyz=candidate_result.local_bbox_xyz,
            slice_outputs=list(candidate_result.slice_outputs),
        )

    def _build_debug_volume(self, candidate_result: CandidateMaskResult) -> dict[str, Any]:
        local_bbox = candidate_result.local_bbox_xyz
        if local_bbox is None:
            raise ValueError("local_bbox_xyz is required to build candidate debug volume")
        return {
            "candidate_index": int(candidate_result.record["candidate_index"]),
            "accepted": bool(candidate_result.record["accepted"]),
            "reason": str(candidate_result.record["reason"]),
            "center_xyz": list(candidate_result.record["center_xyz"]),
            "center_xyz_resampled": list(candidate_result.record["center_xyz_resampled"]),
            "local_bbox_resampled_xyz": [
                [int(local_bbox[0][0]), int(local_bbox[0][1])],
                [int(local_bbox[1][0]), int(local_bbox[1][1])],
                [int(local_bbox[2][0]), int(local_bbox[2][1])],
            ],
            "raw_probability_xyz": np.asarray(candidate_result.raw_probability_xyz, dtype=np.float32),
            "filtered_probability_xyz": (
                np.asarray(candidate_result.filtered_probability_xyz, dtype=np.float32)
                if candidate_result.filtered_probability_xyz is not None
                else None
            ),
            "filtered_binary_xyz": (
                np.asarray(candidate_result.local_binary_xyz, dtype=np.uint8)
                if candidate_result.local_binary_xyz is not None
                else None
            ),
            "filter_debug": {key: np.asarray(value) for key, value in dict(candidate_result.filter_debug).items()},
            "segmentor_slices": [
                {
                    "z_index_resampled": int(slice_output.z_index_resampled),
                    "input_patch_yx": (
                        np.asarray(slice_output.input_patch_yx, dtype=np.float32)
                        if slice_output.input_patch_yx is not None
                        else None
                    ),
                    "probability_patch_yx": np.asarray(slice_output.probability_patch_yx, dtype=np.float32),
                    "mapping": dict(slice_output.mapping),
                }
                for slice_output in candidate_result.slice_outputs
            ],
        }

    def _build_candidate_record(
        self,
        candidate_index: int,
        candidate: dict[str, Any],
        center_resampled_xyz: np.ndarray,
        accepted: bool,
        reason: str,
        half_depth_vox: int,
        local_bbox_xyz: BBoxXYZ | None = None,
        extra_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "candidate_index": int(candidate_index),
            "accepted": bool(accepted),
            "reason": str(reason),
            "score_logit": float(candidate.get("score_logit", 0.0)),
            "score_probability": float(candidate.get("score_probability", 0.0)),
            "center_xyz": [float(value) for value in candidate.get("center_xyz", (0.0, 0.0, 0.0))],
            "center_xyz_rounded": [int(round(float(value))) for value in candidate.get("center_xyz", (0.0, 0.0, 0.0))],
            "center_xyz_resampled": [float(value) for value in center_resampled_xyz],
            "center_xyz_resampled_rounded": [int(round(float(value))) for value in center_resampled_xyz],
            "diameter_mm": float(candidate.get("diameter_mm", 0.0)),
            "half_depth_vox": int(half_depth_vox),
        }
        if local_bbox_xyz is not None:
            record["local_bbox_resampled_xyz"] = [
                [int(local_bbox_xyz[0][0]), int(local_bbox_xyz[0][1])],
                [int(local_bbox_xyz[1][0]), int(local_bbox_xyz[1][1])],
                [int(local_bbox_xyz[2][0]), int(local_bbox_xyz[2][1])],
            ]
        if extra_stats:
            record["local_stats"] = extra_stats
        return record
