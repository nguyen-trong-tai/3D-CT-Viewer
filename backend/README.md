# CT-based Medical Imaging & AI Research Platform - Backend

## Overview

This is the backend component of the CT-based Medical Imaging & AI Research Platform. It provides:

- **CT Data Ingestion**: Upload and process DICOM series and NIfTI files
- **AI Processing Pipeline**: Segmentation → SDF → Mesh reconstruction
- **Artifact Storage & Delivery**: Case-based storage with all intermediate artifacts

**DISCLAIMER**: This software is intended for research and educational purposes. It is not certified for clinical diagnosis or treatment.

## Architecture

```
backend/
├── main.py                 # FastAPI application entry point
├── config.py               # Configuration settings
├── modal_app.py            # Modal cloud deployment
├── requirements.txt        # Python dependencies
├── api/
│   ├── router.py           # REST API endpoints
│   └── dependencies.py     # Dependency injection
├── models/
│   ├── schemas.py          # Pydantic request/response models
│   └── enums.py            # Status and type enums
├── processing/
│   ├── loader.py           # DICOM/NIfTI file loading
│   ├── segmentation.py     # Volume segmentation
│   ├── sdf.py              # Signed Distance Function
│   └── mesh.py             # Mesh generation (Marching Cubes)
├── services/
│   └── pipeline.py         # Pipeline orchestration
└── storage/
    └── repository.py       # File-based data persistence
```

## API Principles

This API follows the medical workstation architecture:

1. **Case-based, not slice-based**: All operations are per-case
2. **No real-time interaction**: API is for upload, processing, and artifact delivery
3. **Frontend independence**: After data load, frontend operates without API calls

## Quick Start

### Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### Run Development Server

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or simply:

```bash
python main.py
```

### API Documentation

Once running, access:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### Case Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/cases` | POST | Upload CT file (ZIP/NIfTI) |
| `/api/v1/cases/dicom` | POST | Upload DICOM files directly |
| `/api/v1/cases/{case_id}/status` | GET | Get case status |
| `/api/v1/cases/{case_id}` | DELETE | Delete a case |

### Processing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/cases/{case_id}/process` | POST | Start processing pipeline |
| `/api/v1/cases/{case_id}/pipeline` | GET | Get detailed pipeline status |

### Data Retrieval

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/cases/{case_id}/metadata` | GET | Get CT metadata |
| `/api/v1/cases/{case_id}/ct/volume` | GET | Get full CT volume (binary) |
| `/api/v1/cases/{case_id}/ct/slices/{index}` | GET | Get single CT slice |
| `/api/v1/cases/{case_id}/mask/volume` | GET | Get full mask (binary) |
| `/api/v1/cases/{case_id}/mask/slices/{index}` | GET | Get single mask slice |
| `/api/v1/cases/{case_id}/mesh` | GET | Get 3D mesh (Draco-compressed GLB) |
| `/api/v1/cases/{case_id}/artifacts` | GET | List available artifacts |

## Processing Pipeline

```
CT Volume (HU) → Segmentation → SDF → Mesh (Draco GLB)
```

### Stage 1: Segmentation
- Threshold-based tissue segmentation
- Deterministic and reproducible
- Output: Binary mask (uint8)

### Stage 2: SDF (Signed Distance Function)
- Euclidean distance transform
- Automatic downsampling for large volumes
- Output: Float32 distance field

### Stage 3: Mesh Extraction
- Marching Cubes at zero level-set
- Physical coordinates (mm)
- Vertex normals pre-computed
- Output: Draco-compressed GLB (80-90% smaller than OBJ)
- Compatible with @react-three/drei useGLTF hook

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | App environment. Use `production` to enable safer defaults |
| `API_DOCS_ENABLED` | `true` in dev, `false` in prod | Enables `/docs`, `/redoc`, and `/openapi.json` |
| `HEALTH_DETAILS_ENABLED` | `true` in dev, `false` in prod | Exposes runtime/backend details in health endpoints |
| `CORS_ORIGINS` | local frontend origins in dev, empty in prod | Comma-separated or JSON list of allowed browser origins |
| `CORS_ALLOW_CREDENTIALS` | `false` | Whether browsers may send credentials on cross-origin requests |
| `TRUSTED_HOSTS` | localhost/test hosts in dev, empty in prod | Comma-separated host allowlist for `Host` header validation |
| `SECURITY_HEADERS_ENABLED` | `true` | Adds basic hardening headers like `X-Frame-Options` and `nosniff` |
| `STORAGE_ROOT` | `d:/Workspace/viewr_ct/data` | Data storage directory |
| `MAX_WORKERS` | CPU count | Parallel DICOM processing workers |
| `DISTRIBUTED_RUNTIME_MODE` | `auto` | `required` makes startup fail if Redis + R2 are unavailable |
| `REDIS_URL` | unset | Redis state store for pipeline status, locks, and batch sessions |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | unset | Cloudflare R2 artifact/object storage |

For production, start from [`.env.example`](./.env.example) and set explicit values for
`CORS_ORIGINS` and `TRUSTED_HOSTS` instead of using wildcards.

## Modal Deployment

Deploy to Modal cloud with GPU support:

```bash
modal deploy modal_app.py
```

For distributed execution without shared-volume fallback, set `DISTRIBUTED_RUNTIME_MODE=required`
and provide both Redis + R2 credentials. In that mode the app will fail at startup if either
backend cannot be reached, which avoids silently dropping to in-memory/local storage.

## Data Storage

Each case is stored in `{STORAGE_ROOT}/{case_id}/`:

```
{case_id}/
├── status.json           # Case status and timestamps
├── ct_volume.npy         # HU volume (int16)
├── ct_metadata.json      # Dimensions, spacing, HU range
├── extra_metadata.json   # Patient/study info (optional)
├── mask_volume.npy       # Segmentation mask (uint8)
├── sdf_volume.npy        # SDF (float32)
└── mesh.glb              # Surface mesh (Draco-compressed GLB)
```

### Node.js Requirement

For optimal Draco compression, ensure Node.js (v18+) is installed.
The pipeline uses `gltf-pipeline` via npx for compression.
If Node.js is unavailable, meshes are saved as standard GLB without Draco.

## Performance Targets

- DICOM upload: < 2s for typical datasets
- Full pipeline: < 15s for 512×512×200 volumes
- Memory-efficient: Uses memory-mapped arrays for large volumes

## License

Research and educational use only. Not certified for clinical use.
