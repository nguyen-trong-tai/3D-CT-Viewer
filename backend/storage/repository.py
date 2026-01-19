import os
import json
import numpy as np
import trimesh
from pathlib import Path
from typing import Optional, Dict, Any

# Simple file-based storage
STORAGE_ROOT = Path("d:/Workspace/viewr_ct/data")
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

class CaseRepository:
    def __init__(self, root_dir: Path = STORAGE_ROOT):
        self.root_dir = root_dir

    def _case_dir(self, case_id: str) -> Path:
        return self.root_dir / case_id

    def create_case(self, case_id: str):
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        self.update_status(case_id, "uploaded")

    def save_ct_volume(self, case_id: str, volume: np.ndarray, spacing: tuple):
        """Saves CT volume as a numpy file and metadata as json."""
        case_path = self._case_dir(case_id)
        np.save(case_path / "ct_volume.npy", volume.astype(np.int16)) # Save as int16 to preserve HU
        
        metadata = {
            "shape": volume.shape,
            "spacing": spacing,
            "dtype": str(volume.dtype)
        }
        with open(case_path / "ct_metadata.json", "w") as f:
            json.dump(metadata, f)

    def load_ct_volume(self, case_id: str) -> Optional[np.ndarray]:
        path = self._case_dir(case_id) / "ct_volume.npy"
        if not path.exists():
            return None
        return np.load(path)

    def load_ct_metadata(self, case_id: str) -> Optional[Dict]:
        path = self._case_dir(case_id) / "ct_metadata.json"
        if not path.exists():
            return None
        with open(path, "r") as f:
            return json.load(f)

    def save_mask(self, case_id: str, mask: np.ndarray):
        case_path = self._case_dir(case_id)
        np.save(case_path / "mask_volume.npy", mask.astype(np.uint8))

    def load_mask(self, case_id: str) -> Optional[np.ndarray]:
        path = self._case_dir(case_id) / "mask_volume.npy"
        if not path.exists():
            return None
        return np.load(path)
        
    def save_mesh(self, case_id: str, mesh: trimesh.Trimesh):
        case_path = self._case_dir(case_id)
        mesh.export(case_path / "mesh.obj")
        
    def get_mesh_path(self, case_id: str) -> Optional[Path]:
        path = self._case_dir(case_id) / "mesh.obj"
        if path.exists():
            return path
        return None

    def save_extra_metadata(self, case_id: str, metadata: Dict[str, Any]):
        """Save additional metadata (patient info, study details, etc.)"""
        case_path = self._case_dir(case_id)
        with open(case_path / "extra_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

    def load_extra_metadata(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Load additional metadata if available"""
        path = self._case_dir(case_id) / "extra_metadata.json"
        if not path.exists():
            return None
        with open(path, "r") as f:
            return json.load(f)

    def update_status(self, case_id: str, status: str):
        case_path = self._case_dir(case_id)
        with open(case_path / "status.txt", "w") as f:
            f.write(status)

    def get_status(self, case_id: str) -> str:
        """
        Returns the current status of a case.
        
        Status semantics (state machine):
        - "uploaded": Case created, processing not yet started (including early state)
        - "processing": Pipeline execution is ongoing
        - "ready": Pipeline completed successfully
        - "error": Pipeline failed after being started
        
        Note: If status.txt doesn't exist yet (race condition between creation
        and polling), we return "uploaded" as this represents the early state,
        NOT an error condition.
        """
        path = self._case_dir(case_id) / "status.txt"
        if not path.exists():
            # Early state: case may be in creation, treat as "uploaded"
            return "uploaded"
        with open(path, "r") as f:
            return f.read().strip()

