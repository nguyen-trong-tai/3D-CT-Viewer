"""
Standalone Modal entrypoints for testing the DeepLung detector in the sandbox.

Usage examples:

1. Test an already-uploaded case:
   modal run backend/sandbox/modal_deeplung_test.py::main --case-id <case_id>

2. Test raw data already uploaded to the `data_raw` Modal volume:
   modal run backend/sandbox/modal_deeplung_test.py::main --volume-path dataset/3000522.000000-NA-04919

3. Save the returned JSON locally as well:
   modal run backend/sandbox/modal_deeplung_test.py::main --volume-path <path-in-data-raw> --output-path backend/sandbox/deeplung_result.json
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import modal
import numpy as np


CURRENT_FILE = Path(__file__).resolve()

if (CURRENT_FILE.parent / "checkpoints").exists() and CURRENT_FILE.parent.name == "sandbox":
    BACKEND_ROOT = CURRENT_FILE.parents[1]
    REPO_ROOT = BACKEND_ROOT.parent
elif Path("/root/backend").exists():
    BACKEND_ROOT = Path("/root/backend")
    REPO_ROOT = BACKEND_ROOT.parent
else:
    try:
        REPO_ROOT = CURRENT_FILE.parents[3]
        BACKEND_ROOT = REPO_ROOT / "backend"
    except IndexError:
        BACKEND_ROOT = CURRENT_FILE.parent
        REPO_ROOT = BACKEND_ROOT.parent

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

APP_NAME = "sandbox-deeplung-detector"
DATA_PATH = "/data"
RAW_DATA_PATH = "/data_raw"
OUTPUT_PATH = "/sandbox_output"
WORKER_TEMP_PATH = "/tmp/viewr_ct"
WORKER_STORAGE_ROOT = f"{WORKER_TEMP_PATH}/cases"
SHARED_TEMP_PATH = f"{DATA_PATH}/temp"

app = modal.App(APP_NAME)
data_volume = modal.Volume.from_name("ct-data", create_if_missing=True)
raw_data_volume = modal.Volume.from_name("data_raw", create_if_missing=False)
output_volume = modal.Volume.from_name("sandbox-output", create_if_missing=True)

def _ignore_local_path(path: str | Path) -> bool:
    path = Path(path)
    blocked = {"venv", ".venv", "__pycache__", ".git", ".idea", ".vscode"}
    return any(part in blocked for part in path.parts)


image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "trimesh",
        "torch",
        "numpy",
        "scipy",
        "scikit-image",
        "Pillow",
        "pydicom",
        "nibabel",
        "SimpleITK",
        "modal>=0.55.0",
        "pydantic>=2.0",
        "redis>=5.0.0",
        "boto3>=1.34.0",
    )
    .add_local_dir(
        local_path=str(BACKEND_ROOT),
        remote_path="/root/backend",
        ignore=_ignore_local_path,
    )
)

SANDBOX_VOLUMES = {
    DATA_PATH: data_volume,
    RAW_DATA_PATH: raw_data_volume,
    OUTPUT_PATH: output_volume,
}


def _configure_runtime() -> None:
    from config import settings

    os.environ["STORAGE_ROOT"] = DATA_PATH if os.path.exists(DATA_PATH) else WORKER_STORAGE_ROOT
    os.environ["TEMP_STORAGE_ROOT"] = SHARED_TEMP_PATH if os.path.exists(DATA_PATH) else WORKER_TEMP_PATH
    settings.refresh_from_env()


def _sanitize_path_fragment(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    sanitized = sanitized.strip("._-")
    return sanitized or "unnamed"


def _window_hu_to_uint8(slice_hu: np.ndarray) -> np.ndarray:
    window_low = -1200.0
    window_high = 600.0
    normalized = (np.asarray(slice_hu, dtype=np.float32) - window_low) / (window_high - window_low)
    normalized = np.clip(normalized, 0.0, 1.0)
    return np.rint(normalized * 255.0).astype(np.uint8)


def _clip_index(value: float, upper_bound: int) -> int:
    if upper_bound <= 0:
        return 0
    return int(np.clip(int(round(float(value))), 0, upper_bound - 1))


def _draw_candidate_box(
    image_uint8: np.ndarray,
    center_col: float,
    center_row: float,
    half_width_px: float,
    half_height_px: float,
    output_path: Path,
) -> None:
    from PIL import Image, ImageDraw

    image = Image.fromarray(image_uint8, mode="L").convert("RGB")
    draw = ImageDraw.Draw(image)

    left = max(0.0, center_col - half_width_px)
    top = max(0.0, center_row - half_height_px)
    right = min(float(image.width - 1), center_col + half_width_px)
    bottom = min(float(image.height - 1), center_row + half_height_px)

    line_width = max(2, int(round(min(image.size) * 0.008)))
    color = (255, 64, 64)
    draw.rectangle((left, top, right, bottom), outline=color, width=line_width)

    crosshair = max(6, int(round(min(image.size) * 0.02)))
    draw.line((center_col - crosshair, center_row, center_col + crosshair, center_row), fill=color, width=line_width)
    draw.line((center_col, center_row - crosshair, center_col, center_row + crosshair), fill=color, width=line_width)
    image.save(output_path)


def _compose_candidate_box_rgb(
    image_uint8: np.ndarray,
    center_col: float,
    center_row: float,
    half_width_px: float,
    half_height_px: float,
) -> np.ndarray:
    from PIL import Image, ImageDraw

    image = Image.fromarray(image_uint8, mode="L").convert("RGB")
    draw = ImageDraw.Draw(image)

    left = max(0.0, center_col - half_width_px)
    top = max(0.0, center_row - half_height_px)
    right = min(float(image.width - 1), center_col + half_width_px)
    bottom = min(float(image.height - 1), center_row + half_height_px)

    line_width = max(2, int(round(min(image.size) * 0.008)))
    color = (255, 64, 64)
    draw.rectangle((left, top, right, bottom), outline=color, width=line_width)

    crosshair = max(6, int(round(min(image.size) * 0.02)))
    draw.line((center_col - crosshair, center_row, center_col + crosshair, center_row), fill=color, width=line_width)
    draw.line((center_col, center_row - crosshair, center_col, center_row + crosshair), fill=color, width=line_width)
    return np.asarray(image, dtype=np.uint8)


def _save_contact_sheet_rgb(
    tiles_rgb: list[np.ndarray],
    output_path: Path,
    tile_label_values: list[int] | None = None,
) -> None:
    from PIL import Image, ImageDraw

    if not tiles_rgb:
        raise ValueError("Cannot build contact sheet without tiles")

    first = np.asarray(tiles_rgb[0], dtype=np.uint8)
    tile_height, tile_width = int(first.shape[0]), int(first.shape[1])
    columns = max(1, int(math.ceil(math.sqrt(len(tiles_rgb)))))
    rows = int(math.ceil(len(tiles_rgb) / columns))
    label_height = 18 if tile_label_values is not None else 0
    canvas = np.zeros((rows * (tile_height + label_height), columns * tile_width, 3), dtype=np.uint8)

    for index, tile in enumerate(tiles_rgb):
        row = index // columns
        col = index % columns
        y0 = row * (tile_height + label_height)
        x0 = col * tile_width
        if label_height:
            canvas[y0:y0 + label_height, x0:x0 + tile_width] = np.array([24, 24, 24], dtype=np.uint8)
        canvas[y0 + label_height:y0 + label_height + tile_height, x0:x0 + tile_width] = np.asarray(tile, dtype=np.uint8)

    image = Image.fromarray(canvas, mode="RGB")
    if tile_label_values is not None:
        draw = ImageDraw.Draw(image)
        for index, label_value in enumerate(tile_label_values):
            row = index // columns
            col = index % columns
            x0 = col * tile_width + 4
            y0 = row * (tile_height + label_height) + 2
            draw.text((x0, y0), f"z={int(label_value)}", fill=(255, 255, 255))
    image.save(output_path)


def _build_output_dir(source_tag: str) -> Path:
    output_dir = Path(OUTPUT_PATH) / "deeplung" / _sanitize_path_fragment(source_tag)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _relative_output_path(path: Path) -> str:
    return path.relative_to(Path(OUTPUT_PATH)).as_posix()


def _visualize_candidates(
    output_dir: Path,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    visualizations_dir = output_dir / "visualizations"
    visualizations_dir.mkdir(parents=True, exist_ok=True)

    spacing_x, spacing_y, spacing_z = [float(value) for value in spacing_xyz_mm]
    records: list[dict[str, Any]] = []

    for rank, candidate in enumerate(candidates, start=1):
        center_xyz = candidate.get("center_xyz", [0.0, 0.0, 0.0])
        center_x = float(center_xyz[0])
        center_y = float(center_xyz[1])
        center_z = float(center_xyz[2])
        x_index = _clip_index(center_x, volume_xyz.shape[0])
        y_index = _clip_index(center_y, volume_xyz.shape[1])
        z_index = _clip_index(center_z, volume_xyz.shape[2])

        diameter_mm = max(1.0, float(candidate.get("diameter_mm", 1.0)))
        radius_mm = diameter_mm / 2.0

        candidate_dir = visualizations_dir / f"candidate_{rank:03d}"
        candidate_dir.mkdir(parents=True, exist_ok=True)

        axial = _window_hu_to_uint8(volume_xyz[:, :, z_index].T)
        axial_path = candidate_dir / "axial.png"
        _draw_candidate_box(
            image_uint8=axial,
            center_col=center_x,
            center_row=center_y,
            half_width_px=radius_mm / max(spacing_x, 1e-6),
            half_height_px=radius_mm / max(spacing_y, 1e-6),
            output_path=axial_path,
        )

        coronal = _window_hu_to_uint8(volume_xyz[:, y_index, :].T)
        coronal_path = candidate_dir / "coronal.png"
        _draw_candidate_box(
            image_uint8=coronal,
            center_col=center_x,
            center_row=center_z,
            half_width_px=radius_mm / max(spacing_x, 1e-6),
            half_height_px=radius_mm / max(spacing_z, 1e-6),
            output_path=coronal_path,
        )

        sagittal = _window_hu_to_uint8(volume_xyz[x_index, :, :].T)
        sagittal_path = candidate_dir / "sagittal.png"
        _draw_candidate_box(
            image_uint8=sagittal,
            center_col=center_y,
            center_row=center_z,
            half_width_px=radius_mm / max(spacing_y, 1e-6),
            half_height_px=radius_mm / max(spacing_z, 1e-6),
            output_path=sagittal_path,
        )

        z_radius_px = max(0, int(math.ceil(radius_mm / max(spacing_z, 1e-6))))
        z_start = max(0, z_index - z_radius_px)
        z_stop = min(volume_xyz.shape[2], z_index + z_radius_px + 1)
        z_indices = list(range(z_start, z_stop))
        if not z_indices:
            z_indices = [z_index]

        axial_stack_tiles = [
            _compose_candidate_box_rgb(
                image_uint8=_window_hu_to_uint8(volume_xyz[:, :, candidate_z].T),
                center_col=center_x,
                center_row=center_y,
                half_width_px=radius_mm / max(spacing_x, 1e-6),
                half_height_px=radius_mm / max(spacing_y, 1e-6),
            )
            for candidate_z in z_indices
        ]
        axial_stack_path = candidate_dir / "axial_stack_contact_sheet.png"
        _save_contact_sheet_rgb(axial_stack_tiles, axial_stack_path, tile_label_values=z_indices)

        records.append(
            {
                "rank": rank,
                "score_logit": float(candidate.get("score_logit", 0.0)),
                "score_probability": float(candidate.get("score_probability", 0.0)),
                "center_xyz": [center_x, center_y, center_z],
                "center_xyz_rounded": [x_index, y_index, z_index],
                "diameter_mm": diameter_mm,
                "stack_z_indices": [int(value) for value in z_indices],
                "views": {
                    "axial": _relative_output_path(axial_path),
                    "axial_stack": _relative_output_path(axial_stack_path),
                    "coronal": _relative_output_path(coronal_path),
                    "sagittal": _relative_output_path(sagittal_path),
                },
            }
        )

    return records


def _attach_output_artifacts(
    result: dict[str, Any],
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    source_tag: str,
) -> dict[str, Any]:
    if os.path.exists(OUTPUT_PATH):
        output_volume.reload()

    output_dir = _build_output_dir(source_tag)
    visualization_records = _visualize_candidates(
        output_dir=output_dir,
        volume_xyz=np.asarray(volume_xyz),
        spacing_xyz_mm=spacing_xyz_mm,
        candidates=list(result.get("candidates", [])),
    )

    detector_debug_artifacts = _serialize_detector_debug_artifacts(
        output_dir=output_dir,
        result=result,
    )

    artifacts = {
        "output_volume_name": "sandbox-output",
        "output_mount_path": OUTPUT_PATH,
        "run_dir": str(output_dir),
        "run_dir_relative": _relative_output_path(output_dir),
        "result_json": _relative_output_path(output_dir / "result.json"),
        "visualization_count": len(visualization_records),
        "visualizations": visualization_records,
        "detector_debug": detector_debug_artifacts,
    }
    result["artifacts"] = artifacts

    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if os.path.exists(OUTPUT_PATH):
        output_volume.commit()

    return result


def _serialize_detector_debug_artifacts(output_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    detector_dir = output_dir / "detector_debug"
    detector_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, Any] = {}

    preprocess = dict(result.get("preprocess", {}) or {})
    clean_volume = preprocess.get("clean_volume_zyx")
    if clean_volume is not None:
        clean_volume_path = detector_dir / "clean_volume_zyx.npy"
        np.save(clean_volume_path, np.asarray(clean_volume, dtype=np.uint8))
        artifacts["clean_volume_zyx_npy"] = _relative_output_path(clean_volume_path)

    for key in ("raw_candidates_zyx", "post_nms_candidates_zyx", "selected_candidates_zyx"):
        value = result.get(key)
        if value is None:
            continue
        path = detector_dir / f"{key}.npy"
        array = np.asarray(value, dtype=np.float32)
        np.save(path, array)
        artifacts[f"{key}_npy"] = _relative_output_path(path)
        result[key] = {
            "count": int(array.shape[0]) if array.ndim > 0 else 0,
            "path": _relative_output_path(path),
        }

    preprocess_summary = {
        "clean_volume_zyx": {
            "path": artifacts.get("clean_volume_zyx_npy"),
            "shape": (
                [int(value) for value in np.asarray(clean_volume).shape]
                if clean_volume is not None
                else None
            ),
        },
        "spacing_zyx_mm": (
            np.asarray(preprocess.get("spacing_zyx_mm"), dtype=np.float32).tolist()
            if preprocess.get("spacing_zyx_mm") is not None
            else None
        ),
        "extendbox_zyx": (
            np.asarray(preprocess.get("extendbox_zyx"), dtype=np.int32).tolist()
            if preprocess.get("extendbox_zyx") is not None
            else None
        ),
        "original_shape_zyx": preprocess.get("original_shape_zyx"),
        "resampled_shape_zyx": preprocess.get("resampled_shape_zyx"),
    }
    result["preprocess"] = preprocess_summary

    metadata_path = detector_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "debug": dict(result.get("debug", {})),
                "preprocess": preprocess_summary,
                "candidate_count": len(result.get("candidates", [])),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    artifacts["metadata_json"] = _relative_output_path(metadata_path)
    return artifacts


@app.function(
    image=image,
    volumes=SANDBOX_VOLUMES,
    timeout=1800,
    startup_timeout=900,
    retries=1,
    scaledown_window=300,
    gpu="A10G",
)
def detect_case_remote(
    case_id: str,
    use_existing_mask: bool = True,
    score_threshold: float = -3.0,
    nms_threshold: float = 0.1,
    top_k: int | None = 10,
) -> dict[str, Any]:
    """Run DeepLung on a case already stored by the backend repository."""
    if os.path.exists(DATA_PATH):
        data_volume.reload()

    _configure_runtime()

    from api.dependencies import get_repository, reset_dependencies
    from processing.Segmentation import LungSegmenter
    from sandbox.deeplung import DeepLungDetector, DeepLungDetectorConfig

    reset_dependencies()
    repo = get_repository()

    metadata = repo.load_ct_metadata(case_id)
    if metadata is None:
        raise ValueError(f"Missing CT metadata for case {case_id}")

    volume = repo.load_ct_volume_mmap(case_id)
    if volume is None:
        volume = repo.load_ct_volume(case_id)
    if volume is None:
        raise ValueError(f"Missing CT volume for case {case_id}")

    lung_mask = None
    used_existing_mask = False
    if use_existing_mask and repo.mask_exists(case_id):
        lung_mask = repo.load_mask(case_id)
        used_existing_mask = lung_mask is not None

    if lung_mask is None:
        segmenter = LungSegmenter(
            hu_threshold=-400,
            min_lung_volume=50_000,
            fill_holes=True,
        )
        lung_mask = segmenter.segment(np.asarray(volume))["lung_mask"]

    detector = DeepLungDetector.from_checkpoint(
        "/root/backend/sandbox/checkpoints/detection/DeepLung.ckpt",
        config=DeepLungDetectorConfig(device="cuda"),
    )
    result = detector.detect(
        volume_hu_xyz=np.asarray(volume),
        spacing_xyz_mm=tuple(float(value) for value in metadata.get("spacing", (1.0, 1.0, 1.0))),
        lung_mask_xyz=np.asarray(lung_mask).astype(bool),
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
    )
    result["case_id"] = case_id
    result["used_existing_mask"] = used_existing_mask
    result["runtime"] = "modal_gpu"
    result["gpu"] = "A10G"
    return _attach_output_artifacts(
        result=result,
        volume_xyz=np.asarray(volume),
        spacing_xyz_mm=tuple(float(value) for value in metadata.get("spacing", (1.0, 1.0, 1.0))),
        source_tag=f"case-{case_id}",
    )


def _run_detector_on_volume(
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    score_threshold: float,
    nms_threshold: float,
    top_k: int | None,
    source_tag: str,
) -> dict[str, Any]:
    from processing.Segmentation import LungSegmenter
    from sandbox.deeplung import DeepLungDetector, DeepLungDetectorConfig

    volume_xyz = np.asarray(volume_xyz)
    segmenter = LungSegmenter(
        hu_threshold=-400,
        min_lung_volume=50_000,
        fill_holes=True,
    )
    lung_mask = segmenter.segment(volume_xyz)["lung_mask"]

    detector = DeepLungDetector.from_checkpoint(
        "/root/backend/sandbox/checkpoints/detection/DeepLung.ckpt",
        config=DeepLungDetectorConfig(device="cuda"),
    )
    result = detector.detect(
        volume_hu_xyz=volume_xyz,
        spacing_xyz_mm=spacing_xyz_mm,
        lung_mask_xyz=lung_mask,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
    )
    result["runtime"] = "modal_gpu"
    result["gpu"] = "A10G"
    return _attach_output_artifacts(
        result=result,
        volume_xyz=volume_xyz,
        spacing_xyz_mm=spacing_xyz_mm,
        source_tag=source_tag,
    )


@app.function(
    image=image,
    volumes=SANDBOX_VOLUMES,
    timeout=1800,
    startup_timeout=900,
    retries=1,
    scaledown_window=300,
    gpu="A10G",
)
def detect_volume_remote(
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    score_threshold: float = -3.0,
    nms_threshold: float = 0.1,
    top_k: int | None = 50,
) -> dict[str, Any]:
    """Run DeepLung on an ad-hoc volume loaded locally by the client."""
    return _run_detector_on_volume(
        volume_xyz=volume_xyz,
        spacing_xyz_mm=spacing_xyz_mm,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
        source_tag="adhoc-volume",
    )


@app.function(
    image=image,
    volumes=SANDBOX_VOLUMES,
    timeout=1800,
    startup_timeout=900,
    retries=1,
    scaledown_window=300,
    gpu="A10G",
)
def detect_volume_from_raw_remote(
    volume_path: str,
    score_threshold: float = -3.0,
    nms_threshold: float = 0.1,
    top_k: int | None = 50,
) -> dict[str, Any]:
    """Run DeepLung on raw data mounted from the `data_raw` Modal volume."""
    if os.path.exists(RAW_DATA_PATH):
        raw_data_volume.reload()

    resolved_volume_path = _normalize_volume_path(volume_path)
    volume_xyz, spacing_xyz_mm = _load_volume_from_filesystem_path(resolved_volume_path)
    result = _run_detector_on_volume(
        volume_xyz=volume_xyz,
        spacing_xyz_mm=tuple(float(value) for value in spacing_xyz_mm),
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
        source_tag=Path(str(resolved_volume_path).rstrip("/\\")).name or "raw-volume",
    )
    result["volume_path"] = volume_path
    result["resolved_volume_path"] = str(resolved_volume_path)
    result["data_source"] = "data_raw_volume"
    artifacts = result.get("artifacts", {})
    result_json_relative = artifacts.get("result_json")
    if result_json_relative:
        result_json_path = Path(OUTPUT_PATH) / result_json_relative
        result_json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if os.path.exists(OUTPUT_PATH):
            output_volume.commit()
    return result


def _load_volume_from_filesystem_path(resolved: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    from processing.loader import MedicalVolumeLoader

    if not resolved.exists():
        raise FileNotFoundError(f"Input path does not exist: {resolved}")

    if resolved.is_dir():
        dicom_files = sorted(str(path) for path in resolved.rglob("*.dcm"))
        if not dicom_files:
            raise ValueError(f"No DICOM files found under: {resolved}")
        return MedicalVolumeLoader.load_dicom_from_files(dicom_files)

    lower_name = resolved.name.lower()
    if lower_name.endswith(".nii") or lower_name.endswith(".nii.gz"):
        return MedicalVolumeLoader.load_nifti(str(resolved))

    if lower_name.endswith(".zip"):
        return MedicalVolumeLoader.load_dicom_series(str(resolved))

    if lower_name.endswith(".dcm"):
        return MedicalVolumeLoader.load_dicom_from_files([str(resolved)])

    raise ValueError(f"Unsupported input path for sandbox test: {resolved}")


def _normalize_volume_path(volume_path: str) -> Path:
    resolved = Path(volume_path).expanduser()
    normalized_text = str(resolved).replace("\\", "/")

    if normalized_text == "/__modal/volumes/data_raw":
        return Path(RAW_DATA_PATH).resolve()
    if normalized_text.startswith("/__modal/volumes/data_raw/"):
        suffix = normalized_text.removeprefix("/__modal/volumes/data_raw/").lstrip("/")
        return (Path(RAW_DATA_PATH) / suffix).resolve()
    if normalized_text == RAW_DATA_PATH or normalized_text.startswith(f"{RAW_DATA_PATH}/"):
        return Path(normalized_text).resolve()
    if resolved.is_absolute():
        return resolved.resolve()
    return (Path(RAW_DATA_PATH) / resolved).resolve()


def _load_volume_from_volume_path(volume_path: str) -> tuple[np.ndarray, tuple[float, float, float]]:
    resolved = _normalize_volume_path(volume_path)
    return _load_volume_from_filesystem_path(resolved)


def _save_local_json(output_path: str, payload: dict[str, Any]) -> None:
    resolved = Path(output_path).expanduser()
    if not resolved.is_absolute():
        resolved = (REPO_ROOT / resolved).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[sandbox-modal] Wrote result to {resolved}")


@app.local_entrypoint()
def main(
    case_id: str = "",
    volume_path: str = "",
    output_path: str = "",
    score_threshold: float = -3.0,
    nms_threshold: float = 0.1,
    top_k: int = 10,
    use_existing_mask: bool = True,
):
    """
    Local driver for sandbox testing.

    Provide exactly one of `case_id` or `volume_path`.
    """
    sources = [bool(case_id), bool(volume_path)]
    if sum(sources) != 1:
        raise ValueError("Provide exactly one of `case_id` or `volume_path`.")

    if case_id:
        result = detect_case_remote.remote(
            case_id=case_id,
            use_existing_mask=use_existing_mask,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
        )
    elif volume_path:
        result = detect_volume_from_raw_remote.remote(
            volume_path=volume_path,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
        )

    print(json.dumps(result, indent=2))

    if output_path:
        _save_local_json(output_path, result)
