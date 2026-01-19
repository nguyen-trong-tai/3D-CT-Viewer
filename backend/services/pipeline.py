import numpy as np
import threading
import time
from pathlib import Path
from storage.repository import CaseRepository
from processing import segmentation, sdf, mesh


class PipelineService:
    def __init__(self, repository: CaseRepository):
        self.repo = repository

    def process_case(self, case_id: str, downsample_factor: int = 2):
        """
        Orchestrates the full pipeline:
        Segmentation -> SDF -> Mesh
        
        OPTIMIZED for speed:
        - Uses downsampling for SDF computation on large volumes
        - Timing logs for performance monitoring
        
        Target: < 15 seconds for typical CT volume (512x512x200)
        
        This should be run in a background thread/task.
        """
        try:
            total_start = time.time()
            self.repo.update_status(case_id, "processing")
            
            # 1. Load CT
            t0 = time.time()
            volume = self.repo.load_ct_volume(case_id)
            metadata = self.repo.load_ct_metadata(case_id)
            
            if volume is None or metadata is None:
                raise ValueError("Volume data not found")
                
            spacing = metadata["spacing"]
            print(f"[Pipeline] Loaded volume: {volume.shape}, spacing: {spacing} ({time.time()-t0:.2f}s)")
            
            # Determine if we should downsample based on volume size
            # For volumes > 100M voxels, use aggressive downsampling
            total_voxels = np.prod(volume.shape)
            if total_voxels > 100_000_000:  # > 100M voxels
                downsample_factor = 4
                print(f"[Pipeline] Large volume detected, using downsample_factor={downsample_factor}")
            elif total_voxels > 50_000_000:  # > 50M voxels
                downsample_factor = 3
            elif total_voxels > 20_000_000:  # > 20M voxels
                downsample_factor = 2
            else:
                downsample_factor = 1  # No downsampling for small volumes
            
            # 2. Segmentation (fast - just thresholding)
            t0 = time.time()
            mask = segmentation.segment_volume_baseline(volume)
            print(f"[Pipeline] Segmentation done: {mask.shape} ({time.time()-t0:.2f}s)")
            
            # Save full resolution mask
            self.repo.save_mask(case_id, mask)
            
            # 3. SDF computation (expensive - use downsampling)
            t0 = time.time()
            if downsample_factor > 1:
                sdf_volume = sdf.compute_sdf_downsampled(mask, factor=downsample_factor)
            else:
                sdf_volume = sdf.compute_sdf(mask)
            print(f"[Pipeline] SDF done: {sdf_volume.shape} ({time.time()-t0:.2f}s)")
            
            # 4. Mesh Reconstruction
            t0 = time.time()
            mesh_obj = mesh.extract_mesh(sdf_volume, spacing)
            print(f"[Pipeline] Mesh done: {len(mesh_obj.vertices)} vertices ({time.time()-t0:.2f}s)")
            
            self.repo.save_mesh(case_id, mesh_obj)
            
            self.repo.update_status(case_id, "ready")
            
            total_time = time.time() - total_start
            print(f"[Pipeline] TOTAL: {total_time:.2f}s for case {case_id}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Pipeline failed for {case_id}: {e}")
            self.repo.update_status(case_id, "error")

    def start_pipeline_async(self, case_id: str):
        thread = threading.Thread(target=self.process_case, args=(case_id,))
        thread.start()
