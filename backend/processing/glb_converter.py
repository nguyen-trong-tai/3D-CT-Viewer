"""
GLB Converter Module

Converts trimesh meshes to GLB, optionally applying Draco compression.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Optional, Tuple

import trimesh

MeshLike = trimesh.Trimesh | trimesh.Scene


class GLBConverter:
    """Utilities for GLB export and Draco compression."""

    DRACO_COMPRESSION_LEVEL = 7
    DRACO_QUANTIZE_POSITION_BITS = 14
    DRACO_QUANTIZE_NORMAL_BITS = 10
    DRACO_QUANTIZE_TEXCOORD_BITS = 12
    DRACO_QUANTIZE_COLOR_BITS = 8

    @classmethod
    def convert_mesh_to_glb(
        cls,
        mesh: MeshLike,
        output_path: Path,
        apply_draco: bool = True,
        compression_level: int = DRACO_COMPRESSION_LEVEL,
        quantize_position_bits: int = DRACO_QUANTIZE_POSITION_BITS,
        quantize_normal_bits: int = DRACO_QUANTIZE_NORMAL_BITS,
    ) -> Tuple[bool, str]:
        """Convert a mesh to GLB, using Draco when available."""
        geometry = cls._iter_exportable_geometry(mesh)
        if not geometry:
            return False, "Empty mesh - no vertices to convert"

        for part in geometry:
            if part.vertex_normals is None or len(part.vertex_normals) == 0:
                part.fix_normals()

        if apply_draco:
            success, message = cls._convert_with_draco(
                mesh,
                output_path,
                compression_level=compression_level,
                quantize_position_bits=quantize_position_bits,
                quantize_normal_bits=quantize_normal_bits,
            )
            if success:
                return success, message
            print(f"[GLB] Draco compression unavailable, using standard GLB: {message}")

        return cls._convert_to_standard_glb(mesh, output_path)

    @classmethod
    def _convert_with_draco(
        cls,
        mesh: MeshLike,
        output_path: Path,
        compression_level: int,
        quantize_position_bits: int,
        quantize_normal_bits: int,
    ) -> Tuple[bool, str]:
        """Convert mesh to GLB with Draco compression via `gltf-pipeline`."""
        temp_dir: Path | None = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix="glb_convert_"))

            temp_glb = temp_dir / "mesh_uncompressed.glb"
            mesh.export(str(temp_glb), file_type="glb")
            if not temp_glb.exists():
                return False, "Failed to export initial GLB"

            initial_size = temp_glb.stat().st_size

            draco_cmd = [
                "npx",
                "-y",
                "gltf-pipeline",
                "-i",
                str(temp_glb),
                "-o",
                str(output_path),
                "--draco.compressionLevel",
                str(compression_level),
                "--draco.quantizePositionBits",
                str(quantize_position_bits),
                "--draco.quantizeNormalBits",
                str(quantize_normal_bits),
                "--draco.quantizeTexcoordBits",
                str(cls.DRACO_QUANTIZE_TEXCOORD_BITS),
                "--draco.quantizeColorBits",
                str(cls.DRACO_QUANTIZE_COLOR_BITS),
            ]

            result = subprocess.run(
                draco_cmd,
                capture_output=True,
                text=True,
                timeout=120,
                shell=True if sys.platform == "win32" else False,
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                return False, f"gltf-pipeline failed: {error_msg}"

            if not output_path.exists():
                return False, "gltf-pipeline did not create output file"

            final_size = output_path.stat().st_size
            reduction = ((initial_size - final_size) / initial_size) * 100
            return True, (
                f"Draco compressed: {initial_size / 1024:.1f}KB -> "
                f"{final_size / 1024:.1f}KB ({reduction:.1f}% reduction)"
            )

        except FileNotFoundError:
            return False, "Node.js/npx not found - Draco compression requires Node.js"
        except subprocess.TimeoutExpired:
            return False, "gltf-pipeline timed out"
        except Exception as exc:
            return False, f"Draco conversion error: {exc}"
        finally:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _convert_to_standard_glb(
        mesh: MeshLike,
        output_path: Path,
    ) -> Tuple[bool, str]:
        """Convert mesh to standard GLB without Draco compression."""
        try:
            for part in GLBConverter._iter_exportable_geometry(mesh):
                if part.vertex_normals is None or len(part.vertex_normals) == 0:
                    part.fix_normals()

            mesh.export(str(output_path), file_type="glb")
            if not output_path.exists():
                return False, "Failed to create GLB file"

            file_size = output_path.stat().st_size
            return True, f"Standard GLB export: {file_size / 1024:.1f}KB (no Draco compression)"
        except Exception as exc:
            return False, f"GLB export failed: {exc}"

    @staticmethod
    def _iter_exportable_geometry(mesh: MeshLike) -> list[trimesh.Trimesh]:
        """Return all non-empty Trimesh geometries contained in the export target."""
        if isinstance(mesh, trimesh.Scene):
            geometry = [
                part
                for part in mesh.geometry.values()
                if isinstance(part, trimesh.Trimesh)
                and len(part.vertices) > 0
                and len(part.faces) > 0
            ]
            return geometry

        if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            return []
        return [mesh]

    @staticmethod
    def get_glb_stats(glb_path: Path) -> Optional[dict]:
        """Get basic file stats about a GLB artifact."""
        if not glb_path.exists():
            return None

        size_bytes = glb_path.stat().st_size
        return {
            "path": str(glb_path),
            "size_bytes": size_bytes,
            "size_kb": size_bytes / 1024,
            "size_mb": size_bytes / (1024 * 1024),
        }

    @staticmethod
    def compare_mesh_sizes(obj_path: Path, glb_path: Path) -> Optional[dict]:
        """Compare file sizes between OBJ and GLB artifacts."""
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


def convert_mesh_to_glb(
    mesh: MeshLike,
    output_path: Path,
    apply_draco: bool = True,
    compression_level: int = GLBConverter.DRACO_COMPRESSION_LEVEL,
    quantize_position_bits: int = GLBConverter.DRACO_QUANTIZE_POSITION_BITS,
    quantize_normal_bits: int = GLBConverter.DRACO_QUANTIZE_NORMAL_BITS,
) -> Tuple[bool, str]:
    return GLBConverter.convert_mesh_to_glb(
        mesh,
        output_path,
        apply_draco=apply_draco,
        compression_level=compression_level,
        quantize_position_bits=quantize_position_bits,
        quantize_normal_bits=quantize_normal_bits,
    )


def get_glb_stats(glb_path: Path) -> Optional[dict]:
    return GLBConverter.get_glb_stats(glb_path)


def compare_mesh_sizes(obj_path: Path, glb_path: Path) -> Optional[dict]:
    return GLBConverter.compare_mesh_sizes(obj_path, glb_path)
