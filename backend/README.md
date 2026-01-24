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
| `/api/v1/cases/{case_id}/process` | POST | Start AI processing pipeline |
| `/api/v1/cases/{case_id}/pipeline` | GET | Get detailed pipeline status |

### Data Retrieval

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/cases/{case_id}/metadata` | GET | Get CT metadata |
| `/api/v1/cases/{case_id}/ct/volume` | GET | Get full CT volume (binary) |
| `/api/v1/cases/{case_id}/ct/slices/{index}` | GET | Get single CT slice |
| `/api/v1/cases/{case_id}/mask/volume` | GET | Get full mask (binary) |
| `/api/v1/cases/{case_id}/mask/slices/{index}` | GET | Get single mask slice |
| `/api/v1/cases/{case_id}/mesh` | GET | Get 3D mesh (OBJ) |
| `/api/v1/cases/{case_id}/artifacts` | GET | List available artifacts |

## Processing Pipeline

```
CT Volume (HU) → Segmentation → SDF → Mesh (OBJ)
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
- Output: OBJ file

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_ROOT` | `d:/Workspace/viewr_ct/data` | Data storage directory |
| `MAX_WORKERS` | CPU count | Parallel DICOM processing workers |

## Modal Deployment

Deploy to Modal cloud with GPU support:

```bash
modal deploy modal_app.py
```

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
└── mesh.obj              # Surface mesh
```

## Performance Targets

- DICOM upload: < 2s for typical datasets
- Full pipeline: < 15s for 512×512×200 volumes
- Memory-efficient: Uses memory-mapped arrays for large volumes

## License

Research and educational use only. Not certified for clinical use.
