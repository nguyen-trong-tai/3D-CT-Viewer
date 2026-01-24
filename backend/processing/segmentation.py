"""
Segmentation Module

Implements CT volume segmentation for lung and tissue structures.
Uses thresholding-based approach for the initial version with
deterministic, reproducible results.
"""

import numpy as np
from scipy import ndimage
from typing import Tuple, Optional

from config import settings


def segment_volume_baseline(
    volume: np.ndarray,
    threshold: float = None
) -> np.ndarray:
    """
    Baseline segmentation using HU thresholding.
    
    This is a simple but effective approach for demonstrating
    the 3D reconstruction pipeline. It segments tissues above
    the specified threshold.
    
    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        threshold: HU threshold for segmentation (default: -600 for soft tissue)
        
    Returns:
        Binary mask (uint8), same shape as input
        
    Note:
        This is decision-support data, not clinical truth.
    """
    if threshold is None:
        threshold = settings.DEFAULT_TISSUE_THRESHOLD
    
    # Simple thresholding - fast and deterministic
    mask = (volume > threshold).astype(np.uint8)
    
    return mask


def segment_lung(volume: np.ndarray) -> np.ndarray:
    """
    Segment lung regions from CT volume.
    
    Uses HU thresholding with air detection:
    - Air in lungs: approximately -1000 to -300 HU
    - Connected component analysis to identify lung fields
    
    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        
    Returns:
        Binary mask of lung regions (uint8)
    """
    low_threshold = settings.DEFAULT_LUNG_THRESHOLD_LOW
    high_threshold = settings.DEFAULT_LUNG_THRESHOLD_HIGH
    
    # Create mask for lung HU range
    lung_mask = (
        (volume > low_threshold) & 
        (volume < high_threshold)
    ).astype(np.uint8)
    
    # Optional: fill holes and clean up with morphological operations
    # This is kept simple for speed and reproducibility
    
    return lung_mask


def segment_tissue(
    volume: np.ndarray,
    threshold: float = None
) -> np.ndarray:
    """
    Segment soft tissue regions from CT volume.
    
    Uses simple thresholding - tissue typically has HU > -300.
    
    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        threshold: HU threshold (default: -600)
        
    Returns:
        Binary mask of tissue (uint8)
    """
    if threshold is None:
        threshold = settings.DEFAULT_TISSUE_THRESHOLD
    
    return (volume > threshold).astype(np.uint8)


def segment_bone(volume: np.ndarray, threshold: float = 300.0) -> np.ndarray:
    """
    Segment bone structures from CT volume.
    
    Bone typically has HU > 300 (cortical bone > 700).
    
    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        threshold: HU threshold for bone (default: 300)
        
    Returns:
        Binary mask of bone (uint8)
    """
    return (volume > threshold).astype(np.uint8)


def segment_with_morphology(
    volume: np.ndarray,
    threshold: float,
    opening_size: int = 3,
    closing_size: int = 3,
    fill_holes: bool = True
) -> np.ndarray:
    """
    Segmentation with morphological post-processing.
    
    Applies morphological opening and closing to clean up
    the segmentation mask.
    
    Args:
        volume: CT volume in HU
        threshold: HU threshold
        opening_size: Structuring element size for opening
        closing_size: Structuring element size for closing
        fill_holes: Whether to fill holes in the mask
        
    Returns:
        Cleaned binary mask (uint8)
    """
    # Initial thresholding
    mask = (volume > threshold).astype(np.uint8)
    
    # Morphological opening (remove small noise)
    if opening_size > 0:
        struct = ndimage.generate_binary_structure(3, 1)
        mask = ndimage.binary_opening(mask, struct, iterations=opening_size)
    
    # Morphological closing (fill small gaps)
    if closing_size > 0:
        struct = ndimage.generate_binary_structure(3, 1)
        mask = ndimage.binary_closing(mask, struct, iterations=closing_size)
    
    # Fill holes
    if fill_holes:
        mask = ndimage.binary_fill_holes(mask)
    
    return mask.astype(np.uint8)


def get_largest_connected_component(mask: np.ndarray) -> np.ndarray:
    """
    Extract the largest connected component from a binary mask.
    
    Useful for isolating the main structure (e.g., body from table).
    
    Args:
        mask: Binary mask (uint8 or bool)
        
    Returns:
        Binary mask with only the largest component (uint8)
    """
    # Label connected components
    labeled, num_features = ndimage.label(mask)
    
    if num_features == 0:
        return mask.astype(np.uint8)
    
    # Find the largest component
    component_sizes = ndimage.sum(mask, labeled, range(1, num_features + 1))
    largest_label = np.argmax(component_sizes) + 1
    
    # Create mask for largest component only
    result = (labeled == largest_label).astype(np.uint8)
    
    return result


def compute_segmentation_stats(mask: np.ndarray, spacing: Tuple[float, float, float]) -> dict:
    """
    Compute statistics about a segmentation mask.
    
    Args:
        mask: Binary mask
        spacing: Voxel spacing in mm (sx, sy, sz)
        
    Returns:
        Dictionary with segmentation statistics
    """
    voxel_count = int(np.sum(mask > 0))
    voxel_volume_mm3 = spacing[0] * spacing[1] * spacing[2]
    volume_mm3 = voxel_count * voxel_volume_mm3
    volume_ml = volume_mm3 / 1000.0  # 1 ml = 1000 mm³
    
    # Find bounding box
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
