"""
AI segmentation service that combines lung segmentation with sandbox nodule masks.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict

import numpy as np

from processing import LungSegmenter


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SegmentationLabelSpec:
    label_id: int
    key: str
    display_name: str
    color: str
    visible_by_default: bool
    render_2d: bool
    render_3d: bool


class AISegmentationService:
    """Produces a labeled segmentation mask plus component metadata."""

    LABEL_SPECS = (
        SegmentationLabelSpec(1, "left_lung", "Left Lung", "#60a5fa", True, True, True),
        SegmentationLabelSpec(2, "right_lung", "Right Lung", "#34d399", True, True, True),
        SegmentationLabelSpec(3, "nodule", "Nodule", "#f97316", True, True, True),
    )

    def __init__(
        self,
        lung_segmenter: LungSegmenter | None = None,
        checkpoint_root: Path | None = None,
    ) -> None:
        self.lung_segmenter = lung_segmenter or LungSegmenter(
            hu_threshold=-400,
            min_lung_volume=50_000,
            fill_holes=True,
        )
        self.checkpoint_root = checkpoint_root or (Path(__file__).resolve().parents[1] / "ai" / "checkpoints")
        self._nodule_pipeline: Any | None = None
        self._nodule_pipeline_error: str | None = None

    def segment(self, volume_xyz: np.ndarray, spacing_xyz_mm: tuple[float, float, float]) -> dict[str, Any]:
        lung_result = self.lung_segmenter.segment(volume_xyz)
        left_mask = np.asarray(lung_result.get("left_mask"), dtype=bool)
        right_mask = np.asarray(lung_result.get("right_mask"), dtype=bool)
        lung_mask = np.asarray(lung_result.get("lung_mask"), dtype=bool)

        nodule_mask = np.zeros_like(lung_mask, dtype=bool)
        nodule_debug: Dict[str, Any] = {"mode": "fallback_empty"}
        pipeline = self._get_nodule_pipeline()
        if pipeline is not None:
            try:
                pipeline_result = pipeline.run(
                    volume_hu_xyz=np.asarray(volume_xyz),
                    spacing_xyz_mm=spacing_xyz_mm,
                    lung_mask_xyz=lung_mask,
                )
                nodule_mask = np.asarray(pipeline_result.final_mask_xyz, dtype=bool)
                nodule_debug = {
                    "mode": "sandbox_ai",
                    "candidate_count": int(len(getattr(pipeline_result, "candidates", []) or [])),
                    "component_count": int(len(getattr(pipeline_result, "component_stats", []) or [])),
                    "component_stats": list(getattr(pipeline_result, "component_stats", []) or []),
                    "pipeline_debug": dict(getattr(pipeline_result, "debug", {}) or {}),
                }
            except Exception as exc:
                self._nodule_pipeline_error = str(exc)
                logger.exception("Nodule mask pipeline failed")
                nodule_debug = {"mode": "pipeline_error", "error": str(exc)}
        elif self._nodule_pipeline_error:
            nodule_debug = {"mode": "pipeline_unavailable", "error": self._nodule_pipeline_error}

        labeled_mask = self._build_labeled_mask(left_mask, right_mask, nodule_mask)
        manifest = self._build_manifest(labeled_mask)
        components = self._build_components(left_mask, right_mask, nodule_mask)

        return {
            "lung_mask": (left_mask | right_mask).astype(np.uint8),
            "left_mask": left_mask.astype(np.uint8),
            "right_mask": right_mask.astype(np.uint8),
            "nodule_mask": nodule_mask.astype(np.uint8),
            "labeled_mask": labeled_mask,
            "components": components,
            "manifest": manifest,
            "stats": {
                "left_lung_voxels": int(left_mask.sum()),
                "right_lung_voxels": int(right_mask.sum()),
                "nodule_voxels": int(nodule_mask.sum()),
                "nodule_debug": nodule_debug,
            },
        }

    def _build_components(
        self,
        left_mask: np.ndarray,
        right_mask: np.ndarray,
        nodule_mask: np.ndarray,
    ) -> dict[str, dict[str, Any]]:
        masks = {
            "left_lung": left_mask,
            "right_lung": right_mask,
            "nodule": nodule_mask,
        }
        components: dict[str, dict[str, Any]] = {}
        for spec in self.LABEL_SPECS:
            mask = np.asarray(masks[spec.key], dtype=bool)
            components[spec.key] = {
                "name": spec.display_name,
                "mask": mask,
                "color": spec.color,
                "render_2d": spec.render_2d,
                "render_3d": spec.render_3d,
                "visible_by_default": spec.visible_by_default,
                "voxel_count": int(mask.sum()),
                "label_id": spec.label_id,
            }
        return components

    def _build_manifest(self, labeled_mask: np.ndarray) -> dict[str, Any]:
        labels: list[dict[str, Any]] = []
        for spec in self.LABEL_SPECS:
            voxel_count = int(np.count_nonzero(labeled_mask == spec.label_id))
            labels.append(
                {
                    "label_id": spec.label_id,
                    "key": spec.key,
                    "display_name": spec.display_name,
                    "color": spec.color,
                    "available": voxel_count > 0,
                    "visible_by_default": spec.visible_by_default,
                    "render_2d": spec.render_2d,
                    "render_3d": spec.render_3d,
                    "voxel_count": voxel_count,
                    "mesh_component_name": spec.key,
                }
            )

        return {
            "version": 1,
            "has_labeled_mask": True,
            "labels": labels,
        }

    @staticmethod
    def _build_labeled_mask(left_mask: np.ndarray, right_mask: np.ndarray, nodule_mask: np.ndarray) -> np.ndarray:
        labeled = np.zeros(left_mask.shape, dtype=np.uint8)
        labeled[np.asarray(left_mask, dtype=bool)] = 1
        labeled[np.asarray(right_mask, dtype=bool)] = 2
        labeled[np.asarray(nodule_mask, dtype=bool)] = 3
        return labeled

    def _get_nodule_pipeline(self) -> Any | None:
        if self._nodule_pipeline is not None:
            return self._nodule_pipeline
        if self._nodule_pipeline_error:
            return None

        try:
            import torch
            from ai.deeplung import DeepLungDetector, DeepLungDetectorConfig
            from ai.nodule_mask_pipeline import NoduleMaskPipeline, NoduleMaskPipelineConfig
            from ai.transattunet import (
                TransAttUnetPatchSegmenter,
                TransAttUnetPatchSegmenterConfig,
            )

            checkpoint_root = self.checkpoint_root
            if not checkpoint_root.exists():
                checkpoint_root = Path(__file__).resolve().parents[1] / "sandbox" / "checkpoints"

            device = "cuda" if torch.cuda.is_available() else "cpu"
            detection_ckpt = checkpoint_root / "detection" / "DeepLung.ckpt"
            segmentation_ckpt = checkpoint_root / "segmentation" / "TransAttUnet_v2.pth"
            if not segmentation_ckpt.exists():
                segmentation_ckpt = checkpoint_root / "segmentation" / "TransAttUnet.pth"
            if not detection_ckpt.exists() or not segmentation_ckpt.exists():
                raise FileNotFoundError("AI checkpoints are unavailable")

            detector = DeepLungDetector.from_checkpoint(
                detection_ckpt,
                config=DeepLungDetectorConfig(device=device),
            )
            patch_segmenter = TransAttUnetPatchSegmenter.from_checkpoint(
                segmentation_ckpt,
                config=TransAttUnetPatchSegmenterConfig(device=device),
            )
            self._nodule_pipeline = NoduleMaskPipeline(
                detector=detector,
                patch_segmenter=patch_segmenter,
                lung_segmenter=self.lung_segmenter,
                config=NoduleMaskPipelineConfig(),
            )
            return self._nodule_pipeline
        except Exception as exc:
            try:
                import torch
                from sandbox.deeplung import DeepLungDetector, DeepLungDetectorConfig
                from sandbox.nodule_mask_pipeline import NoduleMaskPipeline, NoduleMaskPipelineConfig
                from sandbox.transattunet import (
                    TransAttUnetPatchSegmenter,
                    TransAttUnetPatchSegmenterConfig,
                )

                checkpoint_root = Path(__file__).resolve().parents[1] / "sandbox" / "checkpoints"
                detection_ckpt = checkpoint_root / "detection" / "DeepLung.ckpt"
                segmentation_ckpt = checkpoint_root / "segmentation" / "TransAttUnet_v2.pth"
                if not segmentation_ckpt.exists():
                    segmentation_ckpt = checkpoint_root / "segmentation" / "TransAttUnet.pth"
                if not detection_ckpt.exists() or not segmentation_ckpt.exists():
                    raise FileNotFoundError("Sandbox checkpoints are unavailable")

                device = "cuda" if torch.cuda.is_available() else "cpu"
                detector = DeepLungDetector.from_checkpoint(
                    detection_ckpt,
                    config=DeepLungDetectorConfig(device=device),
                )
                patch_segmenter = TransAttUnetPatchSegmenter.from_checkpoint(
                    segmentation_ckpt,
                    config=TransAttUnetPatchSegmenterConfig(device=device),
                )
                self._nodule_pipeline = NoduleMaskPipeline(
                    detector=detector,
                    patch_segmenter=patch_segmenter,
                    lung_segmenter=self.lung_segmenter,
                    config=NoduleMaskPipelineConfig(),
                )
                self._nodule_pipeline_error = f"production_import_failed: {exc}"
                return self._nodule_pipeline
            except Exception as fallback_exc:
                self._nodule_pipeline_error = f"{exc}; fallback_failed: {fallback_exc}"
                return None
