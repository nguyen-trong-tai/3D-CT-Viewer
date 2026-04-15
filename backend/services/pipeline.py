"""
Pipeline Service

Orchestrates the CT processing pipeline:
CT Volume → Segmentation → SDF → Mesh

This service coordinates all processing stages and manages
artifact storage throughout the pipeline lifecycle.
"""

import time
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from storage.repository import CaseRepository
from models.enums import CaseStatus
from processing import (
    HUPreprocessor,
    MeshProcessor,
    SDFProcessor,
)
from services.ai_segmentation import AISegmentationService


class PipelineStageStatus(str, Enum):
    """Status of individual pipeline stages."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStageResult:
    """Result of a pipeline stage execution."""
    name: str
    status: PipelineStageStatus
    duration_seconds: float = 0.0
    message: str = ""
    output_shape: Optional[tuple] = None


@dataclass
class PipelineResult:
    """Complete result of pipeline execution."""
    case_id: str
    success: bool
    stages: list = field(default_factory=list)
    total_duration_seconds: float = 0.0
    error_message: Optional[str] = None


@dataclass
class SegmentationComponent:
    """Normalized segmentation component for downstream mesh generation."""
    key: str
    display_name: str
    mask: np.ndarray
    color_hex: str
    label_id: int = 0
    visible_by_default: bool = True
    render_2d: bool = False
    render_3d: bool = True


class PipelineService:
    """
    Orchestrates the full CT → 3D processing pipeline.
    Pipeline stages:
    1. Load CT volume from storage
    2. Segmentation (threshold-based)
    3. SDF computation (with automatic downsampling for large volumes)
    4. Mesh extraction (Marching Cubes)
    
    All intermediate artifacts are stored for inspection and reuse.
    """
    
    def __init__(self, repository: CaseRepository):
        self.repo = repository
        self._active_pipelines: Dict[str, bool] = {}
        self.ai_segmenter = AISegmentationService()
    def process_case(
        self,
        case_id: str,
        force_recompute: bool = False,
        segmentation_threshold: float = -600.0,
    ) -> PipelineResult:
        """
        Execute the full processing pipeline for a case.
        
        This is the main entry point for pipeline execution.
        Should be run in a background thread/task.
        
        Args:
            case_id: Unique case identifier
            force_recompute: If True, recompute even if artifacts exist
            segmentation_threshold: HU threshold for segmentation
            
        Returns:
            PipelineResult with status of each stage
        """
        result = PipelineResult(case_id=case_id, success=False)
        total_start = time.time()
        lock_acquired = False
        
        try:
            # Mark pipeline as active
            lock_acquired = self.repo.acquire_processing_lock(case_id)
            if not lock_acquired:
                raise ValueError("Case is already locked for processing")

            self._active_pipelines[case_id] = True
            self.repo.update_status(case_id, CaseStatus.PROCESSING.value)
            
            # Stage 1: Load CT Volume
            self.repo.update_pipeline_stage(case_id, "load_volume", "running")
            stage_result, volume, metadata = self._stage_load_volume(case_id)
            result.stages.append(stage_result)
            self.repo.update_pipeline_stage(
                case_id,
                stage_result.name,
                stage_result.status.value,
                duration_seconds=stage_result.duration_seconds,
                message=stage_result.message,
                output_shape=stage_result.output_shape,
            )
            
            if stage_result.status == PipelineStageStatus.FAILED:
                raise ValueError(f"Failed to load volume: {stage_result.message}")
            spacing = tuple(metadata["spacing"])
            
            print(f"[Pipeline] Volume loaded: {volume.shape}, spacing: {spacing}")
            
            # Stage 2: Segmentation
            self.repo.update_pipeline_stage(case_id, "segmentation", "running")
            stage_result, mask, mesh_components = self._stage_segmentation(
                case_id, volume, metadata, segmentation_threshold, force_recompute
            )
            result.stages.append(stage_result)
            self.repo.update_pipeline_stage(
                case_id,
                stage_result.name,
                stage_result.status.value,
                duration_seconds=stage_result.duration_seconds,
                message=stage_result.message,
                output_shape=stage_result.output_shape,
            )
            
            if stage_result.status == PipelineStageStatus.FAILED:
                raise ValueError(f"Segmentation failed: {stage_result.message}")

            # Stage 3: SDF Computation
            self.repo.update_pipeline_stage(case_id, "sdf", "running")
            stage_result, sdf_volume = self._stage_sdf(case_id, mask, force_recompute)
            result.stages.append(stage_result)
            self.repo.update_pipeline_stage(
                case_id,
                stage_result.name,
                stage_result.status.value,
                duration_seconds=stage_result.duration_seconds,
                message=stage_result.message,
                output_shape=stage_result.output_shape,
            )
            
            if stage_result.status == PipelineStageStatus.FAILED:
                raise ValueError(f"SDF computation failed: {stage_result.message}")

            # Stage 4: Mesh Extraction
            self.repo.update_pipeline_stage(case_id, "mesh", "running")
            stage_result = self._stage_mesh(
                case_id, sdf_volume, spacing, mesh_components, force_recompute
            )
            result.stages.append(stage_result)
            self.repo.update_pipeline_stage(
                case_id,
                stage_result.name,
                stage_result.status.value,
                duration_seconds=stage_result.duration_seconds,
                message=stage_result.message,
            )
            
            if stage_result.status == PipelineStageStatus.FAILED:
                raise ValueError(f"Mesh extraction failed: {stage_result.message}")
            
            # Success!
            result.success = True
            result.total_duration_seconds = time.time() - total_start
            
            self.repo.update_status(
                case_id,
                CaseStatus.READY.value,
                message=f"Completed in {result.total_duration_seconds:.1f}s"
            )
            
            print(f"[Pipeline] COMPLETE: {result.total_duration_seconds:.2f}s")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            result.success = False
            result.error_message = str(e)
            result.total_duration_seconds = time.time() - total_start
            
            self.repo.update_status(
                case_id,
                CaseStatus.ERROR.value,
                message=str(e)
            )
            
            print(f"[Pipeline] FAILED: {e}")
            
        finally:
            self._active_pipelines.pop(case_id, None)
            if lock_acquired:
                self.repo.release_processing_lock(case_id)
        
        return result
    
    def _stage_load_volume(
        self, case_id: str
    ) -> tuple[PipelineStageResult, Optional[np.ndarray], Optional[Dict[str, Any]]]:
        """Stage 1: Verify volume is loaded and accessible."""
        start = time.time()
        
        try:
            metadata = self.repo.load_ct_metadata(case_id)

            volume = None
            load_mode = "mmap"
            try:
                volume = self.repo.load_ct_volume_mmap(case_id)
            except Exception:
                volume = None

            if volume is None:
                volume = self.repo.load_ct_volume(case_id)
                load_mode = "eager"
            
            if volume is None or metadata is None:
                return (
                    PipelineStageResult(
                        name="load_volume",
                        status=PipelineStageStatus.FAILED,
                        message="Volume or metadata not found"
                    ),
                    None,
                    None,
                )

            return (
                PipelineStageResult(
                    name="load_volume",
                    status=PipelineStageStatus.COMPLETED,
                    duration_seconds=time.time() - start,
                    output_shape=volume.shape,
                    message=f"Loaded volume: {volume.shape} ({load_mode})"
                ),
                volume,
                metadata,
            )
            
        except Exception as e:
            return (
                PipelineStageResult(
                    name="load_volume",
                    status=PipelineStageStatus.FAILED,
                    duration_seconds=time.time() - start,
                    message=str(e)
                ),
                None,
                None,
            )
    
    def _stage_segmentation(
        self,
        case_id: str,
        volume: np.ndarray,
        metadata: Optional[Dict[str, Any]],
        threshold: float,
        force_recompute: bool,
    ) -> tuple[PipelineStageResult, Optional[np.ndarray], list[SegmentationComponent]]:
        """Stage 2: Segment the CT volume."""
        start = time.time()
        
        try:
            # # Check if mask already exists
            # if not force_recompute and self.repo.mask_exists(case_id):
            #     mask = self.repo.load_mask(case_id)
            #     if mask is None:
            #         return (
            #             PipelineStageResult(
            #                 name="segmentation",
            #                 status=PipelineStageStatus.FAILED,
            #                 duration_seconds=time.time() - start,
            #                 message="Mask manifest exists but artifact could not be loaded"
            #             ),
            #             None,
            #         )
            #     return (
            #         PipelineStageResult(
            #             name="segmentation",
            #             status=PipelineStageStatus.SKIPPED,
            #             duration_seconds=time.time() - start,
            #             output_shape=mask.shape,
            #             message="Using existing mask"
            #         ),
            #         mask,
            #     )
            
            # Perform deterministic baseline segmentation only.
            print(f"[Pipeline Stage 2] Running baseline segmentation (Threshold: {threshold} HU)...")
            volume = self._prepare_volume_for_segmentation(volume, metadata)
            spacing = tuple(float(value) for value in (metadata or {}).get("spacing", (1.0, 1.0, 1.0)))
            segmentation_result = self.ai_segmenter.segment(volume, spacing)
            mask, mesh_components, manifest = self._normalize_segmentation_result(segmentation_result)
            
            # Khởi tạo mesh placeholder nếu không có voxel nào (tránh crash pipeline)
            if np.sum(mask > 0) == 0:
                print(f"[Pipeline Stage 2] Trả về mảng rỗng do không tìm thấy structure.")
            
            # Store result
            self.repo.save_mask(case_id, mask, manifest=manifest)
            
            voxel_count = int(np.count_nonzero(mask))
            component_message = ", ".join(
                f"{item['display_name']}={int(item['voxel_count']):,}"
                for item in manifest.get("labels", [])
                if int(item.get("voxel_count", 0)) > 0
            ) or "no visible components"

            return (
                PipelineStageResult(
                    name="segmentation",
                    status=PipelineStageStatus.COMPLETED,
                    duration_seconds=time.time() - start,
                    output_shape=mask.shape,
                    message=(
                        f"Labeled {voxel_count:,} voxels; "
                        f"{len(mesh_components)} 3D components; "
                        f"{component_message}"
                    )
                ),
                mask,
                mesh_components,
            )
            
        except Exception as e:
            return (
                PipelineStageResult(
                    name="segmentation",
                    status=PipelineStageStatus.FAILED,
                    duration_seconds=time.time() - start,
                    message=str(e)
                ),
                None,
                [],
            )
    
    def _stage_sdf(
        self,
        case_id: str,
        mask: np.ndarray,
        force_recompute: bool
    ) -> tuple[PipelineStageResult, Optional[np.ndarray]]:
        """Stage 3: Compute Signed Distance Function."""
        start = time.time()
        
        try:
            # Check if SDF already exists
            if not force_recompute and self.repo.sdf_exists(case_id):
                sdf = self.repo.load_sdf(case_id)
                if sdf is None:
                    return (
                        PipelineStageResult(
                            name="sdf",
                            status=PipelineStageStatus.FAILED,
                            duration_seconds=time.time() - start,
                            message="SDF manifest exists but artifact could not be loaded"
                        ),
                        None,
                    )
                return (
                    PipelineStageResult(
                        name="sdf",
                        status=PipelineStageStatus.SKIPPED,
                        duration_seconds=time.time() - start,
                        output_shape=sdf.shape,
                        message="Using existing SDF"
                    ),
                    sdf,
                )
            
            # Determine optimal downsample factor based on volume size
            downsample_factor = SDFProcessor.get_optimal_downsample_factor(mask.shape)
            
            if downsample_factor > 1:
                print(f"[Pipeline] SDF: Using downsample factor {downsample_factor}")
                sdf = SDFProcessor.compute_downsampled(mask, factor=downsample_factor)
            else:
                sdf = SDFProcessor.compute_fast(mask)

            if sdf.dtype != np.float32:
                sdf = sdf.astype(np.float32, copy=False)
            
            # Store result (not full SDF to save space - mesh is what matters)
            # But PRD requires intermediate artifacts to be stored
            self.repo.save_sdf(case_id, sdf)
            
            return (
                PipelineStageResult(
                    name="sdf",
                    status=PipelineStageStatus.COMPLETED,
                    duration_seconds=time.time() - start,
                    output_shape=sdf.shape,
                    message=f"SDF computed (factor={downsample_factor})"
                ),
                sdf,
            )
            
        except Exception as e:
            return (
                PipelineStageResult(
                    name="sdf",
                    status=PipelineStageStatus.FAILED,
                    duration_seconds=time.time() - start,
                    message=str(e)
                ),
                None,
            )
    
    def _stage_mesh(
        self,
        case_id: str,
        sdf: np.ndarray,
        spacing: tuple,
        mesh_components: list[SegmentationComponent],
        force_recompute: bool
    ) -> PipelineStageResult:
        """Stage 4: Extract surface mesh using Marching Cubes."""
        start = time.time()
        
        try:
            # Check if mesh already exists
            if not force_recompute and self.repo.mesh_exists(case_id):
                return PipelineStageResult(
                    name="mesh",
                    status=PipelineStageStatus.SKIPPED,
                    duration_seconds=time.time() - start,
                    message="Using existing mesh"
                )
            
            component_meshes: list[tuple[str, Any]] = []
            total_vertices = 0
            total_faces = 0

            for component in mesh_components:
                if not np.any(component.mask):
                    continue

                component_sdf, downsample_factor = self._compute_mask_sdf(component.mask)
                mesh_step_size = MeshProcessor.get_optimal_step_size(component_sdf.shape)
                component_mesh = MeshProcessor.extract_mesh(
                    component_sdf,
                    spacing,
                    step_size=mesh_step_size,
                )

                if len(component_mesh.vertices) == 0 or len(component_mesh.faces) == 0:
                    continue

                colored_mesh = MeshProcessor.apply_color(
                    component_mesh,
                    self._hex_to_rgba(component.color_hex),
                )
                component_meshes.append((component.key, colored_mesh))

                component_stats = MeshProcessor.compute_stats(colored_mesh)
                total_vertices += int(component_stats["vertex_count"])
                total_faces += int(component_stats["face_count"])
                print(
                    "[Pipeline] Mesh component "
                    f"{component.key}: faces={component_stats['face_count']}, "
                    f"downsample={downsample_factor}, step={mesh_step_size}"
                )

            if component_meshes:
                mesh_scene = MeshProcessor.build_scene(component_meshes)
                self.repo.save_mesh(case_id, mesh_scene)
                return PipelineStageResult(
                    name="mesh",
                    status=PipelineStageStatus.COMPLETED,
                    duration_seconds=time.time() - start,
                    message=(
                        f"{len(component_meshes)} components, "
                        f"{total_vertices:,} vertices, {total_faces:,} faces"
                    )
                )

            # Fallback to the legacy single-mesh path when no component meshes exist.
            mesh_step_size = MeshProcessor.get_optimal_step_size(sdf.shape)
            mesh = MeshProcessor.extract_mesh(sdf, spacing, step_size=mesh_step_size)
            self.repo.save_mesh(case_id, mesh)
            stats = MeshProcessor.compute_stats(mesh)

            return PipelineStageResult(
                name="mesh",
                status=PipelineStageStatus.COMPLETED,
                duration_seconds=time.time() - start,
                message=(
                    f"{stats['vertex_count']:,} vertices, "
                    f"{stats['face_count']:,} faces (fallback, step_size={mesh_step_size})"
                )
            )
            
        except Exception as e:
            return PipelineStageResult(
                name="mesh",
                status=PipelineStageStatus.FAILED,
                duration_seconds=time.time() - start,
                message=str(e)
            )

    @staticmethod
    def _normalize_segmentation_result(
        segmentation_result: Dict[str, Any]
    ) -> tuple[np.ndarray, list[SegmentationComponent], dict[str, Any]]:
        """
        Normalize segmentation outputs into a combined overlay mask and 3D components.

        Current segmenters can return legacy top-level masks or a future-proof
        `components` dictionary. The combined overlay mask remains unchanged so
        frontend 2D overlays keep working without modification.
        """
        raw_components = segmentation_result.get("components")
        components: list[SegmentationComponent] = []
        manifest = dict(segmentation_result.get("manifest") or {})

        if isinstance(raw_components, dict) and raw_components:
            for key, payload in raw_components.items():
                if isinstance(payload, dict):
                    mask = payload.get("mask")
                    display_name = str(payload.get("name") or key.replace("_", " ").title())
                    color_hex = str(payload.get("color") or PipelineService._default_component_color(key))
                    label_id = int(payload.get("label_id") or PipelineService._default_component_label(key))
                    visible_by_default = bool(payload.get("visible_by_default", True))
                    render_2d = bool(payload.get("render_2d", False))
                    render_3d = bool(payload.get("render_3d", True))
                else:
                    mask = payload
                    display_name = key.replace("_", " ").title()
                    color_hex = PipelineService._default_component_color(key)
                    label_id = PipelineService._default_component_label(key)
                    visible_by_default = True
                    render_2d = False
                    render_3d = True

                if mask is None:
                    continue

                components.append(
                    SegmentationComponent(
                        key=key,
                        display_name=display_name,
                        mask=np.asarray(mask, dtype=np.uint8),
                        color_hex=color_hex,
                        label_id=label_id,
                        visible_by_default=visible_by_default,
                        render_2d=render_2d,
                        render_3d=render_3d,
                    )
                )
        else:
            fallback_specs = (
                ("lung", "lung_mask", "Lungs", True, False),
                ("left_lung", "left_mask", "Left Lung", False, True),
                ("right_lung", "right_mask", "Right Lung", False, True),
            )
            for key, source_key, display_name, render_2d, render_3d in fallback_specs:
                mask = segmentation_result.get(source_key)
                if mask is None:
                    continue
                components.append(
                    SegmentationComponent(
                        key=key,
                        display_name=display_name,
                        mask=np.asarray(mask, dtype=np.uint8),
                        color_hex=PipelineService._default_component_color(key),
                        label_id=PipelineService._default_component_label(key),
                        visible_by_default=True,
                        render_2d=render_2d,
                        render_3d=render_3d,
                    )
                )

        combined_mask = segmentation_result.get("labeled_mask")
        if combined_mask is None:
            combined_mask = segmentation_result.get("lung_mask")
        if combined_mask is None:
            overlay_sources = [component.mask for component in components]
            if not overlay_sources:
                raise ValueError("Segmentation result did not contain any masks")
            combined_mask = np.logical_or.reduce([mask.astype(bool) for mask in overlay_sources]).astype(np.uint8)
        else:
            combined_mask = np.asarray(combined_mask, dtype=np.uint8)

        renderable_components = [
            component
            for component in components
            if component.render_3d and np.any(component.mask)
        ]

        if not renderable_components and np.any(combined_mask):
            renderable_components = [
                SegmentationComponent(
                    key="lung",
                    display_name="Lungs",
                    mask=combined_mask,
                    color_hex=PipelineService._default_component_color("lung"),
                    label_id=PipelineService._default_component_label("lung"),
                    visible_by_default=True,
                    render_2d=True,
                    render_3d=True,
                )
            ]

        if not manifest:
            manifest = {
                "version": 1,
                "has_labeled_mask": bool(np.max(combined_mask) > 1),
                "labels": [
                    {
                        "label_id": component.label_id,
                        "key": component.key,
                        "display_name": component.display_name,
                        "color": component.color_hex,
                        "available": bool(np.any(component.mask)),
                        "visible_by_default": component.visible_by_default,
                        "render_2d": component.render_2d,
                        "render_3d": component.render_3d,
                        "voxel_count": int(np.count_nonzero(component.mask)),
                        "mesh_component_name": component.key,
                    }
                    for component in components
                ],
            }

        return combined_mask, renderable_components, manifest

    @staticmethod
    def _compute_mask_sdf(mask: np.ndarray) -> tuple[np.ndarray, int]:
        """Compute an SDF for an individual component mask."""
        downsample_factor = SDFProcessor.get_optimal_downsample_factor(mask.shape)
        if downsample_factor > 1:
            sdf = SDFProcessor.compute_downsampled(mask, factor=downsample_factor)
        else:
            sdf = SDFProcessor.compute_fast(mask)

        if sdf.dtype != np.float32:
            sdf = sdf.astype(np.float32, copy=False)

        return sdf, downsample_factor

    @staticmethod
    def _default_component_color(component_key: str) -> str:
        palette = {
            "lung": "#ef4444",
            "left_lung": "#60a5fa",
            "right_lung": "#34d399",
            "nodule": "#f97316",
        }
        return palette.get(component_key, "#f59e0b")

    @staticmethod
    def _default_component_label(component_key: str) -> int:
        label_map = {
            "left_lung": 1,
            "right_lung": 2,
            "nodule": 3,
            "lung": 1,
        }
        return label_map.get(component_key, 0)

    @staticmethod
    def _prepare_volume_for_segmentation(
        volume: np.ndarray,
        metadata: Optional[Dict[str, Any]],
    ) -> np.ndarray:
        """Skip a full-volume clip pass when persisted HU metadata is already in range."""
        if PipelineService._is_hu_range_within_clip_bounds(metadata):
            return volume
        return HUPreprocessor.clip_hu(volume)

    @staticmethod
    def _is_hu_range_within_clip_bounds(metadata: Optional[Dict[str, Any]]) -> bool:
        """Check whether stored HU range guarantees the volume is already clip-safe."""
        if not isinstance(metadata, dict):
            return False

        hu_range = metadata.get("hu_range")
        if not isinstance(hu_range, dict):
            return False

        try:
            hu_min = float(hu_range["min"])
            hu_max = float(hu_range["max"])
        except (KeyError, TypeError, ValueError):
            return False

        return (
            hu_min >= HUPreprocessor.HU_CLIP_MIN
            and hu_max <= HUPreprocessor.HU_CLIP_MAX
        )

    @staticmethod
    def _hex_to_rgba(color_hex: str) -> tuple[int, int, int, int]:
        value = color_hex.strip().lstrip("#")
        if len(value) == 6:
            value += "ff"
        if len(value) != 8:
            raise ValueError(f"Invalid color: {color_hex}")
        return tuple(int(value[index:index + 2], 16) for index in range(0, 8, 2))
    
    def start_pipeline_async(self, case_id: str, **kwargs) -> bool:
        """
        Start pipeline execution in a background thread.
        
        Returns True if pipeline started, False if already running.
        """
        if case_id in self._active_pipelines:
            return False
        
        thread = threading.Thread(
            target=self.process_case,
            args=(case_id,),
            kwargs=kwargs,
            daemon=True
        )
        thread.start()
        
        return True
    
    def is_pipeline_running(self, case_id: str) -> bool:
        """Check if a pipeline is currently running for a case."""
        return case_id in self._active_pipelines
    
    def get_pipeline_status(self, case_id: str) -> Dict[str, Any]:
        """
        Get detailed pipeline status for a case.
        
        Checks which artifacts are available to determine progress.
        """
        status = self.repo.get_status(case_id)
        artifacts = self.repo.get_available_artifacts(case_id)
        pipeline_state = self.repo.get_pipeline_state(case_id)

        stages = []
        if pipeline_state:
            for stage_name in ["load_volume", "segmentation", "sdf", "mesh"]:
                payload = pipeline_state.get(stage_name, {"status": "pending"})
                stages.append({
                    "name": stage_name,
                    "status": payload.get("status", "pending"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "message": payload.get("message"),
                })
        else:
            if artifacts.get("ct_volume"):
                stages.append({"name": "load_volume", "status": "completed"})
            if artifacts.get("segmentation_mask"):
                stages.append({"name": "segmentation", "status": "completed"})
            elif status == CaseStatus.PROCESSING.value:
                stages.append({"name": "segmentation", "status": "running" if len(stages) == 1 else "pending"})
            if artifacts.get("sdf"):
                stages.append({"name": "sdf", "status": "completed"})
            elif status == CaseStatus.PROCESSING.value:
                stages.append({"name": "sdf", "status": "running" if len(stages) == 2 else "pending"})
            if artifacts.get("mesh"):
                stages.append({"name": "mesh", "status": "completed"})
            elif status == CaseStatus.PROCESSING.value:
                stages.append({"name": "mesh", "status": "running" if len(stages) == 3 else "pending"})
        
        return {
            "case_id": case_id,
            "overall_status": status,
            "is_running": self.is_pipeline_running(case_id),
            "stages": stages,
            "artifacts": artifacts
        }
