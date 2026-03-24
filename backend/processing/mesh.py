"""
Mesh Generation Module
"""

import numpy as np
import trimesh
from skimage.measure import marching_cubes
from typing import Tuple, Optional

from config import settings


def get_optimal_mesh_step_size(shape: Tuple[int, int, int]) -> int:
    """Choose a coarser marching-cubes step size for large volumes."""
    total_voxels = int(np.prod(shape))

    if total_voxels > settings.SDF_VOXEL_THRESHOLD_LARGE:
        return max(1, settings.MESH_STEP_SIZE_HUGE)
    if total_voxels > settings.SDF_VOXEL_THRESHOLD_MEDIUM:
        return max(1, settings.MESH_STEP_SIZE_LARGE)
    if total_voxels > settings.SDF_VOXEL_THRESHOLD_SMALL:
        return max(1, settings.MESH_STEP_SIZE_MEDIUM)
    return 1


def extract_mesh(
    sdf: np.ndarray,
    spacing: Tuple[float, float, float],
    level: float = None,
    step_size: int | None = None
) -> trimesh.Trimesh:
    """
    Args:
        sdf: Signed Distance Function volume
        spacing: Voxel spacing (sx, sy, sz) in mm
        level: Iso-surface level (default: 0.0 for SDF zero crossing)
        step_size: Step size for marching cubes (larger = faster but coarser)
        
    Returns:
        Trimesh object with vertices in physical coordinates (mm)
    """
    if level is None:
        level = settings.MESH_LEVEL_SET
    if step_size is None:
        step_size = get_optimal_mesh_step_size(sdf.shape)
    step_size = max(1, int(step_size))
    
    # Validate minimum volume size for marching cubes
    min_size = 2
    if any(dim < min_size for dim in sdf.shape):
        print(f"Warning: Volume too small for mesh extraction: {sdf.shape}")
        return _create_placeholder_mesh(sdf.shape, spacing)
    
    # Check if there's actually a surface to extract
    has_inside = np.any(sdf < level)
    has_outside = np.any(sdf > level)
    
    if not (has_inside and has_outside):
        print(f"Warning: No surface crossing found at level {level}")
        return _create_placeholder_mesh(sdf.shape, spacing)
    
    try:
        # Marching cubes extracts the iso-surface
        vertices, faces, normals, values = marching_cubes(
            sdf,
            level=level,
            step_size=step_size,
            allow_degenerate=False
        )
    except (RuntimeError, ValueError) as e:
        print(f"Warning: Marching cubes failed: {e}")
        return _create_placeholder_mesh(sdf.shape, spacing)
    
    if len(vertices) == 0 or len(faces) == 0:
        print("Warning: Empty mesh generated")
        return _create_placeholder_mesh(sdf.shape, spacing)
    
    # Scale vertices by voxel spacing to convert to physical coordinates
    # Vertices are in voxel indices, multiply by spacing to get mm
    spacing_array = np.array(spacing)
    vertices_mm = vertices * spacing_array
    
    # Create trimesh object
    mesh = trimesh.Trimesh(
        vertices=vertices_mm,
        faces=faces,
        vertex_normals=normals,
        process=False  # Don't process to preserve vertex ordering
    )
    
    return mesh


def extract_mesh_from_mask(
    mask: np.ndarray,
    spacing: Tuple[float, float, float],
    smoothing_iterations: int = 0
) -> trimesh.Trimesh:
    """
    Extract mesh directly from a binary mask.
    
    This is a convenience function that computes the SDF internally
    and then extracts the mesh.
    
    Args:
        mask: Binary segmentation mask
        spacing: Voxel spacing in mm
        smoothing_iterations: Number of Laplacian smoothing iterations
        
    Returns:
        Trimesh object
    """
    from . import sdf as sdf_module
    
    # Compute SDF
    sdf_volume = sdf_module.compute_sdf(mask)
    
    # Extract mesh
    mesh = extract_mesh(sdf_volume, spacing)
    
    # Optional smoothing
    if smoothing_iterations > 0 and len(mesh.vertices) > 0:
        mesh = smooth_mesh_laplacian(mesh, iterations=smoothing_iterations)
    
    return mesh


def smooth_mesh_laplacian(
    mesh: trimesh.Trimesh,
    iterations: int = 3,
    lamb: float = 0.5
) -> trimesh.Trimesh:
    """
    Apply Laplacian smoothing to a mesh.
    
    Note: This is kept minimal as the PRD specifies avoiding
    aggressive smoothing for aesthetic purposes.
    
    Args:
        mesh: Input mesh
        iterations: Number of smoothing iterations
        lamb: Smoothing factor (0-1, higher = more smoothing)
        
    Returns:
        Smoothed mesh
    """
    if len(mesh.vertices) == 0:
        return mesh
    
    # Use trimesh's built-in smoothing if available
    try:
        smoothed = mesh.copy()
        trimesh.smoothing.filter_laplacian(
            smoothed,
            lamb=lamb,
            iterations=iterations
        )
        return smoothed
    except Exception:
        # Return original if smoothing fails
        return mesh


def decimate_mesh(
    mesh: trimesh.Trimesh,
    target_faces: int = None,
    reduction_ratio: float = None
) -> trimesh.Trimesh:
    """
    Reduce mesh complexity while preserving shape.
    
    Args:
        mesh: Input mesh
        target_faces: Target number of faces
        reduction_ratio: Ratio of faces to keep (0-1)
        
    Returns:
        Decimated mesh
    """
    if len(mesh.faces) == 0:
        return mesh
    
    current_faces = len(mesh.faces)
    
    if target_faces is not None:
        ratio = target_faces / current_faces
    elif reduction_ratio is not None:
        ratio = reduction_ratio
    else:
        return mesh
    
    if ratio >= 1.0:
        return mesh
    
    # Use trimesh's simplification
    try:
        simplified = mesh.simplify_quadric_decimation(int(current_faces * ratio))
        return simplified
    except Exception:
        return mesh


def compute_mesh_stats(mesh: trimesh.Trimesh) -> dict:
    """
    Compute statistics about a mesh.
    
    Args:
        mesh: Input mesh
        
    Returns:
        Dictionary with mesh statistics
    """
    if len(mesh.vertices) == 0:
        return {
            "vertex_count": 0,
            "face_count": 0,
            "is_watertight": False,
            "volume_mm3": 0.0,
            "surface_area_mm2": 0.0,
        }
    
    stats = {
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.faces),
        "is_watertight": mesh.is_watertight,
    }
    
    # Bounds
    bounds = mesh.bounds
    stats["bounds_min_mm"] = bounds[0].tolist()
    stats["bounds_max_mm"] = bounds[1].tolist()
    stats["extents_mm"] = mesh.extents.tolist()
    
    # Volume and surface area (only for watertight meshes)
    if mesh.is_watertight:
        stats["volume_mm3"] = float(mesh.volume)
        stats["volume_ml"] = stats["volume_mm3"] / 1000.0
    else:
        stats["volume_mm3"] = None
        stats["volume_ml"] = None
    
    stats["surface_area_mm2"] = float(mesh.area)
    
    # Centroid
    stats["centroid_mm"] = mesh.centroid.tolist()
    
    return stats


def export_mesh(mesh: trimesh.Trimesh, format: str = "obj") -> bytes:
    """
    Export mesh to bytes in the specified format.
    
    Args:
        mesh: Input mesh
        format: Output format ('obj', 'stl', 'ply', 'glb', 'gltf')
        
    Returns:
        Mesh data as bytes
    """
    return mesh.export(file_type=format)


def _create_placeholder_mesh(
    shape: Tuple[int, int, int],
    spacing: Tuple[float, float, float]
) -> trimesh.Trimesh:
    """
    Create a simple box mesh as a placeholder.
    
    Used when actual mesh extraction fails or volume is too small.
    The box represents the bounding volume of the CT scan.
    
    Args:
        shape: Volume shape in voxels
        spacing: Voxel spacing in mm
        
    Returns:
        A simple box mesh
    """
    # Calculate physical dimensions
    dims = np.array(shape) * np.array(spacing)
    
    # Ensure minimum size
    min_dim = 10.0  # mm
    dims = np.maximum(dims, min_dim)
    
    # Create centered box
    box = trimesh.creation.box(extents=dims)
    
    # Translate to center it at half the dimensions
    # (so it's positioned at the center of the volume)
    box.apply_translation(dims / 2)
    
    return box


def combine_meshes(meshes: list) -> trimesh.Trimesh:
    """
    Combine multiple meshes into a single mesh.
    
    Args:
        meshes: List of Trimesh objects
        
    Returns:
        Combined mesh
    """
    if not meshes:
        return trimesh.Trimesh()
    
    if len(meshes) == 1:
        return meshes[0]
    
    return trimesh.util.concatenate(meshes)
