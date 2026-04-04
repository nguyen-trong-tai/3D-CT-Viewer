"""
Signed Distance Function (SDF) Module

Computes implicit surface representations from binary segmentation masks.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy.ndimage import distance_transform_edt, zoom

from config import settings


class SDFProcessor:
    """Utility methods for SDF computation and normalization."""

    @staticmethod
    def compute(mask: np.ndarray, spacing: Tuple[float, float, float] | None = None) -> np.ndarray:
        """Compute a signed distance field from a binary mask."""
        mask_bool = mask.astype(bool)
        kwargs = {"sampling": spacing} if spacing is not None else {}

        dist_outside = distance_transform_edt(~mask_bool, **kwargs)
        dist_inside = distance_transform_edt(mask_bool, **kwargs)
        return dist_outside - dist_inside

    @staticmethod
    def compute_fast(mask: np.ndarray, spacing: Tuple[float, float, float] | None = None) -> np.ndarray:
        """Memory-conscious SDF computation for standard-size volumes."""
        if mask.dtype == np.uint8:
            mask_bool = mask.view(bool).reshape(mask.shape)
        else:
            mask_bool = mask.astype(bool)

        kwargs = {"sampling": spacing} if spacing is not None else {}

        sdf = distance_transform_edt(~mask_bool, **kwargs)
        dist_inside = distance_transform_edt(mask_bool, **kwargs)
        np.subtract(sdf, dist_inside, out=sdf)
        return sdf

    @classmethod
    def compute_downsampled(
        cls,
        mask: np.ndarray,
        factor: int = 2,
        spacing: Tuple[float, float, float] | None = None,
    ) -> np.ndarray:
        """Compute the SDF on a downsampled mask and upsample the result."""
        if factor <= 1:
            return cls.compute_fast(mask, spacing)

        small_mask = mask[::factor, ::factor, ::factor]

        small_spacing = None
        if spacing is not None:
            small_spacing = tuple(step * factor for step in spacing)

        small_sdf = cls.compute_fast(small_mask, small_spacing)

        if spacing is None:
            small_sdf *= factor

        target_shape = mask.shape
        zoom_factors = [target / source for target, source in zip(target_shape, small_sdf.shape)]
        return zoom(small_sdf, zoom_factors, order=1)

    @classmethod
    def compute_chunked(
        cls,
        mask: np.ndarray,
        chunk_size: int = 128,
        overlap: int = 16,
        spacing: Tuple[float, float, float] | None = None,
    ) -> np.ndarray:
        """Compute SDF in overlapping chunks for very large volumes."""
        shape = mask.shape
        sdf = np.zeros(shape, dtype=np.float32)

        for z0 in range(0, shape[2], chunk_size - overlap):
            z1 = min(z0 + chunk_size, shape[2])

            for y0 in range(0, shape[1], chunk_size - overlap):
                y1 = min(y0 + chunk_size, shape[1])

                for x0 in range(0, shape[0], chunk_size - overlap):
                    x1 = min(x0 + chunk_size, shape[0])
                    chunk = mask[x0:x1, y0:y1, z0:z1]
                    chunk_sdf = cls.compute(chunk, spacing)

                    cx0 = overlap // 2 if x0 > 0 else 0
                    cy0 = overlap // 2 if y0 > 0 else 0
                    cz0 = overlap // 2 if z0 > 0 else 0
                    cx1 = x1 - x0 - (overlap // 2 if x1 < shape[0] else 0)
                    cy1 = y1 - y0 - (overlap // 2 if y1 < shape[1] else 0)
                    cz1 = z1 - z0 - (overlap // 2 if z1 < shape[2] else 0)

                    sdf[
                        x0 + cx0 : x0 + cx1,
                        y0 + cy0 : y0 + cy1,
                        z0 + cz0 : z0 + cz1,
                    ] = chunk_sdf[cx0:cx1, cy0:cy1, cz0:cz1]

        return sdf

    @staticmethod
    def get_optimal_downsample_factor(
        shape: Tuple[int, int, int],
        target_voxels: int = 20_000_000,
    ) -> int:
        """Choose a downsample factor based on volume size."""
        _ = target_voxels
        total_voxels = int(np.prod(shape))

        if total_voxels > settings.SDF_VOXEL_THRESHOLD_LARGE:
            return 4
        if total_voxels > settings.SDF_VOXEL_THRESHOLD_MEDIUM:
            return 3
        if total_voxels > settings.SDF_VOXEL_THRESHOLD_SMALL:
            return 2
        return 1

    @staticmethod
    def normalize(sdf: np.ndarray, max_dist: float | None = None) -> np.ndarray:
        """Normalize SDF values to the [-1, 1] range."""
        if max_dist is None:
            max_dist = float(np.max(np.abs(sdf)))

        if max_dist > 0:
            return np.clip(sdf / max_dist, -1.0, 1.0)
        return sdf


def compute_sdf(mask: np.ndarray, spacing: Tuple[float, float, float] | None = None) -> np.ndarray:
    return SDFProcessor.compute(mask, spacing)


def compute_sdf_fast(mask: np.ndarray, spacing: Tuple[float, float, float] | None = None) -> np.ndarray:
    return SDFProcessor.compute_fast(mask, spacing)


def compute_sdf_downsampled(
    mask: np.ndarray,
    factor: int = 2,
    spacing: Tuple[float, float, float] | None = None,
) -> np.ndarray:
    return SDFProcessor.compute_downsampled(mask, factor=factor, spacing=spacing)


def compute_sdf_chunked(
    mask: np.ndarray,
    chunk_size: int = 128,
    overlap: int = 16,
    spacing: Tuple[float, float, float] | None = None,
) -> np.ndarray:
    return SDFProcessor.compute_chunked(
        mask,
        chunk_size=chunk_size,
        overlap=overlap,
        spacing=spacing,
    )


def get_optimal_downsample_factor(
    shape: Tuple[int, int, int],
    target_voxels: int = 20_000_000,
) -> int:
    return SDFProcessor.get_optimal_downsample_factor(shape, target_voxels=target_voxels)


def normalize_sdf(sdf: np.ndarray, max_dist: float | None = None) -> np.ndarray:
    return SDFProcessor.normalize(sdf, max_dist=max_dist)
