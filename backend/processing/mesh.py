"""
Mesh Generation Module
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from skimage.measure import marching_cubes
import trimesh

from config import settings
from .sdf import SDFProcessor


class MeshProcessor:
    """Utilities for surface extraction, smoothing, and mesh statistics."""

    @staticmethod
    def get_optimal_step_size(shape: Tuple[int, int, int]) -> int:
        """Choose a coarser marching-cubes step size for large volumes."""
        total_voxels = int(np.prod(shape))

        if total_voxels > settings.SDF_VOXEL_THRESHOLD_LARGE:
            return max(1, settings.MESH_STEP_SIZE_HUGE)
        if total_voxels > settings.SDF_VOXEL_THRESHOLD_MEDIUM:
            return max(1, settings.MESH_STEP_SIZE_LARGE)
        if total_voxels > settings.SDF_VOXEL_THRESHOLD_SMALL:
            return max(1, settings.MESH_STEP_SIZE_MEDIUM)
        return 1

    @classmethod
    def extract_mesh(
        cls,
        sdf: np.ndarray,
        spacing: Tuple[float, float, float],
        level: float | None = None,
        step_size: int | None = None,
    ) -> trimesh.Trimesh:
        """Extract an iso-surface mesh from an SDF volume."""
        if level is None:
            level = settings.MESH_LEVEL_SET
        if step_size is None:
            step_size = cls.get_optimal_step_size(sdf.shape)
        step_size = max(1, int(step_size))

        if any(dim < 2 for dim in sdf.shape):
            print(f"Warning: Volume too small for mesh extraction: {sdf.shape}")
            return cls._create_placeholder_mesh(sdf.shape, spacing)

        has_inside = np.any(sdf < level)
        has_outside = np.any(sdf > level)
        if not (has_inside and has_outside):
            print(f"Warning: No surface crossing found at level {level}")
            return cls._create_placeholder_mesh(sdf.shape, spacing)

        try:
            vertices, faces, normals, _ = marching_cubes(
                sdf,
                level=level,
                step_size=step_size,
                allow_degenerate=False,
            )
        except (RuntimeError, ValueError) as exc:
            print(f"Warning: Marching cubes failed: {exc}")
            return cls._create_placeholder_mesh(sdf.shape, spacing)

        if len(vertices) == 0 or len(faces) == 0:
            print("Warning: Empty mesh generated")
            return cls._create_placeholder_mesh(sdf.shape, spacing)

        vertices_mm = vertices * np.array(spacing)
        return trimesh.Trimesh(
            vertices=vertices_mm,
            faces=faces,
            vertex_normals=normals,
            process=False,
        )

    @classmethod
    def extract_from_mask(
        cls,
        mask: np.ndarray,
        spacing: Tuple[float, float, float],
        smoothing_iterations: int = 0,
    ) -> trimesh.Trimesh:
        """Compute an SDF from a mask and extract a mesh."""
        sdf_volume = SDFProcessor.compute(mask)
        mesh = cls.extract_mesh(sdf_volume, spacing)

        if smoothing_iterations > 0 and len(mesh.vertices) > 0:
            mesh = cls.smooth_laplacian(mesh, iterations=smoothing_iterations)

        return mesh

    @staticmethod
    def smooth_laplacian(
        mesh: trimesh.Trimesh,
        iterations: int = 3,
        lamb: float = 0.5,
    ) -> trimesh.Trimesh:
        """Apply conservative Laplacian smoothing."""
        if len(mesh.vertices) == 0:
            return mesh

        try:
            smoothed = mesh.copy()
            trimesh.smoothing.filter_laplacian(
                smoothed,
                lamb=lamb,
                iterations=iterations,
            )
            return smoothed
        except Exception:
            return mesh

    @staticmethod
    def decimate(
        mesh: trimesh.Trimesh,
        target_faces: int | None = None,
        reduction_ratio: float | None = None,
    ) -> trimesh.Trimesh:
        """Reduce mesh complexity while preserving shape."""
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

        try:
            return mesh.simplify_quadric_decimation(int(current_faces * ratio))
        except Exception:
            return mesh

    @staticmethod
    def compute_stats(mesh: trimesh.Trimesh) -> dict:
        """Compute basic geometric statistics about a mesh."""
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

        bounds = mesh.bounds
        stats["bounds_min_mm"] = bounds[0].tolist()
        stats["bounds_max_mm"] = bounds[1].tolist()
        stats["extents_mm"] = mesh.extents.tolist()

        if mesh.is_watertight:
            stats["volume_mm3"] = float(mesh.volume)
            stats["volume_ml"] = stats["volume_mm3"] / 1000.0
        else:
            stats["volume_mm3"] = None
            stats["volume_ml"] = None

        stats["surface_area_mm2"] = float(mesh.area)
        stats["centroid_mm"] = mesh.centroid.tolist()
        return stats

    @staticmethod
    def export(mesh: trimesh.Trimesh, format: str = "obj") -> bytes:
        """Export a mesh to bytes in the requested format."""
        return mesh.export(file_type=format)

    @staticmethod
    def apply_color(
        mesh: trimesh.Trimesh,
        color: Tuple[int, int, int] | Tuple[int, int, int, int],
    ) -> trimesh.Trimesh:
        """Return a copy of the mesh with a flat RGBA color assigned."""
        if len(mesh.vertices) == 0:
            return mesh

        colored = mesh.copy()
        rgba = np.asarray(color, dtype=np.uint8)
        if rgba.shape[0] == 3:
            rgba = np.concatenate([rgba, np.array([255], dtype=np.uint8)])

        try:
            colored.visual.face_colors = np.tile(rgba, (len(colored.faces), 1))
        except Exception:
            colored.visual.vertex_colors = np.tile(rgba, (len(colored.vertices), 1))

        return colored

    @staticmethod
    def build_scene(named_meshes: list[tuple[str, trimesh.Trimesh]]) -> trimesh.Scene:
        """Assemble a named scene from individual meshes."""
        scene = trimesh.Scene()
        for name, mesh in named_meshes:
            if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
                continue
            scene.add_geometry(mesh, geom_name=name, node_name=name)
        return scene

    @staticmethod
    def _create_placeholder_mesh(
        shape: Tuple[int, int, int],
        spacing: Tuple[float, float, float],
    ) -> trimesh.Trimesh:
        """Create a simple box mesh as a fallback placeholder."""
        dims = np.array(shape) * np.array(spacing)
        dims = np.maximum(dims, 10.0)

        box = trimesh.creation.box(extents=dims)
        box.apply_translation(dims / 2)
        return box

    @staticmethod
    def combine(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
        """Combine multiple meshes into a single mesh."""
        if not meshes:
            return trimesh.Trimesh()
        if len(meshes) == 1:
            return meshes[0]
        return trimesh.util.concatenate(meshes)


def get_optimal_mesh_step_size(shape: Tuple[int, int, int]) -> int:
    return MeshProcessor.get_optimal_step_size(shape)


def extract_mesh(
    sdf: np.ndarray,
    spacing: Tuple[float, float, float],
    level: float | None = None,
    step_size: int | None = None,
) -> trimesh.Trimesh:
    return MeshProcessor.extract_mesh(sdf, spacing, level=level, step_size=step_size)


def extract_mesh_from_mask(
    mask: np.ndarray,
    spacing: Tuple[float, float, float],
    smoothing_iterations: int = 0,
) -> trimesh.Trimesh:
    return MeshProcessor.extract_from_mask(mask, spacing, smoothing_iterations=smoothing_iterations)


def smooth_mesh_laplacian(
    mesh: trimesh.Trimesh,
    iterations: int = 3,
    lamb: float = 0.5,
) -> trimesh.Trimesh:
    return MeshProcessor.smooth_laplacian(mesh, iterations=iterations, lamb=lamb)


def decimate_mesh(
    mesh: trimesh.Trimesh,
    target_faces: int | None = None,
    reduction_ratio: float | None = None,
) -> trimesh.Trimesh:
    return MeshProcessor.decimate(mesh, target_faces=target_faces, reduction_ratio=reduction_ratio)


def compute_mesh_stats(mesh: trimesh.Trimesh) -> dict:
    return MeshProcessor.compute_stats(mesh)


def export_mesh(mesh: trimesh.Trimesh, format: str = "obj") -> bytes:
    return MeshProcessor.export(mesh, format=format)


def combine_meshes(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return MeshProcessor.combine(meshes)


def colorize_mesh(
    mesh: trimesh.Trimesh,
    color: Tuple[int, int, int] | Tuple[int, int, int, int],
) -> trimesh.Trimesh:
    return MeshProcessor.apply_color(mesh, color)


def build_mesh_scene(named_meshes: list[tuple[str, trimesh.Trimesh]]) -> trimesh.Scene:
    return MeshProcessor.build_scene(named_meshes)
