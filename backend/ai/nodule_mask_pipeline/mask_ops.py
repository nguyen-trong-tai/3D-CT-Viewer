from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from scipy import ndimage


def resolve_seed_and_support_thresholds(seed_threshold: float, support_threshold: float) -> tuple[float, float]:
    seed = float(seed_threshold)
    support = float(min(seed, max(float(support_threshold), seed * 0.5)))
    return seed, support


def dilate_mask(mask_xyz: np.ndarray, iterations: int) -> np.ndarray:
    mask = np.asarray(mask_xyz, dtype=bool)
    if iterations <= 0 or not mask.any():
        return mask
    structure = ndimage.generate_binary_structure(3, 1)
    return ndimage.binary_dilation(mask, structure=structure, iterations=int(iterations))


def fill_mask_holes_per_slice(mask_xyz: np.ndarray) -> np.ndarray:
    filled = np.asarray(mask_xyz, dtype=bool).copy()
    if not filled.any():
        return filled
    
    # Optimize by extracting the bounding box containing the nodule
    coords = np.where(filled)
    bbox = tuple(slice(np.min(c), np.max(c) + 1) for c in coords)
    cropped = filled[bbox]
    
    # 1. 3D fill for fully enclosed cavities (runs instantly on small cropped region)
    cropped = ndimage.binary_fill_holes(cropped)
    
    # 2. 2D fill per slice for open cavities
    for z in range(cropped.shape[2]):
        if cropped[:, :, z].any():
            cropped[:, :, z] = ndimage.binary_fill_holes(cropped[:, :, z])
            
    # Put the filled crop back into the original volume
    filled[bbox] = cropped
    return filled


def compute_minimum_component_voxels(
    min_component_volume_mm3: float,
    spacing_xyz: Iterable[float],
) -> int:
    voxel_volume_mm3 = float(np.prod(np.asarray(tuple(float(value) for value in spacing_xyz), dtype=np.float32)))
    return max(1, int(math.ceil(float(min_component_volume_mm3) / max(voxel_volume_mm3, 1e-6))))

