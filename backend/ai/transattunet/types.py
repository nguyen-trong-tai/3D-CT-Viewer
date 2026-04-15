from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TransAttUnetPatchSegmenterConfig:
    image_size: int = 128
    roi_size: int = 128
    window_center: float = -600.0
    window_width: float = 1500.0
    foreground_threshold: float = 0.45
    device: str = "cpu"


@dataclass(frozen=True)
class PatchExtractionPlan:
    patch_size: int
    source_row_start: int
    source_row_end: int
    source_col_start: int
    source_col_end: int
    target_row_start: int
    target_row_end: int
    target_col_start: int
    target_col_end: int
    center_row_in_patch: float
    center_col_in_patch: float


@dataclass(frozen=True)
class SlicePatchMapping:
    roi_plan: PatchExtractionPlan
    model_plan: PatchExtractionPlan
    slice_row_start: int
    slice_row_end: int
    slice_col_start: int
    slice_col_end: int
    patch_row_start: int
    patch_row_end: int
    patch_col_start: int
    patch_col_end: int
    target_center_y_in_roi: float
    target_center_x_in_roi: float


@dataclass(frozen=True)
class PreparedSlicePatch:
    input_patch: np.ndarray
    mapping: SlicePatchMapping


@dataclass(frozen=True)
class SegmentedSlicePatch:
    probability_patch: np.ndarray
    mapping: SlicePatchMapping
    input_patch: np.ndarray | None = None
    logits_patch: np.ndarray | None = None
