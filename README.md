# ViewR CT

ViewR CT is a research and educational monorepo for turning CT studies into interactive 2D and 3D visualizations. The system supports uploading DICOM or NIfTI data, building a normalized CT volume, running a processing pipeline, storing intermediate artifacts per case, and rendering the result in a web UI.

## Disclaimer

This project is for research, prototyping, and education only. It is not intended for clinical diagnosis or treatment.

## What The System Does

- Upload single archives (`.zip`) or NIfTI volumes (`.nii`, `.nii.gz`)
- Upload large DICOM folders through direct API relay or chunked batch upload
- Convert source data into a canonical CT volume plus metadata
- Run a backend pipeline: `load_volume -> segmentation -> sdf -> mesh`
- Persist intermediate artifacts such as CT preview volumes, masks, SDFs, and meshes
- Visualize axial/coronal/sagittal views and a 3D mesh in the frontend
- Support local/shared-volume execution and distributed execution with Redis + Cloudflare R2

## Repository Layout

```text
viewr_ct/
|- frontend/          React + Vite application
|- backend/           FastAPI API, processing pipeline, storage, workers
|- docs/              System and architecture documentation
|- data/              Local case/artifact storage in shared-volume mode
|- dataset/           Sample or working datasets
`- README.md          This file
```

## High-Level Architecture

The project is organized into four main layers:

1. Frontend
   React renders the upload flow, progress UI, 2D viewers, MPR interactions, and 3D mesh viewer.
2. Backend API
   FastAPI exposes case-centric endpoints for upload, status, metadata, artifacts, and pipeline control.
3. Processing pipeline
   Python services transform CT data into segmentation masks, SDF volumes, and meshes.
4. Storage and runtime
   The app can run with local/shared-volume storage or with Redis for operational state plus Cloudflare R2 for binary artifacts.

## Runtime Modes

### Shared-volume mode

This is the default fallback mode for local development.

- Case artifacts are stored on the filesystem under `backend` storage paths
- Operational state can fall back to in-memory storage
- Modal workers, when used, rely on shared-volume reload/commit behavior

### Distributed mode

This mode is active when both Redis and Cloudflare R2 are configured and distributed runtime is not disabled.

- Redis stores case status, pipeline stage state, upload batch sessions, and locks
- R2 stores binary artifacts such as volume files, preview volumes, masks, SDFs, and meshes
- The frontend can use direct object-store upload/download URLs for better remote performance

### Strictness

`DISTRIBUTED_RUNTIME_MODE` controls runtime behavior:

- `auto`: use distributed services when available, otherwise fall back
- `required`: fail startup if Redis or R2 is unavailable
- `disabled`: always use shared-volume/local behavior

## Main User Flow

```text
Upload CT data
-> backend builds a case
-> CT volume + metadata are saved
-> processing pipeline runs asynchronously
-> artifacts become available per stage
-> frontend loads preview/full data for 2D viewing
-> frontend loads mesh for 3D viewing
```

## Quick Start

### Requirements

- Python 3.11+
- Node.js 18+
- npm
- Optional: Modal account for cloud workers
- Optional: Redis + Cloudflare R2 for distributed runtime

### Backend

```bash
cd backend
python -m venv .venv
# PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
# source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Backend URLs:

- API root: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

### Frontend

Set the frontend API target in `frontend/.env`:

```bash
VITE_API_URL=http://localhost:8000
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server is typically available at `http://localhost:5173`.

## Optional Distributed Runtime Setup

To enable distributed execution, configure the backend with Redis and Cloudflare R2 credentials. The most important environment variables are:

```bash
REDIS_URL=...
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
R2_PUBLIC_BASE_URL=...
DISTRIBUTED_RUNTIME_MODE=auto
```

Useful optional tuning variables include:

- `UPLOAD_URL_TTL_SECONDS`
- `ARTIFACT_URL_TTL_SECONDS`
- `MESH_URL_TTL_SECONDS`
- `DIRECT_UPLOAD_CONCURRENCY`
- `CASE_RETENTION_SECONDS`

## Modal Deployment

The backend contains a Modal app definition for background workers and cloud deployment:

```bash
cd backend
modal deploy modal_app.py
```

## Current Scope

This repository is currently focused on:

- research and demo workflows
- case-based upload/process/view loops
- deterministic baseline segmentation and geometry extraction
- performance-oriented artifact delivery for browser visualization

It is not yet focused on:

- clinical-grade workflows
- authentication and authorization
- multi-tenant governance
- production observability and job orchestration at enterprise scale

## License And Usage

Research and educational use only. Review the disclaimer above before sharing or deploying the system.
