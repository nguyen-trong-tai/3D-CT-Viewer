"""
Segmentation Module

Implements deterministic rule-based lung segmentation utilities for CT volumes.

Implements Nodule segmentation (processing)
    output: binary mask of each nodule
            contour 2D for each slice
            3D connected component
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy import ndimage


class LungSegmenter:
    """
    Rule-based 3D lung segmentation for CT volumes stored as (X, Y, Z).

    Pipeline:
        1. Build a body mask on each axial slice.
        2. Extract low-density air voxels inside the body mask.
        3. Keep the largest lung-like 3D components.
        4. Apply conservative 3D post-processing.
        5. Split the final mask into left and right lungs.
    """

    def __init__(
        self,
        hu_threshold: float = -400,
        min_lung_volume: int = 50_000,
        fill_holes: bool = True,
        body_threshold: float = -500,
        min_component_slices: int = 8,
    ):
        self.hu_threshold = hu_threshold
        self.min_lung_volume = min_lung_volume
        self.fill_holes = fill_holes
        self.body_threshold = body_threshold
        self.min_component_slices = min_component_slices

    def segment(self, volume_hu: np.ndarray) -> dict:
        """
        Segment lungs from a CT volume.

        Args:
            volume_hu: (X, Y, Z) numpy array in Hounsfield Units

        Returns:
            Dictionary with:
                "lung_mask":  (X, Y, Z) bool mask for both lungs
                "left_mask":  (X, Y, Z) bool mask for the left lung
                "right_mask": (X, Y, Z) bool mask for the right lung
                "stats":      segmentation statistics
        """
        print("[SEG] Step 1/5: build body mask...")
        body_mask = self._create_body_mask(volume_hu)

        print("[SEG] Step 2/5: extract internal air...")
        internal_air = self._extract_internal_air(volume_hu, body_mask)

        print("[SEG] Step 3/5: keep lung components...")
        lung_mask = self._keep_lung_components(internal_air)

        print("[SEG] Step 4/5: post-process lung mask...")
        lung_mask = self._postprocess_3d(lung_mask)

        print("[SEG] Step 5/5: split left/right lungs...")
        left_mask, right_mask = self._separate_lobes(lung_mask)
        components = self._build_components(lung_mask, left_mask, right_mask)

        stats = self._compute_stats(lung_mask, left_mask, right_mask)

        return {
            "lung_mask": lung_mask,
            "left_mask": left_mask,
            "right_mask": right_mask,
            "components": components,
            "stats": stats,
        }

    def _build_components(
        self,
        lung_mask: np.ndarray,
        left_mask: np.ndarray,
        right_mask: np.ndarray,
    ) -> dict:
        """
        Build a component-aware segmentation payload.

        The pipeline currently keeps a combined lung mask for 2D overlays while
        exposing left/right components for 3D rendering. Future segmenters can
        extend this structure with more components without changing the pipeline
        contract again.
        """
        component_specs = (
            ("lung", "Lungs", lung_mask, "#ef4444", True, False),
            ("left_lung", "Left Lung", left_mask, "#60a5fa", False, True),
            ("right_lung", "Right Lung", right_mask, "#34d399", False, True),
        )

        components: dict[str, dict] = {}
        for key, name, mask, color, render_2d, render_3d in component_specs:
            components[key] = {
                "name": name,
                "mask": mask.astype(bool, copy=False),
                "color": color,
                "render_2d": render_2d,
                "render_3d": render_3d,
                "voxel_count": int(mask.sum()),
            }

        return components

    def _create_body_mask(self, volume_hu: np.ndarray) -> np.ndarray:
        """
        Estimate the patient body mask slice-by-slice on axial planes.

        The key difference from the previous approach is that we do not remove
        air components by checking whether they touch the outer volume border.
        Instead, we first find the body and only keep air that is inside it.
        """
        body_mask = np.zeros_like(volume_hu, dtype=bool)
        open_structure = np.ones((3, 3), dtype=bool)
        close_structure = np.ones((5, 5), dtype=bool)

        for z in range(volume_hu.shape[2]):
            tissue = volume_hu[:, :, z] > self.body_threshold
            if not tissue.any():
                continue

            # Break weak links to the table, then restore the body outline.
            tissue = ndimage.binary_opening(tissue, structure=open_structure, iterations=1)
            tissue = ndimage.binary_closing(tissue, structure=close_structure, iterations=1)

            labeled, num_components = ndimage.label(tissue)
            if num_components == 0:
                continue

            body_label = self._select_body_component(labeled)
            if body_label == 0:
                continue

            body_slice = labeled == body_label
            body_slice = ndimage.binary_fill_holes(body_slice)
            body_slice = ndimage.binary_closing(body_slice, structure=close_structure, iterations=1)
            body_mask[:, :, z] = body_slice

        return body_mask

    def _select_body_component(self, labeled_slice: np.ndarray) -> int:
        """Choose the body component using a central-window prior."""
        component_sizes = np.bincount(labeled_slice.ravel())
        if component_sizes.size <= 1:
            return 0

        x_dim, y_dim = labeled_slice.shape
        x0, x1 = max(0, x_dim // 4), min(x_dim, (3 * x_dim) // 4)
        y0, y1 = max(0, y_dim // 4), min(y_dim, (3 * y_dim) // 4)

        center_labels = np.unique(labeled_slice[x0:x1, y0:y1])
        center_labels = center_labels[center_labels != 0]

        if center_labels.size > 0:
            return int(max(center_labels, key=lambda label_id: component_sizes[int(label_id)]))

        return int(np.argmax(component_sizes[1:]) + 1)

    def _extract_internal_air(self, volume_hu: np.ndarray, body_mask: np.ndarray) -> np.ndarray:
        """Keep only air-like voxels that fall inside the patient body mask."""
        air_mask = volume_hu < self.hu_threshold
        return air_mask & body_mask

    def _keep_lung_components(self, mask: np.ndarray) -> np.ndarray:
        """
        Keep the largest lung-like connected components.

        Component ranking favors both volume and superior-inferior extent so
        stomach/bowel gas is less likely to outrank true lungs.
        """
        if not mask.any():
            return np.zeros_like(mask, dtype=bool)

        structure = ndimage.generate_binary_structure(3, 1)
        labeled, num_components = ndimage.label(mask, structure=structure)
        if num_components == 0:
            return np.zeros_like(mask, dtype=bool)

        component_sizes = np.bincount(labeled.ravel())
        objects = ndimage.find_objects(labeled)
        candidates = []

        for label_id, bbox in enumerate(objects, start=1):
            if bbox is None:
                continue

            size = int(component_sizes[label_id])
            x_extent = bbox[0].stop - bbox[0].start
            y_extent = bbox[1].stop - bbox[1].start
            z_extent = bbox[2].stop - bbox[2].start

            if size == 0:
                continue

            score = float(size)
            score *= 1.0 + (z_extent / max(mask.shape[2], 1))
            score *= 1.0 + 0.5 * (x_extent / max(mask.shape[0], 1))
            score *= 1.0 + 0.25 * (y_extent / max(mask.shape[1], 1))

            candidates.append(
                {
                    "label_id": label_id,
                    "size": size,
                    "x_extent": x_extent,
                    "y_extent": y_extent,
                    "z_extent": z_extent,
                    "score": score,
                }
            )

        if not candidates:
            return np.zeros_like(mask, dtype=bool)

        large_candidates = [
            candidate
            for candidate in candidates
            if candidate["size"] >= self.min_lung_volume
            and candidate["z_extent"] >= min(self.min_component_slices, mask.shape[2])
        ]
        ranked_candidates = large_candidates if large_candidates else candidates
        ranked_candidates.sort(key=lambda candidate: (candidate["score"], candidate["size"]), reverse=True)

        keep_ids = [ranked_candidates[0]["label_id"]]
        if len(ranked_candidates) > 1 and large_candidates:
            keep_ids.append(ranked_candidates[1]["label_id"])
        elif len(ranked_candidates) > 1 and ranked_candidates[1]["size"] >= max(
            1,
            int(ranked_candidates[0]["size"] * 0.2),
        ):
            keep_ids.append(ranked_candidates[1]["label_id"])

        lung_mask = np.isin(labeled, keep_ids)
        return lung_mask.astype(bool, copy=False)

    def _postprocess_3d(self, mask: np.ndarray) -> np.ndarray:
        """
        Conservative post-processing that avoids deleting large lung regions.

        We fill holes on true axial slices (Z axis), then apply a light
        in-slice closing. Small noisy components are removed afterwards by
        running the component filter again instead of using an aggressive
        opening that can delete edge slices.
        """
        if not mask.any():
            return mask

        mask = mask.copy()

        close_structure = np.ones((3, 3), dtype=bool)

        if self.fill_holes:
            for z in range(mask.shape[2]):
                mask[:, :, z] = ndimage.binary_fill_holes(mask[:, :, z])

        for z in range(mask.shape[2]):
            mask[:, :, z] = ndimage.binary_closing(mask[:, :, z], structure=close_structure, iterations=1)

        if self.fill_holes:
            for z in range(mask.shape[2]):
                mask[:, :, z] = ndimage.binary_fill_holes(mask[:, :, z])

        return self._keep_lung_components(mask)

    def _separate_lobes(self, lung_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Split the mask along the left-right image axis (X).

        When two disconnected components already exist, they are assigned by
        X-centroid. Otherwise we split the combined mask at the X midline of
        the occupied bounding box.
        """
        empty_mask = np.zeros_like(lung_mask, dtype=bool)
        if not lung_mask.any():
            return empty_mask, empty_mask

        structure = ndimage.generate_binary_structure(3, 1)
        labeled, num_components = ndimage.label(lung_mask, structure=structure)
        component_sizes = np.bincount(labeled.ravel())
        objects = ndimage.find_objects(labeled)

        components = []
        for label_id, bbox in enumerate(objects, start=1):
            if bbox is None:
                continue
            size = int(component_sizes[label_id])
            if size == 0:
                continue
            centroid_x = 0.5 * (bbox[0].start + bbox[0].stop - 1)
            components.append((size, centroid_x, label_id))

        if len(components) >= 2:
            components.sort(key=lambda item: item[0], reverse=True)
            leading = components[:2]
            leading.sort(key=lambda item: item[1])
            right_label = leading[0][2]
            left_label = leading[1][2]
            left_mask = labeled == left_label
            right_mask = labeled == right_label
            return left_mask.astype(bool, copy=False), right_mask.astype(bool, copy=False)

        occupied_x = np.where(lung_mask.any(axis=(1, 2)))[0]
        if occupied_x.size == 0:
            return empty_mask, empty_mask

        mid_x = int((occupied_x[0] + occupied_x[-1]) / 2.0)

        right_mask = lung_mask.copy()
        right_mask[mid_x + 1 :, :, :] = False

        left_mask = lung_mask.copy()
        left_mask[: mid_x + 1, :, :] = False

        if not left_mask.any() or not right_mask.any():
            # Fallback to a hard split at the occupied X median.
            median_x = int(np.median(occupied_x))
            right_mask = lung_mask.copy()
            right_mask[median_x + 1 :, :, :] = False
            left_mask = lung_mask.copy()
            left_mask[: median_x + 1, :, :] = False

        return left_mask.astype(bool, copy=False), right_mask.astype(bool, copy=False)

    def _compute_stats(self, lung_mask: np.ndarray, left_mask: np.ndarray, right_mask: np.ndarray) -> dict:
        """Compute basic voxel statistics."""
        return {
            "total_voxels": int(lung_mask.sum()),
            "left_voxels": int(left_mask.sum()),
            "right_voxels": int(right_mask.sum()),
        }
