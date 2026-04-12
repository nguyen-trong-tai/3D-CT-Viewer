from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from .model import TransAttUnet
from .types import (
    PatchExtractionPlan,
    PreparedSlicePatch,
    SegmentedSlicePatch,
    SlicePatchMapping,
    TransAttUnetPatchSegmenterConfig,
)


class TransAttUnetPatchSegmenter:
    def __init__(
        self,
        model: TransAttUnet,
        config: TransAttUnetPatchSegmenterConfig | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        self.config = config or TransAttUnetPatchSegmenterConfig()
        self.device = torch.device(self.config.device)
        self.model = model.to(self.device)
        self.model.eval()
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else None

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint_path: str | Path,
        config: TransAttUnetPatchSegmenterConfig | None = None,
    ) -> "TransAttUnetPatchSegmenter":
        resolved_config = config or TransAttUnetPatchSegmenterConfig()
        model = TransAttUnet(n_channels=1, n_classes=2)
        checkpoint = torch.load(checkpoint_path, map_location="cpu")
        state_dict = checkpoint.get("model_state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
        if not isinstance(state_dict, dict):
            raise TypeError(f"Unsupported checkpoint payload: {type(state_dict).__name__}")
        model.load_state_dict(state_dict, strict=True)
        return cls(model=model, config=resolved_config, checkpoint_path=checkpoint_path)

    @staticmethod
    def build_patch_plan(shape: tuple[int, int], center_row: float, center_col: float, patch_size: int) -> PatchExtractionPlan:
        height, width = [int(value) for value in shape]
        half = int(patch_size) // 2
        center_row_i = int(round(float(center_row)))
        center_col_i = int(round(float(center_col)))
        src_row_start = max(center_row_i - half, 0)
        src_col_start = max(center_col_i - half, 0)
        src_row_end = min(src_row_start + patch_size, height)
        src_col_end = min(src_col_start + patch_size, width)
        if src_row_end - src_row_start < patch_size:
            src_row_start = max(src_row_end - patch_size, 0)
        if src_col_end - src_col_start < patch_size:
            src_col_start = max(src_col_end - patch_size, 0)
        crop_height = src_row_end - src_row_start
        crop_width = src_col_end - src_col_start
        dst_row_start = (patch_size - crop_height) // 2
        dst_col_start = (patch_size - crop_width) // 2
        return PatchExtractionPlan(
            patch_size=int(patch_size),
            source_row_start=int(src_row_start),
            source_row_end=int(src_row_end),
            source_col_start=int(src_col_start),
            source_col_end=int(src_col_end),
            target_row_start=int(dst_row_start),
            target_row_end=int(dst_row_start + crop_height),
            target_col_start=int(dst_col_start),
            target_col_end=int(dst_col_start + crop_width),
            center_row_in_patch=float(dst_row_start + (center_row_i - src_row_start)),
            center_col_in_patch=float(dst_col_start + (center_col_i - src_col_start)),
        )

    @staticmethod
    def extract_with_plan(array: np.ndarray, plan: PatchExtractionPlan, pad_value: float = 0.0) -> np.ndarray:
        patch = np.full((plan.patch_size, plan.patch_size), pad_value, dtype=array.dtype)
        patch[plan.target_row_start:plan.target_row_end, plan.target_col_start:plan.target_col_end] = array[
            plan.source_row_start:plan.source_row_end,
            plan.source_col_start:plan.source_col_end,
        ]
        return patch

    @staticmethod
    def direct_slice_mapping(patch_plan: PatchExtractionPlan) -> SlicePatchMapping:
        return SlicePatchMapping(
            roi_plan=patch_plan,
            model_plan=patch_plan,
            slice_row_start=int(patch_plan.source_row_start),
            slice_row_end=int(patch_plan.source_row_end),
            slice_col_start=int(patch_plan.source_col_start),
            slice_col_end=int(patch_plan.source_col_end),
            patch_row_start=int(patch_plan.target_row_start),
            patch_row_end=int(patch_plan.target_row_end),
            patch_col_start=int(patch_plan.target_col_start),
            patch_col_end=int(patch_plan.target_col_end),
            target_center_y_in_roi=float(patch_plan.center_row_in_patch),
            target_center_x_in_roi=float(patch_plan.center_col_in_patch),
        )

    @staticmethod
    def compose_slice_mapping(roi_plan: PatchExtractionPlan, model_plan: PatchExtractionPlan) -> SlicePatchMapping:
        overlap_row_start = max(model_plan.source_row_start, roi_plan.target_row_start)
        overlap_row_end = min(model_plan.source_row_end, roi_plan.target_row_end)
        overlap_col_start = max(model_plan.source_col_start, roi_plan.target_col_start)
        overlap_col_end = min(model_plan.source_col_end, roi_plan.target_col_end)
        if overlap_row_start >= overlap_row_end or overlap_col_start >= overlap_col_end:
            raise ValueError("ROI/model patch composition does not overlap any real slice pixels")
        patch_row_start = model_plan.target_row_start + (overlap_row_start - model_plan.source_row_start)
        patch_col_start = model_plan.target_col_start + (overlap_col_start - model_plan.source_col_start)
        slice_row_start = roi_plan.source_row_start + (overlap_row_start - roi_plan.target_row_start)
        slice_col_start = roi_plan.source_col_start + (overlap_col_start - roi_plan.target_col_start)
        return SlicePatchMapping(
            roi_plan=roi_plan,
            model_plan=model_plan,
            slice_row_start=int(slice_row_start),
            slice_row_end=int(slice_row_start + (overlap_row_end - overlap_row_start)),
            slice_col_start=int(slice_col_start),
            slice_col_end=int(slice_col_start + (overlap_col_end - overlap_col_start)),
            patch_row_start=int(patch_row_start),
            patch_row_end=int(patch_row_start + (overlap_row_end - overlap_row_start)),
            patch_col_start=int(patch_col_start),
            patch_col_end=int(patch_col_start + (overlap_col_end - overlap_col_start)),
            target_center_y_in_roi=float(roi_plan.center_row_in_patch),
            target_center_x_in_roi=float(roi_plan.center_col_in_patch),
        )

    def normalize_slice(self, slice_hu: np.ndarray) -> np.ndarray:
        lower = float(self.config.window_center - (self.config.window_width // 2))
        upper = float(self.config.window_center + (self.config.window_width // 2))
        normalized = np.clip(np.asarray(slice_hu, dtype=np.float32), lower, upper)
        normalized = (normalized - lower) / max(upper - lower, 1e-6)
        return normalized.astype(np.float32, copy=False)

    def prepare_slice_patch(self, slice_2d: np.ndarray, center_y: float, center_x: float) -> PreparedSlicePatch:
        normalized_slice = self.normalize_slice(slice_2d)
        model_plan = self.build_patch_plan(normalized_slice.shape, center_y, center_x, self.config.image_size)
        model_patch = self.extract_with_plan(normalized_slice, model_plan, pad_value=0.0).astype(np.float32, copy=False)
        return PreparedSlicePatch(input_patch=model_patch, mapping=self.direct_slice_mapping(model_plan))

    def _predict_prepared_patch(self, input_patch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        patch = np.asarray(input_patch, dtype=np.float32)
        expected_shape = (self.config.image_size, self.config.image_size)
        if patch.shape != expected_shape:
            raise ValueError(f"Expected input patch with shape {expected_shape}, got {patch.shape}")
        tensor = torch.from_numpy(patch).unsqueeze(0).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            logits = self.model(tensor)
            probabilities = torch.softmax(logits, dim=1)[:, 1]
        return (
            probabilities.squeeze(0).detach().cpu().numpy().astype(np.float32, copy=False),
            logits.squeeze(0).detach().cpu().numpy().astype(np.float32, copy=False),
        )

    def segment_prepared_patch(self, input_patch: np.ndarray) -> np.ndarray:
        probability_patch, _ = self._predict_prepared_patch(input_patch)
        return probability_patch

    def segment_slice_patch(self, slice_2d: np.ndarray, center_y: float, center_x: float) -> np.ndarray:
        prepared = self.prepare_slice_patch(slice_2d, center_y=center_y, center_x=center_x)
        return self.segment_prepared_patch(prepared.input_patch)

    def segment_slice_with_mapping(self, slice_2d: np.ndarray, center_y: float, center_x: float) -> SegmentedSlicePatch:
        prepared = self.prepare_slice_patch(slice_2d, center_y=center_y, center_x=center_x)
        probability_patch, logits_patch = self._predict_prepared_patch(prepared.input_patch)
        return SegmentedSlicePatch(
            probability_patch=probability_patch,
            mapping=prepared.mapping,
            input_patch=prepared.input_patch,
            logits_patch=logits_patch,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "device": str(self.device),
            "checkpoint_path": str(self.checkpoint_path) if self.checkpoint_path else None,
            "image_size": int(self.config.image_size),
            "roi_size": int(self.config.roi_size),
            "foreground_threshold": float(self.config.foreground_threshold),
        }
