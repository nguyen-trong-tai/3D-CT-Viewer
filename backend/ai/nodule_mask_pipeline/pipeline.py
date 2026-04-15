from __future__ import annotations

import time
from typing import Any, Iterable

import numpy as np

from .models import (
    CandidateSegmentationStageOutput,
    DetectorStageOutput,
    NoduleMaskPipelineConfig,
    NoduleMaskPipelineResult,
)
from .base_stages import (
    DetectorStage,
    LungMaskStage,
    ResampledVolumeStage,
)
from .candidate_segmentation import CandidateSegmentationStage
from .postprocess import MaskPostProcessor


class NoduleMaskPipeline:
    def __init__(
        self,
        detector: Any,
        patch_segmenter: Any,
        lung_segmenter: Any | None = None,
        config: NoduleMaskPipelineConfig | None = None,
        lung_mask_stage: LungMaskStage | None = None,
        resampled_volume_stage: ResampledVolumeStage | None = None,
        detector_stage: DetectorStage | None = None,
        candidate_segmentation_stage: CandidateSegmentationStage | None = None,
        post_processor: MaskPostProcessor | None = None,
    ) -> None:
        self.detector = detector
        self.patch_segmenter = patch_segmenter
        self.lung_segmenter = lung_segmenter
        self.config = config or NoduleMaskPipelineConfig()
        self.lung_mask_stage = lung_mask_stage or LungMaskStage(lung_segmenter=lung_segmenter)
        self.resampled_volume_stage = resampled_volume_stage or ResampledVolumeStage(self.config)
        self.detector_stage = detector_stage or DetectorStage(detector=detector, config=self.config)
        self.candidate_segmentation_stage = candidate_segmentation_stage or CandidateSegmentationStage(
            patch_segmenter=patch_segmenter,
            config=self.config,
        )
        self.post_processor = post_processor or MaskPostProcessor(self.config)

    def run(
        self,
        volume_hu_xyz: np.ndarray,
        spacing_xyz_mm: Iterable[float],
        lung_mask_xyz: np.ndarray | None = None,
    ) -> NoduleMaskPipelineResult:
        volume_xyz = np.asarray(volume_hu_xyz)
        spacing_xyz = np.asarray(tuple(float(value) for value in spacing_xyz_mm), dtype=np.float32)
        if volume_xyz.ndim != 3:
            raise ValueError(f"Expected a 3D CT volume, got shape {volume_xyz.shape}")
        if spacing_xyz.shape != (3,):
            raise ValueError(f"Expected spacing_xyz_mm with 3 elements, got {spacing_xyz}")

        resolved_lung_mask_xyz = self.lung_mask_stage.resolve(volume_xyz, lung_mask_xyz)
        prepared = self.resampled_volume_stage.prepare(
            volume_xyz=volume_xyz,
            spacing_xyz=spacing_xyz,
            lung_mask_xyz=resolved_lung_mask_xyz,
        )

        if not resolved_lung_mask_xyz.any() or not prepared.resampled_lung_mask_xyz.any():
            print("Skipping nodule segmentation because lung mask is empty after preparation.", flush=True)
            return self._build_empty_result(prepared)

        print("Running detector stage...", flush=True)
        detector_start_time = time.time()
        detector_output = self.detector_stage.run(prepared)
        detector_end_time = time.time()
        print(f"Detector stage completed in {detector_end_time - detector_start_time:.2f} seconds.", flush=True)

        segmentor_start_time = time.time()
        segmentor_output = self.candidate_segmentation_stage.run(prepared, detector_output)
        print(f"Segmentor accepted {segmentor_output.accepted_candidate_count} candidates.", flush=True)
        final_mask_resampled_xyz = self.post_processor.post_process_probability_volume(
            segmentor_output.probability_volume_resampled_xyz,
            prepared.resampled_lung_mask_xyz,
            binary_xyz=segmentor_output.binary_volume_resampled_xyz,
            candidate_records=segmentor_output.candidate_records,
        )
        final_mask_xyz = self.post_processor.map_mask_back_to_original(
            final_mask_resampled_xyz,
            source_spacing_xyz=self.config.target_spacing_xyz,
            target_spacing_xyz=prepared.spacing_xyz_mm,
            target_shape_xyz=tuple(int(value) for value in volume_xyz.shape),
        )
        component_stats = self.post_processor.compute_component_stats(final_mask_xyz, prepared.spacing_xyz_mm)
        segmentor_end_time = time.time()
        print(f"Segmentor stage completed in {segmentor_end_time - segmentor_start_time:.2f} seconds.", flush=True)

        return NoduleMaskPipelineResult(
            final_mask_xyz=final_mask_xyz,
            final_mask_resampled_xyz=final_mask_resampled_xyz,
            lung_mask_xyz=prepared.lung_mask_xyz,
            lung_mask_resampled_xyz=prepared.resampled_lung_mask_xyz,
            probability_volume_resampled_xyz=segmentor_output.probability_volume_resampled_xyz,
            binary_volume_resampled_xyz=segmentor_output.binary_volume_resampled_xyz,
            candidates=segmentor_output.candidate_records,
            candidate_debug_volumes=segmentor_output.candidate_debug_volumes,
            component_stats=component_stats,
            detector_output=detector_output,
            segmentor_output=segmentor_output,
            debug=self._build_debug_summary(
                volume_xyz=volume_xyz,
                spacing_xyz=spacing_xyz,
                prepared=prepared,
                detector_output=detector_output,
                segmentor_output=segmentor_output,
            ),
        )

    def _build_empty_result(self, prepared: Any) -> NoduleMaskPipelineResult:
        empty_original = np.zeros_like(prepared.volume_xyz, dtype=bool)
        empty_resampled = np.zeros_like(prepared.resampled_volume_xyz, dtype=bool)
        return NoduleMaskPipelineResult(
            final_mask_xyz=empty_original,
            final_mask_resampled_xyz=empty_resampled,
            lung_mask_xyz=prepared.lung_mask_xyz,
            lung_mask_resampled_xyz=prepared.resampled_lung_mask_xyz,
            probability_volume_resampled_xyz=np.zeros_like(prepared.resampled_volume_xyz, dtype=np.float32),
            binary_volume_resampled_xyz=np.zeros_like(prepared.resampled_volume_xyz, dtype=bool),
            candidates=[],
            candidate_debug_volumes=[],
            component_stats=[],
            detector_output=None,
            segmentor_output=None,
            debug={
                "reason": "empty_lung_mask",
                "input_shape_xyz": [int(value) for value in prepared.volume_xyz.shape],
                "resampled_shape_xyz": [int(value) for value in prepared.resampled_volume_xyz.shape],
                "input_spacing_xyz_mm": [float(value) for value in prepared.spacing_xyz_mm],
                "target_spacing_xyz_mm": [float(value) for value in self.config.target_spacing_xyz],
            },
        )

    def _build_debug_summary(
        self,
        volume_xyz: np.ndarray,
        spacing_xyz: np.ndarray,
        prepared: Any,
        detector_output: DetectorStageOutput,
        segmentor_output: CandidateSegmentationStageOutput,
    ) -> dict[str, Any]:
        return {
            "input_shape_xyz": [int(value) for value in volume_xyz.shape],
            "resampled_shape_xyz": [int(value) for value in prepared.resampled_volume_xyz.shape],
            "input_spacing_xyz_mm": [float(value) for value in spacing_xyz],
            "target_spacing_xyz_mm": [float(value) for value in self.config.target_spacing_xyz],
            "candidate_count": int(len(segmentor_output.candidate_records)),
            "accepted_candidate_count": int(segmentor_output.accepted_candidate_count),
            "foreground_threshold": float(self.config.foreground_threshold),
            "min_component_volume_mm3": float(self.config.min_component_volume_mm3),
            "detector_debug": dict(detector_output.debug),
            "patch_segmenter": self._describe_patch_segmenter(),
        }

    def _describe_patch_segmenter(self) -> dict[str, Any]:
        describe = getattr(self.patch_segmenter, "describe", None)
        if callable(describe):
            return dict(describe())
        return {"config": str(getattr(self.patch_segmenter, "config", None))}
