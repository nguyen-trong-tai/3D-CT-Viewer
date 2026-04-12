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


class CandidateProbabilityFilter:
    def __init__(self, config: NoduleMaskPipelineConfig) -> None:
        self.config = config

    def filter(
        self,
        local_prob_xyz: np.ndarray,
        local_lung_xyz: np.ndarray,
        center_local_xyz: np.ndarray,
    ) -> tuple[np.ndarray | None, dict[str, Any], dict[str, np.ndarray]]:
        if str(self.config.local_filter_mode).strip().lower() == "binary_slice":
            return self._filter_binary_slice_first(local_prob_xyz, local_lung_xyz, center_local_xyz)
        return self._filter_probability_first(local_prob_xyz, local_lung_xyz, center_local_xyz)

    def _filter_probability_first(
        self,
        local_prob_xyz: np.ndarray,
        local_lung_xyz: np.ndarray,
        center_local_xyz: np.ndarray,
    ) -> tuple[np.ndarray | None, dict[str, Any], dict[str, np.ndarray]]:
        seed_threshold, support_threshold = resolve_seed_and_support_thresholds(
            min(self.config.foreground_threshold, self.config.local_foreground_threshold),
            self.config.local_support_threshold,
        )
        relaxed_lung_xyz = self._build_relaxed_lung_mask(local_lung_xyz, local_prob_xyz, center_local_xyz)
        seed_binary_xyz = np.asarray(local_prob_xyz >= seed_threshold, dtype=bool) & relaxed_lung_xyz
        support_binary_xyz = np.asarray(local_prob_xyz >= support_threshold, dtype=bool) & relaxed_lung_xyz
        selection_source = "seed_threshold"
        if not seed_binary_xyz.any():
            seed_binary_xyz = np.asarray(support_binary_xyz, dtype=bool)
            selection_source = "support_fallback"
        if not seed_binary_xyz.any():
            return self._reject(
                "empty_after_threshold",
                {
                    "threshold_used": seed_threshold,
                    "support_threshold_used": support_threshold,
                },
                relaxed_lung_xyz=relaxed_lung_xyz,
                seed_binary_xyz=seed_binary_xyz,
                support_binary_xyz=support_binary_xyz,
            )

        labeled, valid_labels, min_voxels, error = self._label_valid_components(seed_binary_xyz, center_local_xyz)
        if error is not None:
            return self._reject(
                error,
                {
                    "min_voxels": int(min_voxels),
                    "threshold_used": seed_threshold,
                    "support_threshold_used": support_threshold,
                },
                relaxed_lung_xyz=relaxed_lung_xyz,
                seed_binary_xyz=seed_binary_xyz,
                support_binary_xyz=support_binary_xyz,
                labeled_seed_xyz=labeled,
            )

        selected_label, selection_mode, center_label = self._select_component_label(
            labeled=labeled,
            valid_labels=valid_labels,
            center_local_xyz=center_local_xyz,
            local_prob_xyz=local_prob_xyz,
        )
        selected_mask = labeled == selected_label
        if not selected_mask.any():
            return self._reject(
                "selected_component_empty",
                {},
                relaxed_lung_xyz=relaxed_lung_xyz,
                seed_binary_xyz=seed_binary_xyz,
                support_binary_xyz=support_binary_xyz,
                labeled_seed_xyz=labeled,
            )

        structure = np.ones((3, 3, 3), dtype=bool)
        grown_mask = ndimage.binary_propagation(selected_mask, structure=structure, mask=support_binary_xyz)
        grown_mask = ndimage.binary_closing(grown_mask, structure=structure, iterations=1)
        grown_mask &= relaxed_lung_xyz
        grown_mask = self._fill_mask_holes(grown_mask)
        grown_mask = self._fill_small_z_gaps(grown_mask, support_binary_xyz)
        if not grown_mask.any():
            grown_mask = selected_mask

        centroid = ndimage.center_of_mass(grown_mask.astype(np.uint8))
        return (
            np.where(grown_mask, local_prob_xyz, 0.0).astype(np.float32, copy=False),
            {
                "reason": "accepted",
                "filter_mode": "probability",
                "selected_label": int(selected_label),
                "selected_voxel_count": int(selected_mask.sum()),
                "grown_voxel_count": int(grown_mask.sum()),
                "selected_centroid_local_xyz": [float(value) for value in centroid],
                "min_voxels": int(min_voxels),
                "threshold_used": seed_threshold,
                "support_threshold_used": support_threshold,
                "selection_mode": selection_mode,
                "selection_source": selection_source,
                "center_label": int(center_label),
                "valid_label_count": int(len(valid_labels)),
            },
            {
                "relaxed_lung_xyz": relaxed_lung_xyz.astype(np.uint8, copy=False),
                "seed_binary_xyz": seed_binary_xyz.astype(np.uint8, copy=False),
                "support_binary_xyz": support_binary_xyz.astype(np.uint8, copy=False),
                "labeled_seed_xyz": labeled.astype(np.int16, copy=False),
                "selected_mask_xyz": selected_mask.astype(np.uint8, copy=False),
                "grown_mask_xyz": grown_mask.astype(np.uint8, copy=False),
            },
        )

    def _filter_binary_slice_first(
        self,
        local_prob_xyz: np.ndarray,
        local_lung_xyz: np.ndarray,
        center_local_xyz: np.ndarray,
    ) -> tuple[np.ndarray | None, dict[str, Any], dict[str, np.ndarray]]:
        relaxed_lung_xyz = self._build_relaxed_lung_mask(local_lung_xyz, local_prob_xyz, center_local_xyz)
        slice_threshold, support_threshold = resolve_seed_and_support_thresholds(
            min(self.config.foreground_threshold, self.config.local_foreground_threshold),
            self.config.local_support_threshold,
        )

        binary_xyz = np.zeros_like(local_prob_xyz, dtype=bool)
        kept_slice_count = 0
        for z_index in range(local_prob_xyz.shape[2]):
            slice_binary = self._build_slice_binary_mask(
                prob_slice_xy=np.asarray(local_prob_xyz[:, :, z_index], dtype=np.float32),
                lung_slice_xy=np.asarray(relaxed_lung_xyz[:, :, z_index], dtype=bool),
                center_local_xy=np.asarray(center_local_xyz[:2], dtype=np.float32),
                threshold=slice_threshold,
            )
            if slice_binary.any():
                kept_slice_count += 1
            binary_xyz[:, :, z_index] = slice_binary

        if not binary_xyz.any():
            return self._reject(
                "empty_after_slice_binarization",
                {
                    "filter_mode": "binary_slice",
                    "threshold_used": slice_threshold,
                    "support_threshold_used": support_threshold,
                },
                relaxed_lung_xyz=relaxed_lung_xyz,
                slice_binary_xyz=binary_xyz,
            )

        binary_xyz &= relaxed_lung_xyz
        binary_xyz = self._fill_mask_holes(binary_xyz)
        support_binary_xyz = np.asarray(local_prob_xyz >= support_threshold, dtype=bool) & relaxed_lung_xyz
        combined_support_xyz = np.asarray(binary_xyz | support_binary_xyz, dtype=bool)
        binary_xyz = self._fill_small_z_gaps(binary_xyz, support_binary_xyz)
        binary_xyz = ndimage.binary_closing(binary_xyz, structure=np.ones((3, 3, 3), dtype=bool), iterations=1)
        binary_xyz &= relaxed_lung_xyz

        labeled, valid_labels, min_voxels, error = self._label_valid_components(binary_xyz, center_local_xyz)
        if error is not None:
            return self._reject(
                error,
                {
                    "filter_mode": "binary_slice",
                    "min_voxels": int(min_voxels),
                    "threshold_used": slice_threshold,
                    "support_threshold_used": support_threshold,
                },
                relaxed_lung_xyz=relaxed_lung_xyz,
                slice_binary_xyz=binary_xyz,
                support_binary_xyz=support_binary_xyz,
                labeled_slice_stack_xyz=labeled,
            )

        selected_label, selection_mode, center_label = self._select_component_label(
            labeled=labeled,
            valid_labels=valid_labels,
            center_local_xyz=center_local_xyz,
            local_prob_xyz=local_prob_xyz,
        )
        selected_mask = labeled == selected_label
        if not selected_mask.any():
            return self._reject(
                "selected_component_empty",
                {"filter_mode": "binary_slice"},
                relaxed_lung_xyz=relaxed_lung_xyz,
                slice_binary_xyz=binary_xyz,
                support_binary_xyz=support_binary_xyz,
                labeled_slice_stack_xyz=labeled,
            )

        grown_mask = ndimage.binary_propagation(
            selected_mask,
            structure=np.ones((3, 3, 3), dtype=bool),
            mask=combined_support_xyz,
        )
        grown_mask = self._fill_mask_holes(grown_mask)
        grown_mask = self._fill_small_z_gaps(grown_mask, combined_support_xyz)
        grown_mask = self._restore_thin_slices(grown_mask, combined_support_xyz, center_local_xyz)
        grown_mask &= relaxed_lung_xyz

        centroid = ndimage.center_of_mass(grown_mask.astype(np.uint8))
        return (
            np.where(grown_mask, local_prob_xyz, 0.0).astype(np.float32, copy=False),
            {
                "reason": "accepted",
                "filter_mode": "binary_slice",
                "selected_label": int(selected_label),
                "selected_voxel_count": int(selected_mask.sum()),
                "grown_voxel_count": int(grown_mask.sum()),
                "kept_slice_count": int(kept_slice_count),
                "selected_centroid_local_xyz": [float(value) for value in centroid],
                "min_voxels": int(min_voxels),
                "threshold_used": slice_threshold,
                "support_threshold_used": support_threshold,
                "selection_mode": selection_mode,
                "center_label": int(center_label),
                "valid_label_count": int(len(valid_labels)),
            },
            {
                "relaxed_lung_xyz": relaxed_lung_xyz.astype(np.uint8, copy=False),
                "slice_binary_xyz": binary_xyz.astype(np.uint8, copy=False),
                "support_binary_xyz": support_binary_xyz.astype(np.uint8, copy=False),
                "labeled_slice_stack_xyz": labeled.astype(np.int16, copy=False),
                "selected_mask_xyz": selected_mask.astype(np.uint8, copy=False),
                "grown_mask_xyz": grown_mask.astype(np.uint8, copy=False),
            },
        )

    def minimum_component_voxels(self) -> int:
        return compute_minimum_component_voxels(
            self.config.min_component_volume_mm3,
            self.config.target_spacing_xyz,
        )

    def _label_valid_components(
        self,
        mask_xyz: np.ndarray,
        center_local_xyz: np.ndarray,
    ) -> tuple[np.ndarray, list[int], int, str | None]:
        labeled, num_components = ndimage.label(mask_xyz, structure=np.ones((3, 3, 3), dtype=bool))
        if num_components == 0:
            return labeled, [], self.minimum_component_voxels(), "no_components"

        component_sizes = np.bincount(labeled.ravel())
        min_voxels = self.minimum_component_voxels()
        valid_labels = [label for label in range(1, len(component_sizes)) if int(component_sizes[label]) >= min_voxels]
        if not valid_labels:
            valid_labels = self._fallback_valid_labels(component_sizes, center_local_xyz, labeled)
        if not valid_labels:
            return labeled, [], min_voxels, "all_components_below_min_volume"
        return labeled, valid_labels, min_voxels, None

    def _fallback_valid_labels(
        self,
        component_sizes: np.ndarray,
        center_local_xyz: np.ndarray,
        labeled: np.ndarray,
    ) -> list[int]:
        rounded_center = np.clip(
            np.rint(center_local_xyz).astype(int),
            0,
            np.asarray(labeled.shape, dtype=int) - 1,
        )
        center_label = int(labeled[rounded_center[0], rounded_center[1], rounded_center[2]])
        if center_label > 0 and int(component_sizes[center_label]) > 0:
            return [center_label]

        nearby_labels: list[int] = []
        radius = float(max(self.config.center_fallback_radius_vox, 1.0))
        for label_id in range(1, len(component_sizes)):
            if int(component_sizes[label_id]) <= 0:
                continue
            centroid = np.asarray(ndimage.center_of_mass((labeled == label_id).astype(np.uint8)), dtype=np.float32)
            if float(np.linalg.norm(centroid - center_local_xyz)) <= radius:
                nearby_labels.append(int(label_id))
        return nearby_labels

    def _build_relaxed_lung_mask(
        self,
        local_lung_xyz: np.ndarray,
        local_prob_xyz: np.ndarray,
        center_local_xyz: np.ndarray,
    ) -> np.ndarray:
        relaxed = dilate_mask(local_lung_xyz, max(0, int(self.config.local_lung_mask_dilation_iters)))
        return self._apply_center_override(relaxed, local_prob_xyz, center_local_xyz)

    def _apply_center_override(
        self,
        relaxed_lung_xyz: np.ndarray,
        local_prob_xyz: np.ndarray,
        center_local_xyz: np.ndarray,
    ) -> np.ndarray:
        override_radius = float(max(0.0, self.config.local_center_override_radius_vox))
        override_threshold = float(max(0.0, self.config.local_center_override_threshold))
        relaxed = np.asarray(relaxed_lung_xyz, dtype=bool).copy()
        if override_radius <= 0.0 or relaxed.size == 0:
            return relaxed

        grid_x, grid_y, grid_z = np.ogrid[:relaxed.shape[0], :relaxed.shape[1], :relaxed.shape[2]]
        center = np.asarray(center_local_xyz, dtype=np.float32)
        distance = np.sqrt(
            (grid_x - float(center[0])) ** 2
            + (grid_y - float(center[1])) ** 2
            + (grid_z - float(center[2])) ** 2
        )
        override_region = distance <= override_radius
        strong_center_prob = np.asarray(local_prob_xyz, dtype=np.float32) >= override_threshold
        relaxed |= override_region & strong_center_prob
        return relaxed

    @staticmethod
    def _fill_mask_holes(mask_xyz: np.ndarray) -> np.ndarray:
        return fill_mask_holes_per_slice(mask_xyz)

    def _fill_small_z_gaps(self, mask_xyz: np.ndarray, support_xyz: np.ndarray) -> np.ndarray:
        max_gap = max(0, int(self.config.local_max_gap_slices))
        filled = np.asarray(mask_xyz, dtype=bool).copy()
        if max_gap <= 0 or filled.shape[2] <= 2 or not filled.any():
            return filled

        support = np.asarray(support_xyz, dtype=bool)
        for x_index in range(filled.shape[0]):
            for y_index in range(filled.shape[1]):
                z_hits = np.flatnonzero(filled[x_index, y_index, :])
                if z_hits.size < 2:
                    continue
                for left_z, right_z in zip(z_hits[:-1], z_hits[1:]):
                    gap = int(right_z - left_z - 1)
                    if gap <= 0 or gap > max_gap:
                        continue
                    gap_slice = slice(left_z + 1, right_z)
                    if np.all(support[x_index, y_index, gap_slice]):
                        filled[x_index, y_index, gap_slice] = True
        return filled

    def _build_slice_binary_mask(
        self,
        prob_slice_xy: np.ndarray,
        lung_slice_xy: np.ndarray,
        center_local_xy: np.ndarray,
        threshold: float,
    ) -> np.ndarray:
        binary_xy = np.asarray(prob_slice_xy >= float(threshold), dtype=bool)
        binary_xy &= np.asarray(lung_slice_xy, dtype=bool)
        if not binary_xy.any():
            return binary_xy

        binary_xy = ndimage.binary_fill_holes(binary_xy)
        closing_iters = max(0, int(self.config.local_slice_closing_iters))
        if closing_iters > 0:
            binary_xy = ndimage.binary_closing(binary_xy, structure=np.ones((3, 3), dtype=bool), iterations=closing_iters)

        labeled, num_components = ndimage.label(binary_xy, structure=np.ones((3, 3), dtype=bool))
        if num_components == 0:
            return np.zeros_like(binary_xy, dtype=bool)

        component_sizes = np.bincount(labeled.ravel())
        min_area = max(1, int(self.config.local_slice_min_area_voxels))
        keep_labels = [label for label in range(1, len(component_sizes)) if int(component_sizes[label]) >= min_area]
        if not keep_labels:
            keep_labels = [int(np.argmax(component_sizes[1:]) + 1)] if len(component_sizes) > 1 else []
        if not keep_labels:
            return np.zeros_like(binary_xy, dtype=bool)

        if bool(self.config.local_keep_center_only_per_slice):
            center_xy = np.clip(
                np.rint(center_local_xy).astype(int),
                0,
                np.asarray(binary_xy.shape, dtype=int) - 1,
            )
            center_label = int(labeled[center_xy[0], center_xy[1]])
            if center_label in keep_labels:
                keep_labels = [center_label]
            else:
                best_label = keep_labels[0]
                best_score = float("-inf")
                for label_id in keep_labels:
                    component_mask = labeled == label_id
                    centroid = np.asarray(ndimage.center_of_mass(component_mask.astype(np.uint8)), dtype=np.float32)
                    distance = float(np.linalg.norm(centroid - center_local_xy))
                    total_mass = float(np.asarray(prob_slice_xy[component_mask], dtype=np.float32).sum())
                    score = total_mass - distance * 0.25
                    if score > best_score:
                        best_score = score
                        best_label = int(label_id)
                keep_labels = [best_label]

        cleaned = np.isin(labeled, keep_labels)
        cleaned = ndimage.binary_fill_holes(cleaned)
        return np.asarray(cleaned, dtype=bool)

    def _restore_thin_slices(
        self,
        mask_xyz: np.ndarray,
        support_xyz: np.ndarray,
        center_local_xyz: np.ndarray,
    ) -> np.ndarray:
        restored = np.asarray(mask_xyz, dtype=bool).copy()
        support = np.asarray(support_xyz, dtype=bool)
        if restored.shape[2] < 3 or not restored.any():
            return restored

        thin_ratio = float(max(0.0, min(1.0, self.config.local_restore_thin_slice_ratio)))
        if thin_ratio <= 0.0:
            return restored

        center_xy = np.clip(
            np.rint(np.asarray(center_local_xyz[:2], dtype=np.float32)).astype(int),
            0,
            np.asarray(restored.shape[:2], dtype=int) - 1,
        )
        inplane_structure = np.ones((3, 3), dtype=bool)
        slice_areas = restored.sum(axis=(0, 1)).astype(np.int32)

        for z_index in range(1, restored.shape[2] - 1):
            prev_area = int(slice_areas[z_index - 1])
            curr_area = int(slice_areas[z_index])
            next_area = int(slice_areas[z_index + 1])
            if prev_area <= 0 or next_area <= 0:
                continue
            if curr_area >= int(round(min(prev_area, next_area) * thin_ratio)):
                continue

            prev_slice = restored[:, :, z_index - 1]
            next_slice = restored[:, :, z_index + 1]
            support_slice = support[:, :, z_index]
            if not support_slice.any():
                continue

            bridge = ndimage.binary_dilation(prev_slice, structure=inplane_structure, iterations=1)
            bridge |= ndimage.binary_dilation(next_slice, structure=inplane_structure, iterations=1)
            bridge &= support_slice
            bridge = ndimage.binary_fill_holes(bridge)
            if not bridge.any():
                continue

            if not bridge[center_xy[0], center_xy[1]]:
                component_labels, component_count = ndimage.label(bridge, structure=inplane_structure)
                if component_count <= 0:
                    continue
                center_label = int(component_labels[center_xy[0], center_xy[1]])
                if center_label > 0:
                    bridge = component_labels == center_label
                else:
                    sizes = np.bincount(component_labels.ravel())
                    best_label = int(np.argmax(sizes[1:]) + 1) if len(sizes) > 1 else 0
                    if best_label <= 0:
                        continue
                    bridge = component_labels == best_label

            restored[:, :, z_index] |= bridge
            restored[:, :, z_index] = ndimage.binary_fill_holes(restored[:, :, z_index])
            slice_areas[z_index] = int(restored[:, :, z_index].sum())
        return restored

    def _select_component_label(
        self,
        labeled: np.ndarray,
        valid_labels: list[int],
        center_local_xyz: np.ndarray,
        local_prob_xyz: np.ndarray,
    ) -> tuple[int, str, int]:
        rounded_center = np.clip(
            np.rint(center_local_xyz).astype(int),
            0,
            np.asarray(local_prob_xyz.shape, dtype=int) - 1,
        )
        center_label = int(labeled[rounded_center[0], rounded_center[1], rounded_center[2]])
        if center_label in valid_labels:
            return center_label, "center_label", center_label
        return (
            self._best_component_label(labeled, valid_labels, center_local_xyz, local_prob_xyz),
            "probability_near_center",
            center_label,
        )

    def _best_component_label(
        self,
        labeled: np.ndarray,
        valid_labels: list[int],
        center_local_xyz: np.ndarray,
        local_prob_xyz: np.ndarray,
    ) -> int:
        best_label = int(valid_labels[0])
        best_score = float("-inf")
        radius = float(max(self.config.center_fallback_radius_vox, 1.0))
        for label_id in valid_labels:
            component_mask = labeled == label_id
            centroid = np.asarray(ndimage.center_of_mass(component_mask.astype(np.uint8)), dtype=np.float32)
            distance = float(np.linalg.norm(centroid - center_local_xyz))
            coords = np.argwhere(component_mask)
            if coords.size == 0:
                continue
            distances = np.linalg.norm(coords.astype(np.float32) - center_local_xyz[np.newaxis, :], axis=1)
            near_center_coords = coords[distances <= radius]
            if near_center_coords.size == 0:
                near_center_mass = 0.0
            else:
                near_center_mass = float(
                    np.asarray(
                        local_prob_xyz[
                            near_center_coords[:, 0],
                            near_center_coords[:, 1],
                            near_center_coords[:, 2],
                        ],
                        dtype=np.float32,
                    ).sum()
                )
            total_mass = float(np.asarray(local_prob_xyz[component_mask], dtype=np.float32).sum())
            score = near_center_mass * 4.0 + total_mass - distance * 0.25
            if score > best_score:
                best_score = score
                best_label = int(label_id)
        return best_label

    @staticmethod
    def _reject(reason: str, extra_stats: dict[str, Any], **debug_arrays: np.ndarray) -> tuple[None, dict[str, Any], dict[str, np.ndarray]]:
        stats = {"reason": str(reason)}
        stats.update(extra_stats)
        debug: dict[str, np.ndarray] = {}
        for key, value in debug_arrays.items():
            array = np.asarray(value)
            if "labeled" in key:
                debug[key] = np.asarray(array, dtype=np.int16)
            else:
                debug[key] = np.asarray(array, dtype=np.uint8)
        return None, stats, debug
