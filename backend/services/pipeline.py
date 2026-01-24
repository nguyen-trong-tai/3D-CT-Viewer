"""
Pipeline Service

Orchestrates the AI processing pipeline:
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
    segment_volume_baseline,
    compute_sdf,
    compute_sdf_downsampled,
    get_optimal_downsample_factor,
    extract_mesh,
    compute_mesh_stats,
)


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
    
    def process_case(
        self,
        case_id: str,
        force_recompute: bool = False,
        segmentation_threshold: float = -600.0
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
        
        try:
            # Mark pipeline as active
            self._active_pipelines[case_id] = True
            self.repo.update_status(case_id, CaseStatus.PROCESSING.value)
            
            # Stage 1: Load CT Volume
            stage_result = self._stage_load_volume(case_id)
            result.stages.append(stage_result)
            
            if stage_result.status == PipelineStageStatus.FAILED:
                raise ValueError(f"Failed to load volume: {stage_result.message}")
            
            volume = self.repo.load_ct_volume(case_id)
            metadata = self.repo.load_ct_metadata(case_id)
            spacing = tuple(metadata["spacing"])
            
            print(f"[Pipeline] Volume loaded: {volume.shape}, spacing: {spacing}")
            
            # Stage 2: Segmentation
            stage_result = self._stage_segmentation(
                case_id, volume, segmentation_threshold, force_recompute
            )
            result.stages.append(stage_result)
            
            if stage_result.status == PipelineStageStatus.FAILED:
                raise ValueError(f"Segmentation failed: {stage_result.message}")
            
            mask = self.repo.load_mask(case_id)
            
            # Stage 3: SDF Computation
            stage_result = self._stage_sdf(case_id, mask, force_recompute)
            result.stages.append(stage_result)
            
            if stage_result.status == PipelineStageStatus.FAILED:
                raise ValueError(f"SDF computation failed: {stage_result.message}")
            
            sdf_volume = self.repo.load_sdf(case_id)
            
            # Stage 4: Mesh Extraction
            stage_result = self._stage_mesh(
                case_id, sdf_volume, spacing, force_recompute
            )
            result.stages.append(stage_result)
            
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
        
        return result
    
    def _stage_load_volume(self, case_id: str) -> PipelineStageResult:
        """Stage 1: Verify volume is loaded and accessible."""
        start = time.time()
        
        try:
            volume = self.repo.load_ct_volume(case_id)
            metadata = self.repo.load_ct_metadata(case_id)
            
            if volume is None or metadata is None:
                return PipelineStageResult(
                    name="load_volume",
                    status=PipelineStageStatus.FAILED,
                    message="Volume or metadata not found"
                )
            
            return PipelineStageResult(
                name="load_volume",
                status=PipelineStageStatus.COMPLETED,
                duration_seconds=time.time() - start,
                output_shape=volume.shape,
                message=f"Loaded volume: {volume.shape}"
            )
            
        except Exception as e:
            return PipelineStageResult(
                name="load_volume",
                status=PipelineStageStatus.FAILED,
                duration_seconds=time.time() - start,
                message=str(e)
            )
    
    def _stage_segmentation(
        self,
        case_id: str,
        volume: np.ndarray,
        threshold: float,
        force_recompute: bool
    ) -> PipelineStageResult:
        """Stage 2: Segment the CT volume."""
        start = time.time()
        
        try:
            # Check if mask already exists
            if not force_recompute and self.repo.mask_exists(case_id):
                mask = self.repo.load_mask(case_id)
                return PipelineStageResult(
                    name="segmentation",
                    status=PipelineStageStatus.SKIPPED,
                    duration_seconds=time.time() - start,
                    output_shape=mask.shape,
                    message="Using existing mask"
                )
            
            # Perform segmentation
            mask = segment_volume_baseline(volume, threshold=threshold)
            
            # Store result
            self.repo.save_mask(case_id, mask)
            
            voxel_count = int(np.sum(mask > 0))
            
            return PipelineStageResult(
                name="segmentation",
                status=PipelineStageStatus.COMPLETED,
                duration_seconds=time.time() - start,
                output_shape=mask.shape,
                message=f"Segmented {voxel_count:,} voxels"
            )
            
        except Exception as e:
            return PipelineStageResult(
                name="segmentation",
                status=PipelineStageStatus.FAILED,
                duration_seconds=time.time() - start,
                message=str(e)
            )
    
    def _stage_sdf(
        self,
        case_id: str,
        mask: np.ndarray,
        force_recompute: bool
    ) -> PipelineStageResult:
        """Stage 3: Compute Signed Distance Function."""
        start = time.time()
        
        try:
            # Check if SDF already exists
            if not force_recompute and self.repo.sdf_exists(case_id):
                sdf = self.repo.load_sdf(case_id)
                return PipelineStageResult(
                    name="sdf",
                    status=PipelineStageStatus.SKIPPED,
                    duration_seconds=time.time() - start,
                    output_shape=sdf.shape,
                    message="Using existing SDF"
                )
            
            # Determine optimal downsample factor based on volume size
            downsample_factor = get_optimal_downsample_factor(mask.shape)
            
            if downsample_factor > 1:
                print(f"[Pipeline] SDF: Using downsample factor {downsample_factor}")
                sdf = compute_sdf_downsampled(mask, factor=downsample_factor)
            else:
                sdf = compute_sdf(mask)
            
            # Store result (not full SDF to save space - mesh is what matters)
            # But PRD requires intermediate artifacts to be stored
            self.repo.save_sdf(case_id, sdf)
            
            return PipelineStageResult(
                name="sdf",
                status=PipelineStageStatus.COMPLETED,
                duration_seconds=time.time() - start,
                output_shape=sdf.shape,
                message=f"SDF computed (factor={downsample_factor})"
            )
            
        except Exception as e:
            return PipelineStageResult(
                name="sdf",
                status=PipelineStageStatus.FAILED,
                duration_seconds=time.time() - start,
                message=str(e)
            )
    
    def _stage_mesh(
        self,
        case_id: str,
        sdf: np.ndarray,
        spacing: tuple,
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
            
            # Extract mesh
            mesh = extract_mesh(sdf, spacing)
            
            # Store result
            self.repo.save_mesh(case_id, mesh)
            
            # Compute stats
            stats = compute_mesh_stats(mesh)
            
            return PipelineStageResult(
                name="mesh",
                status=PipelineStageStatus.COMPLETED,
                duration_seconds=time.time() - start,
                message=f"{stats['vertex_count']:,} vertices, {stats['face_count']:,} faces"
            )
            
        except Exception as e:
            return PipelineStageResult(
                name="mesh",
                status=PipelineStageStatus.FAILED,
                duration_seconds=time.time() - start,
                message=str(e)
            )
    
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
        
        stages = []
        
        # Determine stage statuses based on artifacts
        if artifacts.get("ct_volume"):
            stages.append({
                "name": "load_volume",
                "status": "completed"
            })
        
        if artifacts.get("segmentation_mask"):
            stages.append({
                "name": "segmentation",
                "status": "completed"
            })
        elif status == CaseStatus.PROCESSING.value:
            stages.append({
                "name": "segmentation",
                "status": "running" if len(stages) == 1 else "pending"
            })
        
        if artifacts.get("sdf"):
            stages.append({
                "name": "sdf",
                "status": "completed"
            })
        elif status == CaseStatus.PROCESSING.value:
            stages.append({
                "name": "sdf",
                "status": "running" if len(stages) == 2 else "pending"
            })
        
        if artifacts.get("mesh"):
            stages.append({
                "name": "mesh",
                "status": "completed"
            })
        elif status == CaseStatus.PROCESSING.value:
            stages.append({
                "name": "mesh",
                "status": "running" if len(stages) == 3 else "pending"
            })
        
        return {
            "case_id": case_id,
            "overall_status": status,
            "is_running": self.is_pipeline_running(case_id),
            "stages": stages,
            "artifacts": artifacts
        }
