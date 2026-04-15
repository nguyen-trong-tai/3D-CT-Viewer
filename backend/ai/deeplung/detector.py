from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch

from .model import DPN3D26, GetPBB, SplitComb, nms_3d
from .preprocessing import (
    DeepLungDetectorConfig,
    DeepLungPreprocessResult,
    DeepLungTileBuilder,
    DeepLungVolumePreprocessor,
)


def _sigmoid(value: float) -> float:
    return float(1.0 / (1.0 + np.exp(-value)))


@dataclass(frozen=True)
class _DetectorThresholds:
    score: float
    nms: float


class DeepLungDetector:
    def __init__(self, model: DPN3D26, config: DeepLungDetectorConfig | None = None, checkpoint_path: str | Path | None = None) -> None:
        self.config = config or DeepLungDetectorConfig()
        self.device = torch.device(self.config.device)
        self.model = model.to(self.device)
        self.model.eval()
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else None
        self.split_comber = SplitComb(self.config.tile_side_len, self.config.max_stride, self.config.stride, self.config.tile_margin, self.config.pad_value)
        self.get_pbb = GetPBB(self.config.stride, self.config.anchors)
        self.preprocessor = DeepLungVolumePreprocessor(self.config)
        self.tile_builder = DeepLungTileBuilder(self.config, self.split_comber)

    @classmethod
    def from_checkpoint(cls, checkpoint_path: str | Path, config: DeepLungDetectorConfig | None = None) -> "DeepLungDetector":
        resolved_config = config or DeepLungDetectorConfig()
        model = DPN3D26(resolved_config.anchors)
        checkpoint = cls._load_checkpoint_dict(checkpoint_path)
        state_dict = checkpoint["state_dict"] if "state_dict" in checkpoint else checkpoint
        model.load_state_dict(state_dict, strict=True)
        return cls(model=model, config=resolved_config, checkpoint_path=checkpoint_path)

    @staticmethod
    def _load_checkpoint_dict(checkpoint_path: str | Path) -> dict[str, Any]:
        checkpoint_path = Path(checkpoint_path)
        with torch.serialization.safe_globals([argparse.Namespace]):
            checkpoint = torch.load(checkpoint_path, map_location="cpu")
        if not isinstance(checkpoint, dict):
            raise TypeError(f"Expected checkpoint dict, got {type(checkpoint).__name__}")
        return checkpoint

    @staticmethod
    def _spacing_xyz_to_zyx(spacing_xyz: Iterable[float]) -> np.ndarray:
        return DeepLungVolumePreprocessor.spacing_xyz_to_zyx(spacing_xyz)

    def prepare_volume(self, volume_hu_xyz: np.ndarray, spacing_xyz_mm: Iterable[float], lung_mask_xyz: np.ndarray) -> DeepLungPreprocessResult:
        return self.preprocessor.prepare(volume_hu_xyz, spacing_xyz_mm, lung_mask_xyz)

    def _build_test_tiles(self, clean_volume_zyx: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[int]]:
        return self.tile_builder.build(clean_volume_zyx)

    def _forward_tiles(self, image_tiles: np.ndarray, coord_tiles: np.ndarray) -> np.ndarray:
        outputs: list[np.ndarray] = []
        batch_size = max(1, int(self.config.batch_size))
        with torch.inference_mode():
            for start in range(0, len(image_tiles), batch_size):
                end = min(start + batch_size, len(image_tiles))
                output = self.model(torch.from_numpy(image_tiles[start:end]).to(self.device), torch.from_numpy(coord_tiles[start:end]).to(self.device))
                outputs.append(output.detach().cpu().numpy())
        return np.concatenate(outputs, axis=0) if outputs else np.zeros((0,), dtype=np.float32)

    def detect(
        self,
        volume_hu_xyz: np.ndarray,
        spacing_xyz_mm: Iterable[float],
        lung_mask_xyz: np.ndarray,
        score_threshold: float | None = None,
        nms_threshold: float | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        if np.asarray(lung_mask_xyz).sum() == 0:
            return {"candidates": [], "debug": {"reason": "empty_lung_mask"}}
        thresholds = self._resolve_thresholds(score_threshold, nms_threshold)
        prep = self.prepare_volume(volume_hu_xyz, spacing_xyz_mm, lung_mask_xyz)
        image_tiles, coord_tiles, nzhw = self._build_test_tiles(prep.clean_volume_zyx)
        raw_output = self._forward_tiles(image_tiles, coord_tiles)
        combined_output = self.split_comber.combine(raw_output, nzhw=nzhw)
        raw_candidates = self.get_pbb(combined_output, threshold=thresholds.score)
        post_nms_candidates = nms_3d(raw_candidates, thresholds.nms) if len(raw_candidates) > 0 else raw_candidates
        selected_candidates = self._select_top_candidates(post_nms_candidates, top_k)
        candidates = [self._build_candidate_payload(candidate, prep, volume_hu_xyz.shape) for candidate in selected_candidates]
        return {
            "candidates": candidates,
            "preprocess": self._build_preprocess_payload(prep),
            "raw_candidates_zyx": np.asarray(raw_candidates, dtype=np.float32),
            "post_nms_candidates_zyx": np.asarray(post_nms_candidates, dtype=np.float32),
            "selected_candidates_zyx": np.asarray(selected_candidates, dtype=np.float32),
            "debug": self._build_debug_payload(prep, volume_hu_xyz, spacing_xyz_mm, image_tiles, coord_tiles, raw_output, combined_output, raw_candidates, post_nms_candidates, len(candidates), thresholds, top_k),
        }

    def _resolve_thresholds(self, score_threshold: float | None, nms_threshold: float | None) -> _DetectorThresholds:
        return _DetectorThresholds(
            score=self.config.score_threshold if score_threshold is None else float(score_threshold),
            nms=self.config.nms_threshold if nms_threshold is None else float(nms_threshold),
        )

    @staticmethod
    def _select_top_candidates(candidates: np.ndarray, top_k: int | None) -> np.ndarray:
        if top_k is None or len(candidates) <= top_k:
            return candidates
        return candidates[np.argsort(-candidates[:, 0])[:top_k]]

    def _build_candidate_payload(self, candidate: np.ndarray, prep: DeepLungPreprocessResult, input_shape_xyz: tuple[int, ...]) -> dict[str, Any]:
        resolution_zyx = np.asarray(self.config.resample_spacing_zyx_mm, dtype=np.float32)
        resampled_center_zyx = candidate[1:4] + prep.extendbox_zyx[:, 0]
        original_center_zyx = resampled_center_zyx * (resolution_zyx / prep.spacing_zyx_mm)
        original_center_xyz = np.clip(original_center_zyx[[2, 1, 0]], 0.0, np.asarray(input_shape_xyz, dtype=np.float32) - 1.0)
        return {
            "score_logit": float(candidate[0]),
            "score_probability": _sigmoid(float(candidate[0])),
            "center_xyz": [float(value) for value in original_center_xyz],
            "center_xyz_rounded": [int(round(float(value))) for value in original_center_xyz],
            "center_zyx_resampled": [float(value) for value in resampled_center_zyx],
            "diameter_mm": float(candidate[4] * resolution_zyx[1]),
        }

    @staticmethod
    def _build_preprocess_payload(prep: DeepLungPreprocessResult) -> dict[str, Any]:
        return {
            "clean_volume_zyx": prep.clean_volume_zyx.astype(np.uint8, copy=False),
            "spacing_zyx_mm": prep.spacing_zyx_mm.astype(np.float32, copy=False),
            "extendbox_zyx": prep.extendbox_zyx.astype(np.int32, copy=False),
            "original_shape_zyx": [int(value) for value in prep.original_shape_zyx],
            "resampled_shape_zyx": [int(value) for value in prep.resampled_shape_zyx],
        }

    def _build_debug_payload(self, prep: DeepLungPreprocessResult, volume_hu_xyz: np.ndarray, spacing_xyz_mm: Iterable[float], image_tiles: np.ndarray, coord_tiles: np.ndarray, raw_output: np.ndarray, combined_output: np.ndarray, raw_candidates: np.ndarray, post_nms_candidates: np.ndarray, selected_count: int, thresholds: _DetectorThresholds, top_k: int | None) -> dict[str, Any]:
        return {
            "input_shape_xyz": [int(value) for value in volume_hu_xyz.shape],
            "input_spacing_xyz_mm": [float(value) for value in spacing_xyz_mm],
            "preprocessed_shape_zyx": [int(value) for value in prep.clean_volume_zyx.shape[1:]],
            "resampled_shape_zyx": [int(value) for value in prep.resampled_shape_zyx],
            "extendbox_zyx": prep.extendbox_zyx.astype(int).tolist(),
            "tile_count": int(len(image_tiles)),
            "tile_shape_zyx": [int(value) for value in image_tiles.shape[2:]],
            "coord_tile_shape_zyx": [int(value) for value in coord_tiles.shape[2:]],
            "raw_output_shape": [int(value) for value in raw_output.shape],
            "combined_output_shape": [int(value) for value in combined_output.shape],
            "raw_candidate_count": int(len(raw_candidates)),
            "candidate_count_after_nms": int(len(post_nms_candidates)),
            "selected_candidate_count": int(selected_count),
            "score_threshold": float(thresholds.score),
            "nms_threshold": float(thresholds.nms),
            "top_k": int(top_k) if top_k is not None else None,
            "device": str(self.device),
            "checkpoint_path": str(self.checkpoint_path) if self.checkpoint_path else None,
        }
