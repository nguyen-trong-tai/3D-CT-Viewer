import numpy as np
from scipy import ndimage

def segment_volume_baseline(volume: np.ndarray, downsample: int = 1) -> np.ndarray:
    """
    Baseline segmentation for high-density structures (e.g. bone).
    Used for demonstrating 3D reconstruction pipeline.
    
    Args:
        volume: CT volume in HU
        downsample: Factor to downsample volume for faster processing (1 = no downsample)
    
    Returns:
        Binary mask (uint8)
    """
    
    # Downsample if requested (for faster processing)
    if downsample > 1:
        volume = volume[::downsample, ::downsample, ::downsample]
    
    # Threshold for tissue (lung tumor threshold)
    # Using numpy's vectorized operation - already fast
    mask = (volume > -600).astype(np.uint8)
    
    return mask


def segment_volume_fast(volume: np.ndarray, threshold: float = -600) -> np.ndarray:
    """
    Fast segmentation using numpy vectorization only.
    No scipy overhead for simple thresholding.
    """
    return (volume > threshold).view(np.uint8)
