"""
AI segmentation service that combines lung segmentation with sandbox nodule masks.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from pathlib import Path
from typing import Any, Dict

import numpy as np
from scipy import ndimage

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


@dataclass(frozen=True)
class NoduleComponentRecord:
    label_id: int
    voxel_count: int
    centroid_xyz: tuple[float, float, float]
    bbox_xyz: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]
    local_mask: np.ndarray
    local_mask_origin_xyz: tuple[int, int, int]


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
        import time
        time_start = time.time()
        lung_result = self.lung_segmenter.segment(volume_xyz)
        end_time = time.time()
        print(f"Lung segmentation completed in {end_time - time_start:.2f} seconds.", flush=True)
        left_mask = np.asarray(lung_result.get("left_mask"), dtype=bool)
        right_mask = np.asarray(lung_result.get("right_mask"), dtype=bool)
        lung_mask = np.asarray(lung_result.get("lung_mask"), dtype=bool)

        nodule_mask = np.zeros_like(lung_mask, dtype=bool)
        nodule_debug: Dict[str, Any] = {"mode": "fallback_empty"}
        accepted_nodule_candidates: list[dict[str, Any]] = []
        pipeline_component_stats: list[dict[str, Any]] = []
        pipeline = self._get_nodule_pipeline()
        if pipeline is not None:
            try:
                pipeline_result = pipeline.run(
                    volume_hu_xyz=np.asarray(volume_xyz),
                    spacing_xyz_mm=spacing_xyz_mm,
                    lung_mask_xyz=lung_mask,
                )
                nodule_mask = np.asarray(pipeline_result.final_mask_xyz, dtype=bool)
                accepted_nodule_candidates = [
                    dict(candidate)
                    for candidate in (getattr(pipeline_result, "candidates", []) or [])
                    if bool(candidate.get("accepted", False))
                ]
                pipeline_component_stats = [
                    dict(component)
                    for component in (getattr(pipeline_result, "component_stats", []) or [])
                ]
                nodule_debug = {
                    "mode": "sandbox_ai",
                    "candidate_count": int(len(getattr(pipeline_result, "candidates", []) or [])),
                    "component_count": int(len(pipeline_component_stats)),
                    "component_stats": list(pipeline_component_stats),
                    "pipeline_debug": dict(getattr(pipeline_result, "debug", {}) or {}),
                }
            except Exception as exc:
                self._nodule_pipeline_error = str(exc)
                logger.exception("Nodule mask pipeline failed")
                nodule_debug = {"mode": "pipeline_error", "error": str(exc)}
        elif self._nodule_pipeline_error:
            nodule_debug = {"mode": "pipeline_unavailable", "error": self._nodule_pipeline_error}

        labeled_mask = self._build_labeled_mask(left_mask, right_mask, nodule_mask)
        nodule_components = self._build_nodule_components(
            nodule_mask,
            spacing_xyz_mm,
            accepted_candidates=accepted_nodule_candidates,
            component_stats=pipeline_component_stats,
        )
        manifest = self._build_manifest(labeled_mask, nodule_components)
        components = self._build_components(left_mask, right_mask, nodule_components)

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
        nodule_components: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        components: dict[str, dict[str, Any]] = {}
        for spec in self.LABEL_SPECS:
            if spec.key == "nodule":
                continue

            mask = np.asarray(left_mask if spec.key == "left_lung" else right_mask, dtype=bool)
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

        for nodule_component in nodule_components:
            entity = dict(nodule_component.get("entity") or {})
            mask = np.asarray(nodule_component.get("mask"), dtype=bool)
            mesh_component_name = str(entity.get("mesh_component_name") or entity.get("id") or "nodule")
            display_name = str(entity.get("display_name") or mesh_component_name.replace("_", " ").title())
            nodule_spec = next((spec for spec in self.LABEL_SPECS if spec.key == "nodule"), None)
            components[mesh_component_name] = {
                "name": display_name,
                "mask": mask,
                "color": nodule_spec.color if nodule_spec else "#f97316",
                "render_2d": False,
                "render_3d": True,
                "visible_by_default": True,
                "voxel_count": int(mask.sum()),
                "label_id": nodule_spec.label_id if nodule_spec else 3,
                "mask_origin_xyz": list(nodule_component.get("mask_origin_xyz") or (0, 0, 0)),
                "mask_is_cropped": True,
            }

        return components

    def _build_manifest(self, labeled_mask: np.ndarray, nodule_components: list[dict[str, Any]]) -> dict[str, Any]:
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
            "nodule_entities": [
                dict(component.get("entity") or {})
                for component in nodule_components
            ],
        }

    def _build_nodule_components(
        self,
        nodule_mask: np.ndarray,
        spacing_xyz_mm: tuple[float, float, float],
        accepted_candidates: list[dict[str, Any]] | None = None,
        component_stats: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        mask_bool = np.asarray(nodule_mask, dtype=bool)
        if not mask_bool.any():
            return []

        labeled, _ = ndimage.label(mask_bool, structure=ndimage.generate_binary_structure(3, 1))
        component_sizes = np.bincount(labeled.ravel())
        objects = ndimage.find_objects(labeled)
        spacing = np.asarray(spacing_xyz_mm, dtype=np.float32)
        voxel_volume_mm3 = float(np.prod(spacing))
        min_voxel_count = self._minimum_nodule_component_voxels(spacing_xyz_mm)
        component_records = self._build_component_records(
            labeled,
            component_sizes,
            objects,
            component_stats or [],
        )
        matched_candidates_by_label, matched_label_order = self._match_candidates_to_components(
            component_records,
            spacing_xyz_mm,
            accepted_candidates or [],
        )
        fallback_labels = [
            label_id
            for label_id, record in component_records.items()
            if label_id not in matched_candidates_by_label
            and int(record.voxel_count) >= min_voxel_count
        ]
        fallback_labels.sort(
            key=lambda label_id: (
                int(component_records[label_id].voxel_count),
                -int(label_id),
            ),
            reverse=True,
        )
        component_labels = matched_label_order + fallback_labels

        nodule_components: list[dict[str, Any]] = []
        for component_index, label_id in enumerate(component_labels, start=1):
            component_record = component_records.get(label_id)
            if component_record is None:
                continue

            voxel_count = int(component_record.voxel_count)
            centroid_xyz = np.asarray(component_record.centroid_xyz, dtype=np.float32)
            bbox_xyz = [
                [int(component_record.bbox_xyz[0][0]), int(component_record.bbox_xyz[0][1])],
                [int(component_record.bbox_xyz[1][0]), int(component_record.bbox_xyz[1][1])],
                [int(component_record.bbox_xyz[2][0]), int(component_record.bbox_xyz[2][1])],
            ]
            bbox_mm = [
                [float(bbox_xyz[0][0] * spacing[0]), float(bbox_xyz[0][1] * spacing[0])],
                [float(bbox_xyz[1][0] * spacing[1]), float(bbox_xyz[1][1] * spacing[1])],
                [float(bbox_xyz[2][0] * spacing[2]), float(bbox_xyz[2][1] * spacing[2])],
            ]
            extents_mm = [
                float((bbox_xyz[0][1] - bbox_xyz[0][0]) * spacing[0]),
                float((bbox_xyz[1][1] - bbox_xyz[1][0]) * spacing[1]),
                float((bbox_xyz[2][1] - bbox_xyz[2][0]) * spacing[2]),
            ]
            mesh_component_name = f"nodule_{component_index:03d}"
            matched_candidate = matched_candidates_by_label.get(label_id)
            entity: dict[str, Any] = {
                "id": mesh_component_name,
                "display_name": f"Nodule {component_index}",
                "mesh_component_name": mesh_component_name,
                "voxel_count": voxel_count,
                "volume_mm3": float(voxel_count * voxel_volume_mm3),
                "volume_ml": float(voxel_count * voxel_volume_mm3 / 1000.0),
                "centroid_xyz": [float(value) for value in centroid_xyz],
                "centroid_mm": [float(value) for value in (centroid_xyz * spacing)],
                "bbox_xyz": bbox_xyz,
                "bbox_mm": bbox_mm,
                "extents_mm": extents_mm,
                "estimated_diameter_mm": float(max(extents_mm) if extents_mm else 0.0),
                "slice_range": [
                    int(bbox_xyz[2][0]),
                    int(max(bbox_xyz[2][0], bbox_xyz[2][1] - 1)),
                ],
                "match_source": "candidate_match" if matched_candidate is not None else "size_fallback",
            }
            if matched_candidate is not None:
                if matched_candidate.get("candidate_index") is not None:
                    entity["candidate_index"] = int(matched_candidate.get("candidate_index"))
                if matched_candidate.get("score_probability") is not None:
                    entity["detection_score_probability"] = float(matched_candidate.get("score_probability"))
                if matched_candidate.get("score_logit") is not None:
                    entity["detection_score_logit"] = float(matched_candidate.get("score_logit"))

            nodule_components.append(
                {
                    "mask": component_record.local_mask,
                    "mask_origin_xyz": list(component_record.local_mask_origin_xyz),
                    "entity": entity,
                }
            )

        return nodule_components

    def _build_component_records(
        self,
        labeled: np.ndarray,
        component_sizes: np.ndarray,
        objects: list[slice | tuple[slice, ...] | None],
        component_stats: list[dict[str, Any]],
    ) -> dict[int, NoduleComponentRecord]:
        stats_by_label = {
            int(item.get("label_id")): dict(item)
            for item in component_stats
            if int(item.get("label_id", 0)) > 0
        }
        component_records: dict[int, NoduleComponentRecord] = {}

        for label_id, bbox in enumerate(objects, start=1):
            if bbox is None:
                continue

            voxel_count = int(component_sizes[label_id]) if label_id < len(component_sizes) else 0
            if voxel_count <= 0:
                continue

            component_stat = stats_by_label.get(label_id, {})
            bbox_xyz = self._resolve_bbox_xyz(component_stat.get("bbox_xyz"), bbox)
            local_mask, local_origin_xyz = self._extract_local_component_mask(labeled, label_id, bbox_xyz)
            centroid_xyz = self._resolve_centroid_xyz(component_stat.get("centroid_xyz"), labeled, label_id)
            component_records[label_id] = NoduleComponentRecord(
                label_id=int(label_id),
                voxel_count=voxel_count,
                centroid_xyz=centroid_xyz,
                bbox_xyz=bbox_xyz,
                local_mask=local_mask,
                local_mask_origin_xyz=local_origin_xyz,
            )

        return component_records

    def _minimum_nodule_component_voxels(self, spacing_xyz_mm: tuple[float, float, float]) -> int:
        min_component_volume_mm3 = 10.0
        pipeline_config = getattr(self._nodule_pipeline, "config", None)
        if pipeline_config is not None:
            min_component_volume_mm3 = float(getattr(pipeline_config, "min_component_volume_mm3", min_component_volume_mm3))

        voxel_volume_mm3 = float(np.prod(np.asarray(spacing_xyz_mm, dtype=np.float32)))
        if voxel_volume_mm3 <= 0.0:
            return 1

        return max(1, int(math.ceil(min_component_volume_mm3 / voxel_volume_mm3)))

    def _match_candidates_to_components(
        self,
        component_records: dict[int, NoduleComponentRecord],
        spacing_xyz_mm: tuple[float, float, float],
        accepted_candidates: list[dict[str, Any]],
    ) -> tuple[dict[int, dict[str, Any]], list[int]]:
        if not accepted_candidates or not component_records:
            return {}, []

        sorted_candidates = sorted(
            [dict(candidate) for candidate in accepted_candidates if bool(candidate.get("accepted", True))],
            key=lambda candidate: (
                -float(candidate.get("score_probability", 0.0)),
                int(candidate.get("candidate_index", 10 ** 6) or 10 ** 6),
                -float(candidate.get("score_logit", 0.0)),
            ),
        )
        remaining_labels = set(component_records.keys())
        matched_candidates_by_label: dict[int, dict[str, Any]] = {}
        matched_label_order: list[int] = []

        for candidate in sorted_candidates:
            best_label: int | None = None
            best_score: float | None = None
            for label_id in remaining_labels:
                score = self._score_candidate_component_match(
                    candidate,
                    component_records[label_id],
                    spacing_xyz_mm,
                )
                if score is None:
                    continue
                if best_score is None or score > best_score:
                    best_score = score
                    best_label = label_id

            if best_label is None:
                continue

            remaining_labels.remove(best_label)
            matched_candidates_by_label[best_label] = candidate
            matched_label_order.append(best_label)

        return matched_candidates_by_label, matched_label_order

    @staticmethod
    def _resolve_bbox_xyz(
        bbox_value: Any,
        fallback_bbox: tuple[slice, slice, slice],
    ) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
        if isinstance(bbox_value, list) and len(bbox_value) == 3:
            try:
                return (
                    (int(bbox_value[0][0]), int(bbox_value[0][1])),
                    (int(bbox_value[1][0]), int(bbox_value[1][1])),
                    (int(bbox_value[2][0]), int(bbox_value[2][1])),
                )
            except (TypeError, ValueError, IndexError):
                pass

        return (
            (int(fallback_bbox[0].start), int(fallback_bbox[0].stop)),
            (int(fallback_bbox[1].start), int(fallback_bbox[1].stop)),
            (int(fallback_bbox[2].start), int(fallback_bbox[2].stop)),
        )

    @staticmethod
    def _resolve_centroid_xyz(
        centroid_value: Any,
        labeled: np.ndarray,
        label_id: int,
    ) -> tuple[float, float, float]:
        if isinstance(centroid_value, list) and len(centroid_value) == 3:
            try:
                return (
                    float(centroid_value[0]),
                    float(centroid_value[1]),
                    float(centroid_value[2]),
                )
            except (TypeError, ValueError):
                pass

        component_mask = np.asarray(labeled == label_id, dtype=np.uint8)
        centroid = ndimage.center_of_mass(component_mask)
        return (float(centroid[0]), float(centroid[1]), float(centroid[2]))

    @staticmethod
    def _extract_local_component_mask(
        labeled: np.ndarray,
        label_id: int,
        bbox_xyz: tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
    ) -> tuple[np.ndarray, tuple[int, int, int]]:
        (x0, x1), (y0, y1), (z0, z1) = bbox_xyz
        local_mask = np.asarray(labeled[x0:x1, y0:y1, z0:z1] == int(label_id), dtype=np.uint8)
        return local_mask, (int(x0), int(y0), int(z0))

    @classmethod
    def _score_candidate_component_match(
        cls,
        candidate: dict[str, Any],
        component_record: NoduleComponentRecord,
        spacing_xyz_mm: tuple[float, float, float],
    ) -> float | None:
        center_xyz = np.asarray(
            candidate.get("center_xyz") or candidate.get("center_xyz_rounded") or (),
            dtype=np.float32,
        )
        if center_xyz.shape != (3,):
            return None

        spacing = np.asarray(spacing_xyz_mm, dtype=np.float32)
        spacing_safe = np.where(spacing > 0.0, spacing, 1.0)
        bbox_xyz = np.asarray(component_record.bbox_xyz, dtype=np.float32)
        center_inside = bool(np.all(center_xyz >= bbox_xyz[:, 0]) and np.all(center_xyz < bbox_xyz[:, 1]))

        diameter_mm = max(float(candidate.get("diameter_mm", 0.0)), float(np.min(spacing_safe)))
        candidate_radius_xyz = np.maximum(1.0, np.ceil((diameter_mm / spacing_safe) / 2.0))
        candidate_bbox_xyz = np.stack(
            [center_xyz - candidate_radius_xyz, center_xyz + candidate_radius_xyz + 1.0],
            axis=1,
        )
        intersection_volume = cls._bbox_intersection_volume(candidate_bbox_xyz, bbox_xyz)
        bbox_distance_mm = cls._point_to_bbox_distance_mm(center_xyz, bbox_xyz, spacing_safe)
        centroid_distance_mm = float(
            np.linalg.norm((np.asarray(component_record.centroid_xyz, dtype=np.float32) - center_xyz) * spacing_safe)
        )
        equivalent_diameter_mm = cls._equivalent_component_diameter_mm(
            component_record.voxel_count,
            spacing_safe,
        )
        diameter_error_mm = abs(equivalent_diameter_mm - diameter_mm)

        if not center_inside and intersection_volume <= 0.0 and bbox_distance_mm > max(6.0, diameter_mm * 1.5):
            return None

        return (
            float(candidate.get("score_probability", 0.0)) * 100.0
            + (5000.0 if center_inside else 0.0)
            + intersection_volume * 0.05
            - bbox_distance_mm * 20.0
            - centroid_distance_mm
            - diameter_error_mm * 0.5
            + min(50.0, math.log1p(max(component_record.voxel_count, 0)) * 5.0)
        )

    @staticmethod
    def _bbox_intersection_volume(candidate_bbox_xyz: np.ndarray, component_bbox_xyz: np.ndarray) -> float:
        overlap = np.maximum(
            0.0,
            np.minimum(candidate_bbox_xyz[:, 1], component_bbox_xyz[:, 1])
            - np.maximum(candidate_bbox_xyz[:, 0], component_bbox_xyz[:, 0]),
        )
        return float(np.prod(overlap))

    @staticmethod
    def _point_to_bbox_distance_mm(
        point_xyz: np.ndarray,
        bbox_xyz: np.ndarray,
        spacing_xyz_mm: np.ndarray,
    ) -> float:
        lower_delta = np.maximum(bbox_xyz[:, 0] - point_xyz, 0.0)
        upper_delta = np.maximum(point_xyz - (bbox_xyz[:, 1] - 1.0), 0.0)
        distance_xyz = (lower_delta + upper_delta) * spacing_xyz_mm
        return float(np.linalg.norm(distance_xyz))

    @staticmethod
    def _equivalent_component_diameter_mm(voxel_count: int, spacing_xyz_mm: np.ndarray) -> float:
        voxel_volume_mm3 = float(np.prod(spacing_xyz_mm))
        if voxel_count <= 0 or voxel_volume_mm3 <= 0.0:
            return 0.0
        volume_mm3 = float(voxel_count) * voxel_volume_mm3
        return float(((6.0 * volume_mm3) / math.pi) ** (1.0 / 3.0))

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
