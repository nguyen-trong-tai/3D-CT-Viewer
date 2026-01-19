import numpy as np
import trimesh
from skimage.measure import marching_cubes
from typing import Tuple

def extract_mesh(sdf: np.ndarray, spacing: Tuple[float, float, float]) -> trimesh.Trimesh:
    """
    Extracts surface mesh using Marching Cubes on the SDF zero-level set.
    
    Constraints:
    - Use Marching Cubes
    - Scale geometry using voxel spacing
    - Output physical units (mm)
    """
    
    # Validate minimum volume size for marching cubes
    min_size = 2
    if any(dim < min_size for dim in sdf.shape):
        print(f"Warning: Volume too small for mesh extraction: {sdf.shape}. Need at least 2x2x2.")
        # Return a simple placeholder cube mesh
        return _create_placeholder_mesh(sdf.shape, spacing)
    
    # Marching cubes finds isosurface at level 0
    # Returns verts, faces, normals, values
    try:
        verts, faces, normals, values = marching_cubes(sdf, level=0.0)
    except (RuntimeError, ValueError) as e:
        # Fallback if no surface found (e.g. empty mask, or volume too small)
        print(f"Warning: Marching cubes failed: {e}. Returning placeholder mesh.")
        return _create_placeholder_mesh(sdf.shape, spacing)
        
    # Scale vertices by voxel spacing to convert Voxel Space -> Physical Space (mm)
    # Spacing is (Sx, Sy, Sz) matching the (X, Y, Z) axes of the volume
    verts_mm = verts * np.array(spacing)
    
    # Create Trimesh object
    mesh = trimesh.Trimesh(vertices=verts_mm, faces=faces, vertex_normals=normals)
    
    return mesh


def _create_placeholder_mesh(shape: tuple, spacing: Tuple[float, float, float]) -> trimesh.Trimesh:
    """
    Create a simple box mesh as a placeholder when the actual mesh cannot be generated.
    The box represents the bounding volume of the CT scan.
    """
    # Calculate physical dimensions
    dims = np.array(shape) * np.array(spacing)
    
    # Create a simple box centered at origin
    box = trimesh.creation.box(extents=dims if dims.sum() > 0 else [10, 10, 10])
    
    # Center at half the dimensions
    box.apply_translation(dims / 2 if dims.sum() > 0 else [5, 5, 5])
    
    return box
