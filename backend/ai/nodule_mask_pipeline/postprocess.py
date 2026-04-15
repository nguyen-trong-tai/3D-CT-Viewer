from __future__ import annotations

from typing import Any

import numpy as np
from scipy import ndimage

from .mask_ops import (
    compute_minimum_component_voxels,
    dilate_mask,
    fill_mask_holes_per_slice,
    resolve_seed_and_support_thresholds,
)
from .models import NoduleMaskPipelineConfig
from .volume_ops import match_volume_shape, resample_volume_xyz


class MaskPostProcessor:
    def __init__(self, config: NoduleMaskPipelineConfig) -> None:
        self.config = config

    def post_process_probability_volume(
        self,
        probability_xyz: np.ndarray,
        lung_mask_xyz: np.ndarray,
        binary_xyz: np.ndarray | None = None,
        candidate_records: list[dict[str, Any]] | None = None,
    ) -> np.ndarray:
        seed_threshold, support_threshold = resolve_seed_and_support_thresholds(
            self.config.foreground_threshold,
            self.config.postprocess_support_threshold,
        )
        relaxed_lung_xyz = self._relax_lung_mask(lung_mask_xyz)
        repaired_binary_xyz = (
            np.asarray(binary_xyz, dtype=bool) & relaxed_lung_xyz
            if binary_xyz is not None
            else np.zeros_like(np.asarray(probability_xyz, dtype=bool), dtype=bool)
        )
        relaxed_lung_xyz = self._augment_relaxed_lung_mask_with_candidates(
            relaxed_lung_xyz=relaxed_lung_xyz,
            probability_xyz=probability_xyz,
            binary_xyz=repaired_binary_xyz if repaired_binary_xyz.any() else binary_xyz,
            candidate_records=list(candidate_records or []),
            support_threshold=support_threshold,
        )
        repaired_binary_xyz = (
            np.asarray(binary_xyz, dtype=bool) & relaxed_lung_xyz
            if binary_xyz is not None
            else np.zeros_like(np.asarray(probability_xyz, dtype=bool), dtype=bool)
        )
        seed_xyz = np.asarray(probability_xyz >= seed_threshold, dtype=bool) & relaxed_lung_xyz
        support_xyz = np.asarray(probability_xyz >= support_threshold, dtype=bool) & relaxed_lung_xyz
        seed_xyz |= repaired_binary_xyz
        support_xyz |= repaired_binary_xyz
        if not seed_xyz.any():
            seed_xyz = np.asarray(support_xyz, dtype=bool)
        if not seed_xyz.any():
            return np.zeros_like(seed_xyz, dtype=bool)

        structure = np.ones((3, 3, 3), dtype=bool)
        labeled, num_components = ndimage.label(seed_xyz, structure=structure)
        if num_components == 0:
            return np.zeros_like(seed_xyz, dtype=bool)

        component_sizes = np.bincount(labeled.ravel())
        min_voxels = self.minimum_component_voxels()
        keep_labels = [label for label in range(1, len(component_sizes)) if int(component_sizes[label]) >= min_voxels]
        keep_labels = self._augment_keep_labels_with_candidate_centers(
            keep_labels,
            labeled,
            component_sizes,
            list(candidate_records or []),
        )
        if not keep_labels:
            return np.zeros_like(seed_xyz, dtype=bool)

        keep_seed = np.isin(labeled, keep_labels)
        grown_mask = ndimage.binary_propagation(keep_seed, structure=structure, mask=support_xyz)
        grown_mask = ndimage.binary_closing(grown_mask, structure=structure, iterations=1)
        grown_mask |= repaired_binary_xyz
        grown_mask &= relaxed_lung_xyz
        grown_mask = self._fill_mask_holes(grown_mask)
        return np.asarray(grown_mask, dtype=bool)

    def map_mask_back_to_original(
        self,
        mask_xyz: np.ndarray,
        source_spacing_xyz: tuple[float, float, float],
        target_spacing_xyz: np.ndarray,
        target_shape_xyz: tuple[int, int, int],
    ) -> np.ndarray:
        resampled = resample_volume_xyz(
            np.asarray(mask_xyz, dtype=np.uint8),
            spacing_xyz=source_spacing_xyz,
            new_spacing_xyz=target_spacing_xyz,
            order=0,
        )
        matched = match_volume_shape((resampled > 0).astype(np.uint8), target_shape_xyz, pad_value=0)
        return np.asarray(matched > 0, dtype=bool)

    def minimum_component_voxels(self) -> int:
        return compute_minimum_component_voxels(
            self.config.min_component_volume_mm3,
            self.config.target_spacing_xyz,
        )

    def _relax_lung_mask(self, lung_mask_xyz: np.ndarray) -> np.ndarray:
        return dilate_mask(lung_mask_xyz, max(0, int(self.config.postprocess_lung_mask_dilation_iters)))

    @staticmethod
    def _augment_relaxed_lung_mask_with_candidates(
        relaxed_lung_xyz: np.ndarray,
        probability_xyz: np.ndarray,
        binary_xyz: np.ndarray | None,
        candidate_records: list[dict[str, Any]],
        support_threshold: float,
    ) -> np.ndarray:
        augmented = np.asarray(relaxed_lung_xyz, dtype=bool).copy()
        probability_bool = np.asarray(probability_xyz >= float(support_threshold), dtype=bool)
        binary_bool = (
            np.asarray(binary_xyz, dtype=bool)
            if binary_xyz is not None
            else np.zeros_like(probability_bool, dtype=bool)
        )
        shape = np.asarray(augmented.shape, dtype=int)

        for record in candidate_records:
            if not bool(record.get("accepted", False)):
                continue
            bbox = record.get("local_bbox_resampled_xyz")
            if not isinstance(bbox, list) or len(bbox) != 3:
                continue
            try:
                (x0, x1), (y0, y1), (z0, z1) = [
                    (
                        int(np.clip(int(axis_bounds[0]), 0, shape[idx])),
                        int(np.clip(int(axis_bounds[1]), 0, shape[idx])),
                    )
                    for idx, axis_bounds in enumerate(bbox)
                ]
            except (TypeError, ValueError, IndexError):
                continue
            if x0 >= x1 or y0 >= y1 or z0 >= z1:
                continue

            candidate_support = probability_bool[x0:x1, y0:y1, z0:z1] | binary_bool[x0:x1, y0:y1, z0:z1]
            if not candidate_support.any():
                continue
            augmented[x0:x1, y0:y1, z0:z1] |= candidate_support

        return augmented

    @staticmethod
    def _fill_mask_holes(mask_xyz: np.ndarray) -> np.ndarray:
        return fill_mask_holes_per_slice(mask_xyz)

    @staticmethod
    def _augment_keep_labels_with_candidate_centers(
        keep_labels: list[int],
        labeled: np.ndarray,
        component_sizes: np.ndarray,
        candidate_records: list[dict[str, Any]],
    ) -> list[int]:
        labels = {int(label) for label in keep_labels}
        if labeled.size == 0:
            return sorted(labels)
        shape = np.asarray(labeled.shape, dtype=int)
        for record in candidate_records:
            if not bool(record.get("accepted", False)):
                continue
            center = np.asarray(record.get("center_xyz_resampled_rounded", ()), dtype=int)
            if center.shape != (3,):
                continue
            center = np.clip(center, 0, shape - 1)
            label_id = int(labeled[center[0], center[1], center[2]])
            if label_id > 0 and int(component_sizes[label_id]) > 0:
                labels.add(label_id)
        return sorted(labels)

    @staticmethod
    def compute_component_stats(mask_xyz: np.ndarray, spacing_xyz: np.ndarray) -> list[dict[str, Any]]:
        mask_bool = np.asarray(mask_xyz, dtype=bool)
        if not mask_bool.any():
            return []

        labeled, _ = ndimage.label(mask_bool, structure=ndimage.generate_binary_structure(3, 1))
        component_sizes = np.bincount(labeled.ravel())
        objects = ndimage.find_objects(labeled)
        voxel_volume_mm3 = float(np.prod(np.asarray(spacing_xyz, dtype=np.float32)))
        stats: list[dict[str, Any]] = []
        for label_id, bbox in enumerate(objects, start=1):
            if bbox is None:
                continue
            voxel_count = int(component_sizes[label_id])
            if voxel_count <= 0:
                continue
            centroid = ndimage.center_of_mass(mask_bool.astype(np.uint8), labeled, label_id)
            stats.append(
                {
                    "label_id": int(label_id),
                    "voxel_count": voxel_count,
                    "volume_mm3": float(voxel_count * voxel_volume_mm3),
                    "bbox_xyz": [
                        [int(bbox[0].start), int(bbox[0].stop)],
                        [int(bbox[1].start), int(bbox[1].stop)],
                        [int(bbox[2].start), int(bbox[2].stop)],
                    ],
                    "centroid_xyz": [float(value) for value in centroid],
                }
            )
        stats.sort(key=lambda item: item["voxel_count"], reverse=True)
        return stats
