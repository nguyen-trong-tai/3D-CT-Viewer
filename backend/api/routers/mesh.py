"""
Mesh Router — 3D mesh retrieval

Handles serving reconstructed 3D mesh files (GLB/OBJ).
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from storage.repository import CaseRepository
from api.dependencies import get_repository


router = APIRouter(tags=["Mesh"])


@router.get("/cases/{case_id}/mesh", summary="Get 3D mesh")
async def get_mesh(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """
    Get the reconstructed 3D mesh in Draco-compressed GLB format.
    Compatible with @react-three/drei's useGLTF hook.
    """
    mesh_path = repo.get_mesh_path(case_id)

    if mesh_path is None:
        raise HTTPException(status_code=404, detail="Mesh not found")

    suffix = mesh_path.suffix.lower()
    if suffix == ".glb":
        media_type = "model/gltf-binary"
        filename = "reconstruction.glb"
    else:
        media_type = "model/obj"
        filename = "reconstruction.obj"

    return FileResponse(
        path=mesh_path,
        media_type=media_type,
        filename=filename
    )
