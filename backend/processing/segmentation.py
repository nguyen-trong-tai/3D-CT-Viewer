"""
Segmentation Module

Implements deterministic threshold-based segmentation utilities for CT volumes.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy import ndimage

from config import settings


def segment_volume_baseline(
    volume: np.ndarray,
    threshold: float | None = None,
) -> np.ndarray:
    """
    Segment the input CT volume using a simple HU threshold plus light cleanup.

    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        threshold: HU threshold for segmentation (default: tissue threshold from settings)

    Returns:
        Binary mask (uint8), same shape as input
    """
    if threshold is None:
        threshold = settings.DEFAULT_TISSUE_THRESHOLD

    print(f"[Segmentation] Running baseline threshold at {threshold} HU")
    mask = (volume > threshold).astype(np.uint8)
    mask = get_largest_connected_component(mask)
    mask = segment_with_morphology(mask, threshold=0, opening_size=2, closing_size=2)
    return mask


def segment_lung(volume: np.ndarray) -> np.ndarray:
    """
    Segment lung-like air regions using the configured HU range.

    Args:
        volume: CT volume in HU, shape (X, Y, Z)

    Returns:
        Binary mask of lung regions (uint8)
    """
    low_threshold = settings.DEFAULT_LUNG_THRESHOLD_LOW
    high_threshold = settings.DEFAULT_LUNG_THRESHOLD_HIGH
    lung_mask = ((volume > low_threshold) & (volume < high_threshold)).astype(np.uint8)
    return lung_mask


def segment_tissue(
    volume: np.ndarray,
    threshold: float | None = None,
) -> np.ndarray:
    """
    Segment soft tissue using a basic HU threshold.

    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        threshold: HU threshold (default: tissue threshold from settings)

    Returns:
        Binary mask of tissue (uint8)
    """
    if threshold is None:
        threshold = settings.DEFAULT_TISSUE_THRESHOLD
    return (volume > threshold).astype(np.uint8)


def segment_bone(volume: np.ndarray, threshold: float = 300.0) -> np.ndarray:
    """
    Segment bone using a fixed HU threshold.

    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        threshold: HU threshold for bone

    Returns:
        Binary mask of bone (uint8)
    """
    return (volume > threshold).astype(np.uint8)


def segment_with_morphology(
    volume: np.ndarray,
    threshold: float,
    opening_size: int = 3,
    closing_size: int = 3,
    fill_holes: bool = True,
) -> np.ndarray:
    """
    Segment a volume with morphological cleanup operations.

    Args:
        volume: Input volume or mask
        threshold: Threshold applied before morphological cleanup
        opening_size: Structuring element size for opening
        closing_size: Structuring element size for closing
        fill_holes: Whether to fill holes in the mask

    Returns:
        Cleaned binary mask (uint8)
    """
    mask = (volume > threshold).astype(np.uint8)

    if opening_size > 0:
        struct = ndimage.generate_binary_structure(3, 1)
        mask = ndimage.binary_opening(mask, struct, iterations=opening_size)

    if closing_size > 0:
        struct = ndimage.generate_binary_structure(3, 1)
        mask = ndimage.binary_closing(mask, struct, iterations=closing_size)

    if fill_holes:
        mask = ndimage.binary_fill_holes(mask)

    return mask.astype(np.uint8)


def get_largest_connected_component(mask: np.ndarray) -> np.ndarray:
    """
    Extract the largest connected component from a binary mask.

    Args:
        mask: Binary mask (uint8 or bool)

    Returns:
        Binary mask with only the largest component (uint8)
    """
    labeled, num_features = ndimage.label(mask)
    if num_features == 0:
        return mask.astype(np.uint8)

    component_sizes = ndimage.sum(mask, labeled, range(1, num_features + 1))
    largest_label = np.argmax(component_sizes) + 1
    return (labeled == largest_label).astype(np.uint8)


def compute_segmentation_stats(mask: np.ndarray, spacing: Tuple[float, float, float]) -> dict:
    """
    Compute basic statistics about a segmentation mask.

    Args:
        mask: Binary mask
        spacing: Voxel spacing in mm (sx, sy, sz)

    Returns:
        Dictionary with segmentation statistics
    """
    voxel_count = int(np.sum(mask > 0))
    voxel_volume_mm3 = spacing[0] * spacing[1] * spacing[2]
    volume_mm3 = voxel_count * voxel_volume_mm3
    volume_ml = volume_mm3 / 1000.0

    if voxel_count > 0:
        coords = np.where(mask > 0)
        bbox_min = [int(np.min(c)) for c in coords]
        bbox_max = [int(np.max(c)) for c in coords]
    else:
        bbox_min = [0, 0, 0]
        bbox_max = [0, 0, 0]

    return {
        "voxel_count": voxel_count,
        "volume_mm3": volume_mm3,
        "volume_ml": volume_ml,
        "bounding_box_min": bbox_min,
        "bounding_box_max": bbox_max,
        "voxel_spacing_mm": list(spacing),
    }
