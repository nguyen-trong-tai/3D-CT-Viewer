# CT-to-3D Medical Imaging Demo Platform

This project demonstrates the end-to-end pipeline from CT medical images to a 3D reconstructed model. It is a research and educational demo web application.

## Disclaimer
**This system is for research and educational demonstration only. It is not intended for clinical diagnosis.**

## Architecture
The system is a monorepo containing:
- **frontend/**: React + Vite application for visualization.
- **backend/**: FastAPI + Python 3.11 service, deployable on Modal.

## Getting Started

### Backend
Navigate to the `backend/` directory:
```bash
cd backend
pip install -r requirements.txt
python main.py
```

### Frontend
Navigate to the `frontend/` directory:
```bash
cd frontend
npm install
npm run dev
```
