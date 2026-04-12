"""Patch-based nodule mask pipeline organized by pipeline stage."""

from .base_stages import DetectorStage, LungMaskStage, ResampledVolumeStage
from .candidate_filter import CandidateProbabilityFilter
from .candidate_segmentation import CandidateSegmentationStage
from .models import (
    CandidateMaskResult,
    CandidateSegmentationStageOutput,
    DetectorStageOutput,
    NoduleMaskPipelineConfig,
    NoduleMaskPipelineResult,
    PreparedPipelineInputs,
    SegmentorCandidateOutput,
    SegmentorSliceDebug,
)
from .pipeline import NoduleMaskPipeline
from .postprocess import MaskPostProcessor
from .volume_ops import match_volume_shape, resample_volume_xyz

__all__ = [
    "CandidateProbabilityFilter",
    "CandidateMaskResult",
    "CandidateSegmentationStage",
    "CandidateSegmentationStageOutput",
    "DetectorStage",
    "DetectorStageOutput",
    "LungMaskStage",
    "MaskPostProcessor",
    "NoduleMaskPipeline",
    "NoduleMaskPipelineConfig",
    "NoduleMaskPipelineResult",
    "PreparedPipelineInputs",
    "ResampledVolumeStage",
    "SegmentorCandidateOutput",
    "SegmentorSliceDebug",
    "match_volume_shape",
    "resample_volume_xyz",
]
