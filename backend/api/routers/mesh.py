"""
Mesh Router — 3D mesh retrieval

Handles serving reconstructed 3D mesh files (GLB/OBJ).
"""

from fastapi import APIRouter, HTTPException, Depends, Response
from fastapi.responses import FileResponse, RedirectResponse

from api.dependencies import get_artifact_service
from config import settings
from services.artifact_service import ArtifactService


router = APIRouter(tags=["Mesh"])


@router.get("/cases/{case_id}/mesh", summary="Get 3D mesh")
async def get_mesh(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """
    Get the reconstructed 3D mesh in Draco-compressed GLB format.
    Compatible with @react-three/drei's useGLTF hook.
    """
    try:
        delivery = artifact_service.get_mesh_delivery(case_id, expires_in_seconds=settings.MESH_URL_TTL_SECONDS)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Mesh not found")

    if delivery["type"] == "redirect":
        return RedirectResponse(url=delivery["url"], status_code=307)

    mesh_path = delivery["path"]
    suffix = mesh_path.suffix.lower()
    media_type = "model/gltf-binary" if suffix == ".glb" else "model/obj"
    filename = "reconstruction.glb" if suffix == ".glb" else "reconstruction.obj"

    return FileResponse(
        path=mesh_path,
        media_type=media_type,
        filename=filename
    )


@router.head("/cases/{case_id}/mesh", summary="Check 3D mesh availability")
async def head_mesh(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    try:
        delivery = artifact_service.get_mesh_delivery(case_id, expires_in_seconds=settings.MESH_URL_TTL_SECONDS)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Mesh not found")

    if delivery["type"] == "redirect":
        return RedirectResponse(url=delivery["url"], status_code=307)

    mesh_path = delivery["path"]
    suffix = mesh_path.suffix.lower()
    media_type = "model/gltf-binary" if suffix == ".glb" else "model/obj"

    return Response(media_type=media_type)
