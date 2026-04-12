from __future__ import annotations

from typing import Any

import numpy as np

from .contracts import normalize_detector_output
from .models import (
    DetectorStageOutput,
    NoduleMaskPipelineConfig,
    PreparedPipelineInputs,
)
from .volume_ops import resample_volume_xyz


class LungMaskStage:
    def __init__(self, lung_segmenter: Any | None = None) -> None:
        self.lung_segmenter = lung_segmenter

    def resolve(self, volume_xyz: np.ndarray, lung_mask_xyz: np.ndarray | None) -> np.ndarray:
        if lung_mask_xyz is not None:
            mask = np.asarray(lung_mask_xyz, dtype=bool)
            if mask.shape != volume_xyz.shape:
                raise ValueError(f"lung_mask_xyz shape {mask.shape} does not match volume shape {volume_xyz.shape}")
            return mask

        if self.lung_segmenter is None:
            raise ValueError("lung_mask_xyz was not provided and no lung_segmenter is configured")

        segmentation = self.lung_segmenter.segment(volume_xyz)
        return np.asarray(segmentation["lung_mask"], dtype=bool)


class ResampledVolumeStage:
    def __init__(self, config: NoduleMaskPipelineConfig) -> None:
        self.config = config

    def prepare(self, volume_xyz: np.ndarray, spacing_xyz: np.ndarray, lung_mask_xyz: np.ndarray) -> PreparedPipelineInputs:
        resampled_volume_xyz = resample_volume_xyz(
            np.asarray(volume_xyz),
            spacing_xyz=spacing_xyz,
            new_spacing_xyz=self.config.target_spacing_xyz,
            order=1,
        ).astype(np.float32, copy=False)
        resampled_lung_mask_xyz = resample_volume_xyz(
            np.asarray(lung_mask_xyz, dtype=np.uint8),
            spacing_xyz=spacing_xyz,
            new_spacing_xyz=self.config.target_spacing_xyz,
            order=0,
        )
        return PreparedPipelineInputs(
            volume_xyz=np.asarray(volume_xyz),
            lung_mask_xyz=np.asarray(lung_mask_xyz, dtype=bool),
            spacing_xyz_mm=np.asarray(spacing_xyz, dtype=np.float32),
            resampled_volume_xyz=resampled_volume_xyz,
            resampled_lung_mask_xyz=np.asarray(resampled_lung_mask_xyz > 0, dtype=bool),
        )


class DetectorStage:
    def __init__(self, detector: Any, config: NoduleMaskPipelineConfig) -> None:
        self.detector = detector
        self.config = config

    def run(self, prepared: PreparedPipelineInputs) -> DetectorStageOutput:
        detector_result = self.detector.detect(
            volume_hu_xyz=prepared.volume_xyz,
            spacing_xyz_mm=tuple(float(value) for value in prepared.spacing_xyz_mm),
            lung_mask_xyz=prepared.lung_mask_xyz,
            score_threshold=self.config.det_score_threshold,
            nms_threshold=self.config.det_nms_threshold,
            top_k=self.config.candidate_top_k,
        )
        normalized = normalize_detector_output(detector_result)
        if self.config.capture_detector_debug:
            return normalized
        return DetectorStageOutput(candidates=normalized.candidates, debug=normalized.debug)
