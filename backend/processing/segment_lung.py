"""
Segmentation Module

Implements deterministic rule-based lung segmentation utilities for CT volumes.

Implements Nodule segmentation (processing)
    output: binary mask of each nodule
            contour 2D for each slice
            3D connected component
"""

from __future__ import annotations

from time import perf_counter
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
        body_bbox_margin_px: int = 8,
        postprocess_bbox_margin_px: int = 4,
    ):
        self.hu_threshold = hu_threshold
        self.min_lung_volume = min_lung_volume
        self.fill_holes = fill_holes
        self.body_threshold = body_threshold
        self.min_component_slices = min_component_slices
        self.body_bbox_margin_px = max(0, int(body_bbox_margin_px))
        self.postprocess_bbox_margin_px = max(0, int(postprocess_bbox_margin_px))

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
        step_start = perf_counter()
        body_mask = self._create_body_mask(volume_hu)
        print(f"[SEG] Step 1/5 complete in {perf_counter() - step_start:.2f}s")

        print("[SEG] Step 2/5: extract internal air...")
        step_start = perf_counter()
        internal_air = self._extract_internal_air(volume_hu, body_mask)
        print(f"[SEG] Step 2/5 complete in {perf_counter() - step_start:.2f}s")

        print("[SEG] Step 3/5: keep lung components...")
        step_start = perf_counter()
        lung_mask = self._keep_lung_components(internal_air)
        print(f"[SEG] Step 3/5 complete in {perf_counter() - step_start:.2f}s")

        print("[SEG] Step 4/5: post-process lung mask...")
        step_start = perf_counter()
        lung_mask = self._postprocess_3d(lung_mask)
        print(f"[SEG] Step 4/5 complete in {perf_counter() - step_start:.2f}s")

        print("[SEG] Step 5/5: split left/right lungs...")
        step_start = perf_counter()
        left_mask, right_mask = self._separate_lobes(lung_mask)
        print(f"[SEG] Step 5/5 complete in {perf_counter() - step_start:.2f}s")
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
        tissue_volume = np.asarray(volume_hu > self.body_threshold, dtype=bool)
        active_z = np.flatnonzero(tissue_volume.any(axis=(0, 1)))
        if active_z.size == 0:
            return body_mask

        x_bounds, y_bounds = self._compute_xy_roi_bounds(tissue_volume, self.body_bbox_margin_px)
        if x_bounds is None or y_bounds is None:
            return body_mask
        x0, x1 = x_bounds
        y0, y1 = y_bounds
        roi_tissue_volume = tissue_volume[x0:x1, y0:y1, :]
        roi_body_mask = body_mask[x0:x1, y0:y1, :]
        morphology_time = 0.0
        label_time = 0.0
        finalize_time = 0.0
        closing_margin = max(close_structure.shape[0] // 2, close_structure.shape[1] // 2)

        for z in active_z:
            tissue = roi_tissue_volume[:, :, z]
            if not tissue.any():
                continue

            slice_bounds = self._compute_xy_roi_bounds_2d(tissue, self.body_bbox_margin_px)
            if slice_bounds is None:
                continue
            (slice_x0, slice_x1), (slice_y0, slice_y1) = slice_bounds
            cropped_tissue = tissue[slice_x0:slice_x1, slice_y0:slice_y1]

            # Break weak links to the table, then restore the body outline.
            timer = perf_counter()
            cropped_tissue = ndimage.binary_opening(cropped_tissue, structure=open_structure, iterations=1)
            cropped_tissue = ndimage.binary_closing(cropped_tissue, structure=close_structure, iterations=1)
            morphology_time += perf_counter() - timer

            timer = perf_counter()
            labeled, num_components = ndimage.label(cropped_tissue)
            if num_components == 0:
                label_time += perf_counter() - timer
                continue

            if num_components == 1:
                body_label = 1
            else:
                body_label = self._select_body_component(
                    labeled,
                    row_offset=x0 + slice_x0,
                    col_offset=y0 + slice_y0,
                    full_shape_xy=volume_hu.shape[:2],
                )
            label_time += perf_counter() - timer
            if body_label == 0:
                continue

            timer = perf_counter()
            body_slice = labeled == body_label
            component_bounds = self._compute_xy_roi_bounds_2d(body_slice, closing_margin)
            if component_bounds is None:
                finalize_time += perf_counter() - timer
                continue

            (body_x0, body_x1), (body_y0, body_y1) = component_bounds
            body_slice_roi = body_slice[body_x0:body_x1, body_y0:body_y1]
            body_slice_roi = ndimage.binary_fill_holes(body_slice_roi)
            body_slice_roi = ndimage.binary_closing(body_slice_roi, structure=close_structure, iterations=1)
            roi_body_mask[
                slice_x0 + body_x0 : slice_x0 + body_x1,
                slice_y0 + body_y0 : slice_y0 + body_y1,
                z,
            ] = body_slice_roi
            finalize_time += perf_counter() - timer

        print(
            "[SEG] Step 1 detail: "
            f"morphology={morphology_time:.2f}s, "
            f"label_select={label_time:.2f}s, "
            f"finalize={finalize_time:.2f}s",
        )

        return body_mask

    @staticmethod
    def _compute_xy_roi_bounds_2d(mask_xy: np.ndarray, margin: int) -> tuple[tuple[int, int], tuple[int, int]] | None:
        x_indices = np.flatnonzero(mask_xy.any(axis=1))
        y_indices = np.flatnonzero(mask_xy.any(axis=0))
        if x_indices.size == 0 or y_indices.size == 0:
            return None

        x0 = max(0, int(x_indices[0]) - margin)
        x1 = min(mask_xy.shape[0], int(x_indices[-1]) + margin + 1)
        y0 = max(0, int(y_indices[0]) - margin)
        y1 = min(mask_xy.shape[1], int(y_indices[-1]) + margin + 1)
        return (x0, x1), (y0, y1)

    @staticmethod
    def _compute_xy_roi_bounds(mask_xyz: np.ndarray, margin: int) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        x_indices = np.flatnonzero(mask_xyz.any(axis=(1, 2)))
        y_indices = np.flatnonzero(mask_xyz.any(axis=(0, 2)))
        if x_indices.size == 0 or y_indices.size == 0:
            return None, None

        x0 = max(0, int(x_indices[0]) - margin)
        x1 = min(mask_xyz.shape[0], int(x_indices[-1]) + margin + 1)
        y0 = max(0, int(y_indices[0]) - margin)
        y1 = min(mask_xyz.shape[1], int(y_indices[-1]) + margin + 1)
        return (x0, x1), (y0, y1)

    @staticmethod
    def _compute_xyz_roi_bounds(
        mask_xyz: np.ndarray,
        margin_xy: int = 0,
        margin_z: int = 0,
    ) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]] | None:
        x_indices = np.flatnonzero(mask_xyz.any(axis=(1, 2)))
        y_indices = np.flatnonzero(mask_xyz.any(axis=(0, 2)))
        z_indices = np.flatnonzero(mask_xyz.any(axis=(0, 1)))
        if x_indices.size == 0 or y_indices.size == 0 or z_indices.size == 0:
            return None

        x0 = max(0, int(x_indices[0]) - margin_xy)
        x1 = min(mask_xyz.shape[0], int(x_indices[-1]) + margin_xy + 1)
        y0 = max(0, int(y_indices[0]) - margin_xy)
        y1 = min(mask_xyz.shape[1], int(y_indices[-1]) + margin_xy + 1)
        z0 = max(0, int(z_indices[0]) - margin_z)
        z1 = min(mask_xyz.shape[2], int(z_indices[-1]) + margin_z + 1)
        return (x0, x1), (y0, y1), (z0, z1)

    def _select_body_component(
        self,
        labeled_slice: np.ndarray,
        row_offset: int = 0,
        col_offset: int = 0,
        full_shape_xy: tuple[int, int] | None = None,
    ) -> int:
        """Choose the body component using a central-window prior."""
        component_sizes = np.bincount(labeled_slice.ravel())
        if component_sizes.size <= 1:
            return 0

        if full_shape_xy is None:
            x_dim, y_dim = labeled_slice.shape
            x0, x1 = max(0, x_dim // 4), min(x_dim, (3 * x_dim) // 4)
            y0, y1 = max(0, y_dim // 4), min(y_dim, (3 * y_dim) // 4)
        else:
            full_x_dim, full_y_dim = [int(value) for value in full_shape_xy]
            global_x0 = max(0, full_x_dim // 4)
            global_x1 = min(full_x_dim, (3 * full_x_dim) // 4)
            global_y0 = max(0, full_y_dim // 4)
            global_y1 = min(full_y_dim, (3 * full_y_dim) // 4)
            x0 = max(0, int(global_x0 - row_offset))
            x1 = min(labeled_slice.shape[0], int(global_x1 - row_offset))
            y0 = max(0, int(global_y0 - col_offset))
            y1 = min(labeled_slice.shape[1], int(global_y1 - col_offset))

        center_labels = np.array([], dtype=labeled_slice.dtype)
        if x0 < x1 and y0 < y1:
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
        roi_bounds = self._compute_xyz_roi_bounds(
            mask,
            margin_xy=self.postprocess_bbox_margin_px,
            margin_z=1,
        )
        if roi_bounds is None:
            return mask
        (x0, x1), (y0, y1), (z0, z1) = roi_bounds
        roi_mask = mask[x0:x1, y0:y1, z0:z1]
        active_z = np.flatnonzero(roi_mask.any(axis=(0, 1)))
        if active_z.size == 0:
            return mask

        close_structure = np.ones((3, 3), dtype=bool)
        fill_first_time = 0.0
        closing_time = 0.0
        fill_second_time = 0.0

        if self.fill_holes:
            for z in active_z:
                timer = perf_counter()
                roi_mask[:, :, z] = ndimage.binary_fill_holes(roi_mask[:, :, z])
                fill_first_time += perf_counter() - timer

        for z in active_z:
            timer = perf_counter()
            roi_mask[:, :, z] = ndimage.binary_closing(roi_mask[:, :, z], structure=close_structure, iterations=1)
            closing_time += perf_counter() - timer

        if self.fill_holes:
            for z in active_z:
                timer = perf_counter()
                roi_mask[:, :, z] = ndimage.binary_fill_holes(roi_mask[:, :, z])
                fill_second_time += perf_counter() - timer

        timer = perf_counter()
        mask = self._keep_lung_components(mask)
        keep_components_time = perf_counter() - timer
        print(
            "[SEG] Step 4 detail: "
            f"fill_holes_1={fill_first_time:.2f}s, "
            f"closing={closing_time:.2f}s, "
            f"fill_holes_2={fill_second_time:.2f}s, "
            f"keep_components={keep_components_time:.2f}s",
        )
        return mask

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

        roi_bounds = self._compute_xyz_roi_bounds(lung_mask)
        if roi_bounds is None:
            return empty_mask, empty_mask
        (x0, x1), (y0, y1), (z0, z1) = roi_bounds
        roi_lung_mask = lung_mask[x0:x1, y0:y1, z0:z1]

        structure = ndimage.generate_binary_structure(3, 1)
        labeled, num_components = ndimage.label(roi_lung_mask, structure=structure)
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
            left_mask = empty_mask.copy()
            right_mask = empty_mask.copy()
            left_mask[x0:x1, y0:y1, z0:z1] = labeled == left_label
            right_mask[x0:x1, y0:y1, z0:z1] = labeled == right_label
            return left_mask.astype(bool, copy=False), right_mask.astype(bool, copy=False)

        occupied_x = np.where(roi_lung_mask.any(axis=(1, 2)))[0]
        if occupied_x.size == 0:
            return empty_mask, empty_mask

        mid_x_local = int((occupied_x[0] + occupied_x[-1]) / 2.0)

        right_roi_mask = roi_lung_mask.copy()
        right_roi_mask[mid_x_local + 1 :, :, :] = False

        left_roi_mask = roi_lung_mask.copy()
        left_roi_mask[: mid_x_local + 1, :, :] = False

        if not left_roi_mask.any() or not right_roi_mask.any():
            # Fallback to a hard split at the occupied X median.
            median_x = int(np.median(occupied_x))
            right_roi_mask = roi_lung_mask.copy()
            right_roi_mask[median_x + 1 :, :, :] = False
            left_roi_mask = roi_lung_mask.copy()
            left_roi_mask[: median_x + 1, :, :] = False

        left_mask = empty_mask.copy()
        right_mask = empty_mask.copy()
        left_mask[x0:x1, y0:y1, z0:z1] = left_roi_mask
        right_mask[x0:x1, y0:y1, z0:z1] = right_roi_mask
        return left_mask.astype(bool, copy=False), right_mask.astype(bool, copy=False)

    def _compute_stats(self, lung_mask: np.ndarray, left_mask: np.ndarray, right_mask: np.ndarray) -> dict:
        """Compute basic voxel statistics."""
        return {
            "total_voxels": int(lung_mask.sum()),
            "left_voxels": int(left_mask.sum()),
            "right_voxels": int(right_mask.sum()),
        }
