# CT-to-3D Research Backend

This is the research pipeline executor for:
**CT (HU) -> Segmentation -> SDF -> 3D Mesh**

## Architecture

- **api/**: FastAPI routes matching `API_CONTRACT.md`.
- **processing/**: Scientific modules (Loader, Seg, SDF, Mesh).
- **services/**: Linear pipeline orchestration.
- **storage/**: File-based persistence of numpy volumes.

## Constraints

This backend strictly adheres to:
1. **Preserving HU Values**: No normalization or windowing is applied to source data.
2. **Explicit Stages**: Every stage produces an intermediate artifact.
3. **Physical Units**: Meshes are scaled to millimeters using voxel spacing.

## Running Locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## Running on Modal

```bash
modal serve modal_app.py
```
