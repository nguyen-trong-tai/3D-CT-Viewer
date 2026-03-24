"""
Signed Distance Function (SDF) Module

Computes implicit surface representations from binary segmentation masks.
The SDF enables smooth surface extraction via Marching Cubes.
"""

import numpy as np
from scipy.ndimage import distance_transform_edt, zoom
from typing import Tuple, Optional

from config import settings


def compute_sdf(mask: np.ndarray, spacing: Tuple[float, float, float] = None) -> np.ndarray:
    """
    Compute Signed Distance Function (SDF) from a binary mask.
    
    The SDF represents the distance to the surface at each point:
    - Negative values: Inside the object
    - Positive values: Outside the object
    - Zero: On the surface
    
    This is a traditional Euclidean distance-based SDF that produces
    deterministic, reproducible results.
    
    Args:
        mask: Binary segmentation mask (uint8 or bool)
        spacing: Optional voxel spacing (sx, sy, sz) for anisotropic volumes.
                 If provided, distances are computed in physical units (mm).
        
    Returns:
        SDF array (float64), same shape as input
    """
    # Convert to boolean
    mask_bool = mask.astype(bool)
    
    # Prepare kwargs for distance transform
    kwargs = {}
    if spacing is not None:
        kwargs['sampling'] = spacing
    
    # Compute distance from outside (positive outside)
    dist_outside = distance_transform_edt(~mask_bool, **kwargs)
    
    # Compute distance from inside (will be negative inside)
    dist_inside = distance_transform_edt(mask_bool, **kwargs)
    
    # Combine: positive outside, negative inside
    # Convention: SDF(x) = dist_to_surface, negative if inside
    sdf = dist_outside - dist_inside
    
    return sdf


def compute_sdf_fast(mask: np.ndarray, spacing: Tuple[float, float, float] = None) -> np.ndarray:
    """
    Fast SDF computation with memory-efficient operations.
    
    Uses in-place operations where possible to reduce memory allocation overhead.
    
    Args:
        mask: Binary mask (uint8 or bool)
        spacing: Optional voxel spacing for anisotropic volumes
        
    Returns:
        SDF array (float64)
    """
    # View as bool without copy if possible
    if mask.dtype == np.uint8:
        # Create a view - this doesn't copy data
        mask_bool = mask.view(bool).reshape(mask.shape)
    else:
        mask_bool = mask.astype(bool)
    
    kwargs = {'sampling': spacing} if spacing else {}
    
    # Compute outside distance first (will be modified in place)
    sdf = distance_transform_edt(~mask_bool, **kwargs)
    
    # Compute inside distance and subtract in place
    dist_inside = distance_transform_edt(mask_bool, **kwargs)
    np.subtract(sdf, dist_inside, out=sdf)
    
    return sdf


def compute_sdf_downsampled(
    mask: np.ndarray,
    factor: int = 2,
    spacing: Tuple[float, float, float] = None
) -> np.ndarray:
    """
    Compute SDF on a downsampled volume for faster processing.
    
    The result is upsampled back to the original resolution.
    This trades some accuracy for significant speed improvement
    on large volumes.
    
    Args:
        mask: Binary mask
        factor: Downsample factor (2 = half resolution in each dimension)
        spacing: Optional voxel spacing
        
    Returns:
        SDF at original resolution (approximate)
    """
    if factor <= 1:
        return compute_sdf_fast(mask, spacing)
    
    # Downsample mask using slicing (fastest method)
    small_mask = mask[::factor, ::factor, ::factor]
    
    # Adjust spacing for downsampled volume
    small_spacing = None
    if spacing is not None:
        small_spacing = tuple(s * factor for s in spacing)
    
    # Compute SDF on smaller volume
    small_sdf = compute_sdf_fast(small_mask, small_spacing)
    
    # Scale distances by factor (voxels are larger)
    if spacing is None:
        # If no physical spacing, scale by voxel factor
        small_sdf *= factor
    
    # Upsample back to original size using linear interpolation
    target_shape = mask.shape
    zoom_factors = [t / s for t, s in zip(target_shape, small_sdf.shape)]
    
    # Use order=1 (linear) for speed, order=3 (cubic) for accuracy
    sdf = zoom(small_sdf, zoom_factors, order=1)
    
    return sdf


def compute_sdf_chunked(
    mask: np.ndarray,
    chunk_size: int = 128,
    overlap: int = 16,
    spacing: Tuple[float, float, float] = None
) -> np.ndarray:
    """
    Compute SDF in chunks for very large volumes.
    
    This approach handles volumes that don't fit in memory by
    processing them in overlapping chunks.
    
    Args:
        mask: Binary mask
        chunk_size: Size of each chunk
        overlap: Overlap between chunks to avoid boundary artifacts
        spacing: Optional voxel spacing
        
    Returns:
        SDF array (float32 to save memory)
    """
    shape = mask.shape
    sdf = np.zeros(shape, dtype=np.float32)
    
    # Process in chunks along each axis
    for z0 in range(0, shape[2], chunk_size - overlap):
        z1 = min(z0 + chunk_size, shape[2])
        
        for y0 in range(0, shape[1], chunk_size - overlap):
            y1 = min(y0 + chunk_size, shape[1])
            
            for x0 in range(0, shape[0], chunk_size - overlap):
                x1 = min(x0 + chunk_size, shape[0])
                
                # Extract chunk with padding
                chunk = mask[x0:x1, y0:y1, z0:z1]
                
                # Compute SDF for chunk
                chunk_sdf = compute_sdf(chunk, spacing)
                
                # Blend into result (use center region to avoid boundary artifacts)
                cx0 = overlap // 2 if x0 > 0 else 0
                cy0 = overlap // 2 if y0 > 0 else 0
                cz0 = overlap // 2 if z0 > 0 else 0
                cx1 = x1 - x0 - (overlap // 2 if x1 < shape[0] else 0)
                cy1 = y1 - y0 - (overlap // 2 if y1 < shape[1] else 0)
                cz1 = z1 - z0 - (overlap // 2 if z1 < shape[2] else 0)
                
                sdf[
                    x0 + cx0:x0 + cx1,
                    y0 + cy0:y0 + cy1,
                    z0 + cz0:z0 + cz1
                ] = chunk_sdf[cx0:cx1, cy0:cy1, cz0:cz1]
    
    return sdf


def get_optimal_downsample_factor(
    shape: Tuple[int, int, int],
    target_voxels: int = 20_000_000
) -> int:
    """
    Determine the optimal downsample factor based on volume size.
    
    Args:
        shape: Volume shape (X, Y, Z)
        target_voxels: Target number of voxels after downsampling
        
    Returns:
        Recommended downsample factor (1, 2, 3, or 4)
    """
    total_voxels = shape[0] * shape[1] * shape[2]
    
    if total_voxels > settings.SDF_VOXEL_THRESHOLD_LARGE:
        return 4
    elif total_voxels > settings.SDF_VOXEL_THRESHOLD_MEDIUM:
        return 3
    elif total_voxels > settings.SDF_VOXEL_THRESHOLD_SMALL:
        return 2
    else:
        return 1


def normalize_sdf(sdf: np.ndarray, max_dist: float = None) -> np.ndarray:
    """
    Normalize SDF values to [-1, 1] range.
    
    Useful for neural network training or visualization.
    
    Args:
        sdf: Input SDF
        max_dist: Maximum distance for normalization. 
                  If None, uses the maximum absolute value in the SDF.
        
    Returns:
        Normalized SDF in [-1, 1] range
    """
    if max_dist is None:
        max_dist = np.max(np.abs(sdf))
    
    if max_dist > 0:
        return np.clip(sdf / max_dist, -1.0, 1.0)
    else:
        return sdf
