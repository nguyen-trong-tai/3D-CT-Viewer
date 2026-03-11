"""
GLB Converter Module

Converts trimesh meshes to Draco-compressed GLB (GLTF Binary) format.
This provides significant file size reduction (80-90%) while maintaining
compatibility with @react-three/drei's useGLTF hook.

Key features:
- Draco compression with configurable settings
- Normals preservation (calculated if missing)
- UV and vertex color preservation
"""

import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
import numpy as np
import trimesh

from config import settings


# Draco compression settings (recommended defaults)
DRACO_COMPRESSION_LEVEL = 7
DRACO_QUANTIZE_POSITION_BITS = 14
DRACO_QUANTIZE_NORMAL_BITS = 10
DRACO_QUANTIZE_TEXCOORD_BITS = 12
DRACO_QUANTIZE_COLOR_BITS = 8


def convert_mesh_to_glb(
    mesh: trimesh.Trimesh,
    output_path: Path,
    apply_draco: bool = True,
    compression_level: int = DRACO_COMPRESSION_LEVEL,
    quantize_position_bits: int = DRACO_QUANTIZE_POSITION_BITS,
    quantize_normal_bits: int = DRACO_QUANTIZE_NORMAL_BITS,
) -> Tuple[bool, str]:
    """
    Convert a trimesh mesh to Draco-compressed GLB format.
    
    This function first exports the mesh to GLTF/GLB using trimesh,
    then applies Draco compression using gltf-pipeline (if available)
    or falls back to trimesh's native GLB export.
    
    Args:
        mesh: Input trimesh.Trimesh object
        output_path: Path for the output .glb file
        apply_draco: Whether to apply Draco compression
        compression_level: Draco compression level (1-10)
        quantize_position_bits: Quantization bits for positions
        quantize_normal_bits: Quantization bits for normals
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    if len(mesh.vertices) == 0:
        return False, "Empty mesh - no vertices to convert"
    
    # Ensure normals are computed
    if mesh.vertex_normals is None or len(mesh.vertex_normals) == 0:
        mesh.fix_normals()
    
    # Attempt conversion with Draco compression
    if apply_draco:
        success, message = _convert_with_draco(
            mesh, output_path,
            compression_level=compression_level,
            quantize_position_bits=quantize_position_bits,
            quantize_normal_bits=quantize_normal_bits
        )
        if success:
            return success, message
        # If Draco fails, fall back to standard GLB
        print(f"[GLB] Draco compression unavailable, using standard GLB: {message}")
    
    # Fallback: Standard GLB export without Draco
    return _convert_to_standard_glb(mesh, output_path)


def _convert_with_draco(
    mesh: trimesh.Trimesh,
    output_path: Path,
    compression_level: int,
    quantize_position_bits: int,
    quantize_normal_bits: int,
) -> Tuple[bool, str]:
    """
    Convert mesh to GLB with Draco compression using gltf-pipeline.
    
    Requires Node.js and gltf-pipeline to be installed globally.
    """
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="glb_convert_"))
        
        # Step 1: Export to uncompressed GLB first
        temp_glb = temp_dir / "mesh_uncompressed.glb"
        mesh.export(str(temp_glb), file_type='glb')
        
        if not temp_glb.exists():
            return False, "Failed to export initial GLB"
        
        initial_size = temp_glb.stat().st_size
        
        # Step 2: Apply Draco compression using gltf-pipeline
        draco_cmd = [
            "npx", "-y", "gltf-pipeline",
            "-i", str(temp_glb),
            "-o", str(output_path),
            "--draco.compressionLevel", str(compression_level),
            "--draco.quantizePositionBits", str(quantize_position_bits),
            "--draco.quantizeNormalBits", str(quantize_normal_bits),
            "--draco.quantizeTexcoordBits", str(DRACO_QUANTIZE_TEXCOORD_BITS),
            "--draco.quantizeColorBits", str(DRACO_QUANTIZE_COLOR_BITS),
        ]
        
        result = subprocess.run(
            draco_cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
            shell=True if subprocess.sys.platform == 'win32' else False
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, f"gltf-pipeline failed: {error_msg}"
        
        if not output_path.exists():
            return False, "gltf-pipeline did not create output file"
        
        final_size = output_path.stat().st_size
        reduction = ((initial_size - final_size) / initial_size) * 100
        
        return True, f"Draco compressed: {initial_size/1024:.1f}KB → {final_size/1024:.1f}KB ({reduction:.1f}% reduction)"
        
    except FileNotFoundError:
        return False, "Node.js/npx not found - Draco compression requires Node.js"
    except subprocess.TimeoutExpired:
        return False, "gltf-pipeline timed out"
    except Exception as e:
        return False, f"Draco conversion error: {str(e)}"
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _convert_to_standard_glb(
    mesh: trimesh.Trimesh,
    output_path: Path
) -> Tuple[bool, str]:
    """
    Convert mesh to standard GLB format without Draco compression.
    
    This is the fallback when Node.js/gltf-pipeline is not available.
    """
    try:
        # Ensure normals are included
        if mesh.vertex_normals is None or len(mesh.vertex_normals) == 0:
            mesh.fix_normals()
        
        # Export to GLB using trimesh
        mesh.export(str(output_path), file_type='glb')
        
        if not output_path.exists():
            return False, "Failed to create GLB file"
        
        file_size = output_path.stat().st_size
        return True, f"Standard GLB export: {file_size/1024:.1f}KB (no Draco compression)"
        
    except Exception as e:
        return False, f"GLB export failed: {str(e)}"


def get_glb_stats(glb_path: Path) -> Optional[dict]:
    """
    Get statistics about a GLB file.
    
    Args:
        glb_path: Path to GLB file
        
    Returns:
        Dictionary with file stats or None if file doesn't exist
    """
    if not glb_path.exists():
        return None
    
    return {
        "path": str(glb_path),
        "size_bytes": glb_path.stat().st_size,
        "size_kb": glb_path.stat().st_size / 1024,
        "size_mb": glb_path.stat().st_size / (1024 * 1024),
    }


def compare_mesh_sizes(obj_path: Path, glb_path: Path) -> Optional[dict]:
    """
    Compare file sizes between OBJ and GLB formats.
    
    Useful for validating compression effectiveness.
    """
    if not obj_path.exists() or not glb_path.exists():
        return None
    
    obj_size = obj_path.stat().st_size
    glb_size = glb_path.stat().st_size
    
    reduction_pct = ((obj_size - glb_size) / obj_size) * 100 if obj_size > 0 else 0
    
    return {
        "obj_size_kb": obj_size / 1024,
        "glb_size_kb": glb_size / 1024,
        "reduction_percent": reduction_pct,
        "compression_ratio": obj_size / glb_size if glb_size > 0 else 0,
    }
