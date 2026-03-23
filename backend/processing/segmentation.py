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

import os
try:
    import torch
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
try:
    from totalsegmentator.python_api import totalsegmentator as _totalseg_fn

    #from totalsegmentator.python_api import totalsegmentator
    import nibabel as nib
    TOTALSEG_AVAILABLE = True
except ImportError:
    TOTALSEG_AVAILABLE = False
_loaded_tasks: set[str] = set()   # track task nào đã warm

def _warmup_task(task: str):
    """
    Sau lần đầu, TotalSegmentator cache model nội bộ.
    """
    if task in _loaded_tasks:
        return  # Đã load rồi, bỏ qua

    print(f"[TotalSeg] Warming up task '{task}'...")
    dummy = nib.Nifti1Image(
        np.zeros((64, 64, 64), dtype=np.float32), np.eye(4)
    )
    try:
        _totalseg_fn(dummy, task=task, quiet=True)
    except Exception:
        pass  # Bỏ qua lỗi inference — chỉ cần model được load

    _loaded_tasks.add(task)
    print(f"[TotalSeg] Task '{task}' warmed up — model in VRAM.")

def segment_volume_baseline(
    volume: np.ndarray,
    threshold: float = None,
    use_ai: bool = False,
    model_path: str = None
) -> np.ndarray:
    """
    Args:
        volume: CT volume in HU, shape (X, Y, Z)
        threshold: HU threshold for segmentation (default: -600 for soft tissue)
        use_ai: Cờ bật chế độ AI segmentation thay cho threshold
        model_path: Đường dẫn tới pre-trained model checkpoint (.pth)
        
    Returns:
        Binary mask (uint8), same shape as input
        
    Note:
        This is decision-support data, not clinical truth.
    """
    if use_ai:
        print("[Segmentation] Sử dụng AI Model pretrained thay cho Threshold...")
        return segment_volume_pretrained_ai(volume, model_path)
        
    if threshold is None:
        threshold = settings.DEFAULT_TISSUE_THRESHOLD
    
    # Simple thresholding - fast and deterministic
    print(f"[Segmentation] Đoạn này phân vùng bằng Threshold cơ bản: {threshold} HU")
    mask = (volume > threshold).astype(np.uint8)
    
    return mask


def segment_volume_total_segmentator(
    volume: np.ndarray,
    task: str = "total",
    spacing: tuple = (1.0, 1.0, 1.0)
) -> np.ndarray:
    """
    segmentation AI siêu tốc bằng TotalSegmentator 
    """
    if not TOTALSEG_AVAILABLE:
        raise ImportError("Chưa cài đặt TotalSegmentator. Hãy chạy: pip install TotalSegmentator")
    os.environ["TOTALSEG_HOME_DIR"] = os.environ.get("TOTALSEG_HOME_DIR", "")

    # Đảm bảo model đã warm trước khi inference thật
    _warmup_task(task)
    print(f"[AI Segmentation] segment bằng TotalSegmentator (Task: {task})...")
    affine = np.diag([spacing[0], spacing[1], spacing[2], 1.0])
    dummy_nifti = nib.Nifti1Image(volume, affine)
    
    # Suy luận nhanh
    seg_nifti = _totalseg_fn(dummy_nifti, task=task)
    mask = seg_nifti.get_fdata()
    
    return mask

def segment_lung_nodules_ai(volume: np.ndarray, spacing: tuple = (1.0, 1.0, 1.0)) -> np.ndarray:
    """
    Args:
        volume: CT volume array (HU chuẩn).
        spacing: Spacing of the volume (default: (1.0, 1.0, 1.0)).
    Returns:
        Binary mask (uint8) với label 1 là Nodule.
    """
    # 1. Dự đoán bằng TotalSegmentator
    mask_multiclass = segment_volume_total_segmentator(volume, task="lung_nodules", spacing=spacing)
    
    # 2. Xử lý Trích xuất Nhãn
    # lung_mask  = (mask_multiclass == 1).astype(np.uint8)
    nodule_mask = (mask_multiclass == 1).astype(np.uint8)
    # 3. Post-Process & Debugging Analysis
    nodule_voxels = np.sum(nodule_mask > 0)
    if nodule_voxels == 0:
        print("[AI Segmentation] KHÔNG tìm thấy bất kỳ nốt sần phổi nào trong thể tích này.")
    else:
        print(f"[AI Segmentation] Thành công. Tìm thấy {nodule_voxels:,} voxels thuộc về nốt sần.")
    
    return nodule_mask

def segment_lung(volume: np.ndarray) -> np.ndarray:
    """
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
    return lung_mask


def segment_tissue(
    volume: np.ndarray,
    threshold: float = None
) -> np.ndarray:
    """
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
