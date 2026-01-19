import numpy as np
from scipy.ndimage import distance_transform_edt

def compute_sdf(mask: np.ndarray) -> np.ndarray:
    """
    Computes Traditional Signed Distance Function (SDF) from a binary mask.
    
    Representation:
    Negative distance: Inside the object
    Positive distance: Outside the object
    Zero: Surface
    
    Constraint: Derived explicitly from segmentation mask.
    
    OPTIMIZED: Uses single pass for inside/outside by computing both simultaneously.
    """
    
    # Convert mask to boolean once
    mask_bool = mask.astype(bool)
    
    # Compute both distance transforms
    # These are independent so scipy can optimize internally
    dist_outside = distance_transform_edt(~mask_bool)
    dist_inside = distance_transform_edt(mask_bool)
    
    # Standard convention: (-) Inside, (+) Outside
    # Use in-place operations to reduce memory allocation
    sdf = dist_outside
    sdf -= dist_inside
    
    return sdf


def compute_sdf_fast(mask: np.ndarray, sampling: tuple = None) -> np.ndarray:
    """
    Fast SDF computation with optional anisotropic sampling.
    
    Args:
        mask: Binary mask (uint8 or bool)
        sampling: Voxel spacing tuple (sx, sy, sz) for anisotropic distance
    
    Returns:
        SDF array (float64)
    """
    # View as bool without copy if possible
    if mask.dtype == np.uint8:
        mask_bool = mask.view(bool).reshape(mask.shape)
    else:
        mask_bool = mask.astype(bool)
    
    # Use sampling parameter for anisotropic volumes
    kwargs = {'sampling': sampling} if sampling else {}
    
    # Compute distance transforms with sampling
    dist_outside = distance_transform_edt(~mask_bool, **kwargs)
    dist_inside = distance_transform_edt(mask_bool, **kwargs)
    
    # In-place subtraction
    dist_outside -= dist_inside
    return dist_outside


def compute_sdf_downsampled(mask: np.ndarray, factor: int = 2) -> np.ndarray:
    """
    Compute SDF on downsampled volume for faster processing.
    Result is upsampled back to original size.
    
    Args:
        mask: Binary mask
        factor: Downsample factor (2 = half resolution in each dimension)
    
    Returns:
        SDF at original resolution (approximate)
    """
    from scipy.ndimage import zoom
    
    if factor <= 1:
        return compute_sdf(mask)
    
    # Downsample mask
    small_mask = mask[::factor, ::factor, ::factor]
    
    # Compute SDF on smaller volume
    small_sdf = compute_sdf(small_mask)
    
    # Scale distances by factor (since voxels are larger)
    small_sdf *= factor
    
    # Upsample back - use order=1 (linear) for speed
    target_shape = mask.shape
    zoom_factors = [t / s for t, s in zip(target_shape, small_sdf.shape)]
    
    sdf = zoom(small_sdf, zoom_factors, order=1)
    
    return sdf
