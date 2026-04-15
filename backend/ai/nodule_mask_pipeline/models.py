from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


BBoxXYZ = tuple[tuple[int, int], tuple[int, int], tuple[int, int]]


@dataclass(frozen=True)
class NoduleMaskPipelineConfig:
    target_spacing_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0)
    det_score_threshold: float = -3.0
    det_nms_threshold: float = 0.1
    candidate_top_k: int = 5
    min_component_volume_mm3: float = 10.0
    foreground_threshold: float = 0.45
    local_filter_mode: str = "binary_slice"
    local_foreground_threshold: float = 0.30
    local_support_threshold: float = 0.15
    local_lung_mask_dilation_iters: int = 1
    local_max_gap_slices: int = 2
    local_slice_closing_iters: int = 1
    local_slice_min_area_voxels: int = 9
    local_keep_center_only_per_slice: bool = True
    local_restore_thin_slice_ratio: float = 0.45
    local_center_override_radius_vox: float = 10.0
    local_center_override_threshold: float = 0.30
    postprocess_support_threshold: float = 0.20
    postprocess_lung_mask_dilation_iters: int = 1
    center_fallback_radius_vox: float = 6.0
    modal_device: str = "cuda"
    capture_detector_debug: bool = False
    capture_segmentor_debug: bool = False


@dataclass
class PreparedPipelineInputs:
    volume_xyz: np.ndarray
    lung_mask_xyz: np.ndarray
    spacing_xyz_mm: np.ndarray
    resampled_volume_xyz: np.ndarray
    resampled_lung_mask_xyz: np.ndarray


@dataclass
class DetectorStageOutput:
    candidates: list[dict[str, Any]]
    debug: dict[str, Any]
    preprocess: dict[str, Any] = field(default_factory=dict)
    raw_candidates_zyx: np.ndarray | None = None
    post_nms_candidates_zyx: np.ndarray | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class SegmentorSliceDebug:
    z_index_resampled: int
    input_patch_yx: np.ndarray | None
    probability_patch_yx: np.ndarray
    mapping: dict[str, Any]


@dataclass
class CandidateMaskResult:
    accepted: bool
    record: dict[str, Any]
    local_probability_xyz: np.ndarray | None = None
    local_binary_xyz: np.ndarray | None = None
    raw_probability_xyz: np.ndarray | None = None
    filtered_probability_xyz: np.ndarray | None = None
    filter_debug: dict[str, np.ndarray] = field(default_factory=dict)
    local_bbox_xyz: BBoxXYZ | None = None
    slice_outputs: list[SegmentorSliceDebug] = field(default_factory=list)


@dataclass
class SegmentorCandidateOutput:
    candidate_index: int
    accepted: bool
    reason: str
    record: dict[str, Any]
    raw_probability_xyz: np.ndarray | None = None
    filtered_probability_xyz: np.ndarray | None = None
    filtered_binary_xyz: np.ndarray | None = None
    filter_debug: dict[str, np.ndarray] = field(default_factory=dict)
    local_bbox_xyz: BBoxXYZ | None = None
    slice_outputs: list[SegmentorSliceDebug] = field(default_factory=list)


@dataclass
class CandidateSegmentationStageOutput:
    probability_volume_resampled_xyz: np.ndarray
    binary_volume_resampled_xyz: np.ndarray
    candidate_records: list[dict[str, Any]]
    candidate_debug_volumes: list[dict[str, Any]]
    candidates: list[SegmentorCandidateOutput]
    accepted_candidate_count: int


@dataclass
class NoduleMaskPipelineResult:
    final_mask_xyz: np.ndarray
    final_mask_resampled_xyz: np.ndarray
    lung_mask_xyz: np.ndarray
    lung_mask_resampled_xyz: np.ndarray
    probability_volume_resampled_xyz: np.ndarray
    binary_volume_resampled_xyz: np.ndarray
    candidates: list[dict[str, Any]]
    candidate_debug_volumes: list[dict[str, Any]]
    component_stats: list[dict[str, Any]]
    detector_output: DetectorStageOutput | None = None
    segmentor_output: CandidateSegmentationStageOutput | None = None
    debug: dict[str, Any] = field(default_factory=dict)
