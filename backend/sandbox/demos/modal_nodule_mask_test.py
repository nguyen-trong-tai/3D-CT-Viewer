"""
Standalone Modal entrypoints for testing the sandbox nodule mask pipeline.

Usage examples:

1. Test an already-uploaded case:
   modal run backend/sandbox/modal_nodule_mask_test.py::main --case-id <case_id>

2. Test raw data already uploaded to the `data_raw` Modal volume:
   modal run backend/sandbox/modal_nodule_mask_test.py::main --volume-path dataset/3000522.000000-NA-04919

3. Save the returned JSON locally as well:
   modal run backend/sandbox/modal_nodule_mask_test.py::main --volume-path <path-in-data-raw> --output-path backend/sandbox/nodule_mask_result.json
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

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

APP_NAME = "sandbox-nodule-mask-pipeline"
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


def _relative_output_path(path: Path) -> str:
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(Path(OUTPUT_PATH).resolve()).as_posix()
    except ValueError:
        return resolved_path.as_posix()


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


def _build_output_dir(source_tag: str) -> Path:
    output_dir = Path(OUTPUT_PATH) / "nodule-mask" / _sanitize_path_fragment(source_tag)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


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
    return np.asarray(image, dtype=np.uint8)


def _compute_mask_outline(mask_2d: np.ndarray) -> np.ndarray:
    mask_bool = np.asarray(mask_2d, dtype=bool)
    if not mask_bool.any():
        return np.zeros_like(mask_bool, dtype=bool)

    padded = np.pad(mask_bool, 1, mode="constant", constant_values=False)
    neighbor_count = np.zeros_like(mask_bool, dtype=np.uint8)
    for row_offset in (-1, 0, 1):
        for col_offset in (-1, 0, 1):
            if row_offset == 0 and col_offset == 0:
                continue
            neighbor_count += padded[
                1 + row_offset:1 + row_offset + mask_bool.shape[0],
                1 + col_offset:1 + col_offset + mask_bool.shape[1],
            ]
    return mask_bool & (neighbor_count < 8)


def _draw_mask_overlay(image_uint8: np.ndarray, mask_2d: np.ndarray, output_path: Path) -> None:
    from PIL import Image

    mask_bool = np.asarray(mask_2d, dtype=bool)
    base = Image.fromarray(image_uint8, mode="L").convert("RGBA")
    overlay = np.zeros((mask_bool.shape[0], mask_bool.shape[1], 4), dtype=np.uint8)
    overlay[mask_bool] = np.array([255, 64, 64, 140], dtype=np.uint8)

    outline = _compute_mask_outline(mask_bool)
    if outline.any():
        overlay[outline] = np.array([255, 230, 64, 255], dtype=np.uint8)

    blended = Image.alpha_composite(base, Image.fromarray(overlay, mode="RGBA"))
    blended.convert("RGB").save(output_path)


def _compose_mask_overlay_rgb(image_uint8: np.ndarray, mask_2d: np.ndarray) -> np.ndarray:
    from PIL import Image

    mask_bool = np.asarray(mask_2d, dtype=bool)
    base = Image.fromarray(image_uint8, mode="L").convert("RGBA")
    overlay = np.zeros((mask_bool.shape[0], mask_bool.shape[1], 4), dtype=np.uint8)
    overlay[mask_bool] = np.array([255, 64, 64, 140], dtype=np.uint8)

    outline = _compute_mask_outline(mask_bool)
    if outline.any():
        overlay[outline] = np.array([255, 230, 64, 255], dtype=np.uint8)

    blended = Image.alpha_composite(base, Image.fromarray(overlay, mode="RGBA"))
    return np.asarray(blended.convert("RGB"), dtype=np.uint8)


def _draw_mask_only(mask_2d: np.ndarray, output_path: Path) -> None:
    from PIL import Image

    mask_bool = np.asarray(mask_2d, dtype=bool)
    canvas = np.zeros((mask_bool.shape[0], mask_bool.shape[1], 3), dtype=np.uint8)
    canvas[mask_bool] = np.array([255, 64, 64], dtype=np.uint8)

    outline = _compute_mask_outline(mask_bool)
    if outline.any():
        canvas[outline] = np.array([255, 230, 64], dtype=np.uint8)

    Image.fromarray(canvas, mode="RGB").save(output_path)


def _compose_mask_only_rgb(mask_2d: np.ndarray) -> np.ndarray:
    mask_bool = np.asarray(mask_2d, dtype=bool)
    canvas = np.zeros((mask_bool.shape[0], mask_bool.shape[1], 3), dtype=np.uint8)
    canvas[mask_bool] = np.array([255, 64, 64], dtype=np.uint8)

    outline = _compute_mask_outline(mask_bool)
    if outline.any():
        canvas[outline] = np.array([255, 230, 64], dtype=np.uint8)
    return canvas


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


def _visualize_final_mask_contact_sheet(
    output_dir: Path,
    volume_xyz: np.ndarray,
    final_mask_xyz: np.ndarray,
    output_subdir: str = "final_mask_views",
    stem_prefix: str = "axial_stack",
) -> dict[str, Any]:
    mask_bool = np.asarray(final_mask_xyz, dtype=bool)
    occupied_z = np.where(mask_bool.any(axis=(0, 1)))[0]
    if occupied_z.size == 0:
        return {
            "present": False,
            "slice_count": 0,
            "z_indices": [],
        }

    final_dir = output_dir / output_subdir
    final_dir.mkdir(parents=True, exist_ok=True)
    z_indices = [int(value) for value in occupied_z.tolist()]

    overlay_tiles = [
        _compose_mask_overlay_rgb(
            _window_hu_to_uint8(volume_xyz[:, :, z_index].T),
            np.asarray(final_mask_xyz[:, :, z_index].T, dtype=np.uint8),
        )
        for z_index in z_indices
    ]
    overlay_sheet_path = final_dir / f"{stem_prefix}_overlay_contact_sheet.png"
    _save_contact_sheet_rgb(overlay_tiles, overlay_sheet_path, tile_label_values=z_indices)

    mask_only_tiles = [
        _compose_mask_only_rgb(np.asarray(final_mask_xyz[:, :, z_index].T, dtype=np.uint8))
        for z_index in z_indices
    ]
    mask_only_sheet_path = final_dir / f"{stem_prefix}_mask_only_contact_sheet.png"
    _save_contact_sheet_rgb(mask_only_tiles, mask_only_sheet_path, tile_label_values=z_indices)

    return {
        "present": True,
        "slice_count": int(len(z_indices)),
        "z_indices": z_indices,
        "axial_stack_overlay_contact_sheet": _relative_output_path(overlay_sheet_path),
        "axial_stack_mask_only_contact_sheet": _relative_output_path(mask_only_sheet_path),
    }


def _probability_to_heatmap(probability_2d: np.ndarray) -> np.ndarray:
    prob = np.clip(np.asarray(probability_2d, dtype=np.float32), 0.0, 1.0)
    heatmap = np.zeros((prob.shape[0], prob.shape[1], 3), dtype=np.uint8)
    heatmap[..., 0] = np.rint(255.0 * prob).astype(np.uint8)
    heatmap[..., 1] = np.rint(220.0 * np.sqrt(prob)).astype(np.uint8)
    heatmap[..., 2] = np.rint(96.0 * (1.0 - prob)).astype(np.uint8)
    return heatmap


def _draw_probability_map(probability_2d: np.ndarray, output_path: Path) -> None:
    from PIL import Image

    Image.fromarray(_probability_to_heatmap(probability_2d), mode="RGB").save(output_path)


def _draw_probability_overlay(
    image_uint8: np.ndarray,
    probability_2d: np.ndarray,
    output_path: Path,
    threshold: float,
) -> None:
    from PIL import Image

    prob = np.clip(np.asarray(probability_2d, dtype=np.float32), 0.0, 1.0)
    base = Image.fromarray(image_uint8, mode="L").convert("RGBA")
    heatmap = _probability_to_heatmap(prob)
    alpha = np.rint(prob * 224.0).astype(np.uint8)
    overlay = np.dstack([heatmap, alpha])

    outline = _compute_mask_outline(prob >= float(threshold))
    if outline.any():
        overlay[outline] = np.array([255, 230, 64, 255], dtype=np.uint8)

    blended = Image.alpha_composite(base, Image.fromarray(overlay, mode="RGBA"))
    blended.convert("RGB").save(output_path)


def _compose_probability_overlay_rgb(
    image_uint8: np.ndarray,
    probability_2d: np.ndarray,
    threshold: float,
) -> np.ndarray:
    from PIL import Image

    prob = np.clip(np.asarray(probability_2d, dtype=np.float32), 0.0, 1.0)
    base = Image.fromarray(image_uint8, mode="L").convert("RGBA")
    heatmap = _probability_to_heatmap(prob)
    alpha = np.rint(prob * 224.0).astype(np.uint8)
    overlay = np.dstack([heatmap, alpha])

    outline = _compute_mask_outline(prob >= float(threshold))
    if outline.any():
        overlay[outline] = np.array([255, 230, 64, 255], dtype=np.uint8)

    blended = Image.alpha_composite(base, Image.fromarray(overlay, mode="RGBA"))
    return np.asarray(blended.convert("RGB"), dtype=np.uint8)


def _embed_local_probability_axial(
    full_shape_xy: tuple[int, int],
    raw_probability_xyz: np.ndarray,
    local_bbox_resampled_xyz: list[list[int]],
    z_offset: int,
) -> np.ndarray:
    plane = np.zeros(full_shape_xy, dtype=np.float32)
    (x0, x1), (y0, y1), _ = local_bbox_resampled_xyz
    clipped_offset = int(np.clip(int(z_offset), 0, max(raw_probability_xyz.shape[2] - 1, 0)))
    plane[x0:x1, y0:y1] = np.asarray(raw_probability_xyz[:, :, clipped_offset], dtype=np.float32)
    return plane


def _render_probability_axial_slice(
    resampled_volume_xyz: np.ndarray,
    probability_xyz: np.ndarray,
    local_bbox_resampled_xyz: list[list[int]],
    z_offset: int,
    z_resampled: int,
    threshold: float,
) -> dict[str, Any]:
    plane = _embed_local_probability_axial(
        full_shape_xy=resampled_volume_xyz.shape[:2],
        raw_probability_xyz=probability_xyz,
        local_bbox_resampled_xyz=local_bbox_resampled_xyz,
        z_offset=z_offset,
    )
    return {
        "z_offset": int(z_offset),
        "z_resampled": int(z_resampled),
        "max_probability": float(np.asarray(probability_xyz[:, :, z_offset], dtype=np.float32).max(initial=0.0)),
        "tile_rgb": _compose_probability_overlay_rgb(
            _window_hu_to_uint8(resampled_volume_xyz[:, :, z_resampled].T),
            plane.T,
            threshold=threshold,
        ),
    }


def _visualize_probability_stage_views(
    output_dir: Path,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    pipeline_result: Any,
    probability_key: str,
    output_subdir: str,
    probability_npy_name: str,
) -> list[dict[str, Any]]:
    from sandbox.nodule_mask_pipeline import resample_volume_xyz

    raw_debug_items = list(getattr(pipeline_result, "candidate_debug_volumes", []))
    if not raw_debug_items:
        return []

    target_spacing_xyz = tuple(
        float(value)
        for value in pipeline_result.debug.get("target_spacing_xyz_mm", spacing_xyz_mm)
    )
    resampled_volume_xyz = resample_volume_xyz(
        np.asarray(volume_xyz),
        spacing_xyz=spacing_xyz_mm,
        new_spacing_xyz=target_spacing_xyz,
        order=1,
    ).astype(np.float32, copy=False)
    threshold = float(pipeline_result.debug.get("foreground_threshold", 0.45))

    visualizations_dir = output_dir / output_subdir
    visualizations_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    for item in raw_debug_items:
        probability_value = item.get(probability_key)
        if probability_value is None:
            continue
        probability_xyz = np.asarray(probability_value, dtype=np.float32)
        if probability_xyz.ndim != 3 or probability_xyz.size == 0:
            continue

        bbox = item.get("local_bbox_resampled_xyz")
        if not isinstance(bbox, list) or len(bbox) != 3:
            continue

        candidate_index = int(item.get("candidate_index", len(records) + 1))
        candidate_dir = visualizations_dir / f"candidate_{candidate_index:03d}"
        candidate_dir.mkdir(parents=True, exist_ok=True)

        probability_path = candidate_dir / probability_npy_name
        np.save(probability_path, probability_xyz.astype(np.float32, copy=False))

        center_resampled = np.asarray(item.get("center_xyz_resampled", (0.0, 0.0, 0.0)), dtype=np.float32)
        (_, _), (_, _), (z0, z1) = bbox
        center_z = _clip_index(center_resampled[2], resampled_volume_xyz.shape[2])
        center_z_offset = int(np.clip(center_z - int(z0), 0, max(probability_xyz.shape[2] - 1, 0)))
        best_z_offset = int(np.argmax(probability_xyz.max(axis=(0, 1)))) if probability_xyz.shape[2] > 0 else 0
        best_z = int(np.clip(int(z0) + best_z_offset, 0, resampled_volume_xyz.shape[2] - 1))
        center_artifact = _render_probability_axial_slice(
            resampled_volume_xyz=resampled_volume_xyz,
            probability_xyz=probability_xyz,
            local_bbox_resampled_xyz=bbox,
            z_offset=center_z_offset,
            z_resampled=center_z,
            threshold=threshold,
        )
        best_artifact = _render_probability_axial_slice(
            resampled_volume_xyz=resampled_volume_xyz,
            probability_xyz=probability_xyz,
            local_bbox_resampled_xyz=bbox,
            z_offset=best_z_offset,
            z_resampled=best_z,
            threshold=threshold,
        )

        axial_stack_slices: list[dict[str, Any]] = []
        axial_stack_tiles: list[np.ndarray] = []
        for z_offset in range(probability_xyz.shape[2]):
            z_resampled = int(np.clip(int(z0) + z_offset, 0, resampled_volume_xyz.shape[2] - 1))
            slice_artifact = _render_probability_axial_slice(
                resampled_volume_xyz=resampled_volume_xyz,
                probability_xyz=probability_xyz,
                local_bbox_resampled_xyz=bbox,
                z_offset=z_offset,
                z_resampled=z_resampled,
                threshold=threshold,
            )
            axial_stack_tiles.append(np.asarray(slice_artifact.pop("tile_rgb"), dtype=np.uint8))
            axial_stack_slices.append(slice_artifact)

        axial_stack_path = candidate_dir / "axial_stack_contact_sheet.png"
        _save_contact_sheet_rgb(
            axial_stack_tiles,
            axial_stack_path,
            tile_label_values=[int(item["z_resampled"]) for item in axial_stack_slices],
        )

        records.append(
            {
                "candidate_index": candidate_index,
                "accepted": bool(item.get("accepted", False)),
                "reason": str(item.get("reason", "")),
                "center_xyz_resampled": [float(value) for value in center_resampled],
                "local_bbox_resampled_xyz": bbox,
                "probability_max": float(probability_xyz.max(initial=0.0)),
                "slice_count": int(probability_xyz.shape[2]),
                "center_slice_z_resampled": int(center_z),
                "best_slice_z_resampled": int(best_z),
                "artifacts": {
                    probability_npy_name: _relative_output_path(probability_path),
                    "axial_stack_contact_sheet": _relative_output_path(axial_stack_path),
                    "axial_stack_slices": axial_stack_slices,
                    "center_slice_summary": {
                        "z_offset": int(center_artifact["z_offset"]),
                        "z_resampled": int(center_artifact["z_resampled"]),
                        "max_probability": float(center_artifact["max_probability"]),
                    },
                    "best_slice_summary": {
                        "z_offset": int(best_artifact["z_offset"]),
                        "z_resampled": int(best_artifact["z_resampled"]),
                        "max_probability": float(best_artifact["max_probability"]),
                    },
                },
            }
        )

    return records


def _compute_volume_voxel_count(mask_xyz: np.ndarray) -> int:
    return int(np.asarray(mask_xyz, dtype=np.uint8).sum())


def _compute_volume_mm3(mask_xyz: np.ndarray, spacing_xyz_mm: tuple[float, float, float]) -> float:
    voxel_count = _compute_volume_voxel_count(mask_xyz)
    voxel_volume_mm3 = float(np.prod(np.asarray(spacing_xyz_mm, dtype=np.float32)))
    return float(voxel_count * voxel_volume_mm3)


def _build_quantitative_validation(
    pipeline_result: Any,
    spacing_xyz_mm: tuple[float, float, float],
) -> dict[str, Any]:
    target_spacing_xyz = tuple(
        float(value)
        for value in pipeline_result.debug.get("target_spacing_xyz_mm", (1.0, 1.0, 1.0))
    )
    final_mask_xyz = np.asarray(pipeline_result.final_mask_xyz, dtype=bool)
    final_mask_resampled_xyz = np.asarray(pipeline_result.final_mask_resampled_xyz, dtype=bool)
    lung_mask_xyz = np.asarray(pipeline_result.lung_mask_xyz, dtype=bool)
    lung_mask_resampled_xyz = np.asarray(pipeline_result.lung_mask_resampled_xyz, dtype=bool)
    probability_volume = np.asarray(pipeline_result.probability_volume_resampled_xyz, dtype=np.float32)

    candidate_records = list(getattr(pipeline_result, "candidates", []) or [])
    accepted_candidates = [record for record in candidate_records if bool(record.get("accepted", False))]
    accepted_candidate_indices = [
        int(record.get("candidate_index", index + 1))
        for index, record in enumerate(accepted_candidates)
    ]
    rejected_reasons: dict[str, int] = {}
    for record in candidate_records:
        if bool(record.get("accepted", False)):
            continue
        reason = str(record.get("reason", "unknown"))
        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1

    final_mask_inside_lung_original = int((final_mask_xyz & lung_mask_xyz).sum())
    final_mask_inside_lung_resampled = int((final_mask_resampled_xyz & lung_mask_resampled_xyz).sum())
    final_mask_voxel_count = int(final_mask_xyz.sum())
    final_mask_resampled_voxel_count = int(final_mask_resampled_xyz.sum())
    final_mask_outside_lung_original = final_mask_voxel_count - final_mask_inside_lung_original
    final_mask_outside_lung_resampled = final_mask_resampled_voxel_count - final_mask_inside_lung_resampled

    component_stats = list(getattr(pipeline_result, "component_stats", []) or [])
    largest_component_mm3 = max((float(item.get("volume_mm3", 0.0)) for item in component_stats), default=0.0)
    probability_nonzero = probability_volume[probability_volume > 0.0]

    accepted_probability_peaks: list[float] = []
    accepted_filtered_voxels: list[int] = []
    accepted_center_covered = 0
    for record in accepted_candidates:
        local_stats = dict(record.get("local_stats", {}) or {})
        accepted_probability_peaks.append(float(local_stats.get("max_probability", 0.0)))
        accepted_filtered_voxels.append(int(local_stats.get("grown_voxel_count", 0)))

        center = np.asarray(record.get("center_xyz_resampled_rounded", ()), dtype=int)
        if center.shape == (3,) and final_mask_resampled_xyz.size > 0:
            center = np.clip(center, 0, np.asarray(final_mask_resampled_xyz.shape, dtype=int) - 1)
            if bool(final_mask_resampled_xyz[center[0], center[1], center[2]]):
                accepted_center_covered += 1

    return {
        "candidate_flow": {
            "detected_count": int(len(candidate_records)),
            "accepted_count": int(len(accepted_candidates)),
            "rejected_count": int(len(candidate_records) - len(accepted_candidates)),
            "acceptance_rate": (
                float(len(accepted_candidates) / len(candidate_records))
                if candidate_records
                else 0.0
            ),
            "accepted_candidate_indices": accepted_candidate_indices,
            "rejected_reason_counts": rejected_reasons,
        },
        "mask_quality": {
            "component_count": int(len(component_stats)),
            "largest_component_volume_mm3": float(largest_component_mm3),
            "final_mask_volume_mm3": _compute_volume_mm3(final_mask_xyz, spacing_xyz_mm),
            "final_mask_resampled_volume_mm3": _compute_volume_mm3(final_mask_resampled_xyz, target_spacing_xyz),
            "lung_volume_mm3": _compute_volume_mm3(lung_mask_xyz, spacing_xyz_mm),
            "mask_to_lung_volume_ratio": (
                float(final_mask_voxel_count / max(int(lung_mask_xyz.sum()), 1))
            ),
            "outside_lung_voxels_original": int(final_mask_outside_lung_original),
            "outside_lung_ratio_original": (
                float(final_mask_outside_lung_original / final_mask_voxel_count)
                if final_mask_voxel_count > 0
                else 0.0
            ),
            "outside_lung_voxels_resampled": int(final_mask_outside_lung_resampled),
            "outside_lung_ratio_resampled": (
                float(final_mask_outside_lung_resampled / final_mask_resampled_voxel_count)
                if final_mask_resampled_voxel_count > 0
                else 0.0
            ),
        },
        "probability_distribution": {
            "max_probability_resampled": float(probability_volume.max(initial=0.0)),
            "mean_nonzero_probability_resampled": (
                float(probability_nonzero.mean())
                if probability_nonzero.size > 0
                else 0.0
            ),
            "p95_nonzero_probability_resampled": (
                float(np.percentile(probability_nonzero, 95))
                if probability_nonzero.size > 0
                else 0.0
            ),
            "nonzero_voxel_count_resampled": int(probability_nonzero.size),
        },
        "candidate_consistency": {
            "accepted_centers_covered_by_final_mask": int(accepted_center_covered),
            "accepted_center_coverage_rate": (
                float(accepted_center_covered / len(accepted_candidates))
                if accepted_candidates
                else 0.0
            ),
            "accepted_mean_peak_probability": (
                float(np.mean(accepted_probability_peaks))
                if accepted_probability_peaks
                else 0.0
            ),
            "accepted_mean_filtered_voxels": (
                float(np.mean(accepted_filtered_voxels))
                if accepted_filtered_voxels
                else 0.0
            ),
        },
    }


def _serialize_detector_debug_artifacts(output_dir: Path, pipeline_result: Any) -> dict[str, Any]:
    detector_output = getattr(pipeline_result, "detector_output", None)
    if detector_output is None:
        return {}

    detector_dir = output_dir / "detector_debug"
    detector_dir.mkdir(parents=True, exist_ok=True)

    raw_candidates = getattr(detector_output, "raw_candidates_zyx", None)
    post_nms_candidates = getattr(detector_output, "post_nms_candidates_zyx", None)
    selected_candidates = getattr(detector_output, "extras", {}).get("selected_candidates_zyx")
    preprocess = dict(getattr(detector_output, "preprocess", {}) or {})

    metadata_payload = {
        "candidates": list(getattr(detector_output, "candidates", [])),
        "debug": dict(getattr(detector_output, "debug", {})),
        "preprocess": {
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
        },
        "counts": {
            "raw_candidate_count": int(np.asarray(raw_candidates).shape[0]) if raw_candidates is not None else 0,
            "post_nms_candidate_count": int(np.asarray(post_nms_candidates).shape[0]) if post_nms_candidates is not None else 0,
            "selected_candidate_count": int(np.asarray(selected_candidates).shape[0]) if selected_candidates is not None else 0,
            "returned_candidate_count": int(len(getattr(detector_output, "candidates", []))),
        },
    }
    metadata_path = detector_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")
    return {"metadata_json": _relative_output_path(metadata_path)}


def _serialize_segmentor_debug_artifacts(output_dir: Path, pipeline_result: Any) -> list[dict[str, Any]]:
    raw_debug_items = list(getattr(pipeline_result, "candidate_debug_volumes", []))
    if not raw_debug_items:
        return []

    segmentor_dir = output_dir / "segmentor_debug"
    segmentor_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    for item in raw_debug_items:
        candidate_index = int(item.get("candidate_index", len(records) + 1))
        candidate_dir = segmentor_dir / f"candidate_{candidate_index:03d}"
        candidate_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = candidate_dir / "metadata.json"
        filter_debug_summary: dict[str, dict[str, Any]] = {}
        for key, value in dict(item.get("filter_debug", {})).items():
            debug_array = np.asarray(value)
            filter_debug_summary[key] = {
                "shape": [int(dimension) for dimension in debug_array.shape],
                "dtype": str(debug_array.dtype),
                "nonzero_voxel_count": int(np.count_nonzero(debug_array)),
                "max_value": float(debug_array.max(initial=0.0)) if debug_array.size > 0 else 0.0,
            }

        segmentor_slices = list(item.get("segmentor_slices", []))
        z_indices = [int(slice_item.get("z_index_resampled", 0)) for slice_item in segmentor_slices]

        metadata_path.write_text(
            json.dumps(
                {
                    "candidate_index": candidate_index,
                    "accepted": bool(item.get("accepted", False)),
                    "reason": item.get("reason"),
                    "center_xyz": item.get("center_xyz"),
                    "center_xyz_resampled": item.get("center_xyz_resampled"),
                    "local_bbox_resampled_xyz": item.get("local_bbox_resampled_xyz"),
                    "slice_count": len(segmentor_slices),
                    "slice_z_indices_resampled": z_indices,
                    "filter_debug_summary": filter_debug_summary,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        records.append(
            {
                "candidate_index": candidate_index,
                "metadata_json": _relative_output_path(metadata_path),
                "slice_count": len(segmentor_slices),
                "slice_z_indices_resampled": z_indices,
                "filter_debug_summary": filter_debug_summary,
            }
        )

    return records


def _write_mesh_export(payload: Any, output_path: Path) -> None:
    if isinstance(payload, bytes):
        output_path.write_bytes(payload)
        return
    if isinstance(payload, str):
        output_path.write_text(payload, encoding="utf-8")
        return
    if hasattr(payload, "read"):
        output_path.write_bytes(payload.read())
        return
    raise TypeError(f"Unsupported mesh export payload type: {type(payload)!r}")


def _serialize_final_mask_mesh(
    output_dir: Path,
    final_mask_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
) -> dict[str, Any]:
    from processing.mesh import colorize_mesh, compute_mesh_stats, extract_mesh_from_mask

    mask_bool = np.asarray(final_mask_xyz, dtype=bool)
    if not mask_bool.any():
        return {
            "present": False,
            "format": None,
            "path": None,
            "stats": {},
        }

    mesh_dir = output_dir / "final_mask_mesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)

    mesh = extract_mesh_from_mask(mask_bool, spacing=tuple(float(v) for v in spacing_xyz_mm))
    mesh = colorize_mesh(mesh, (255, 96, 96, 255))
    stats = compute_mesh_stats(mesh)

    glb_path = mesh_dir / "final_mask.glb"
    try:
        _write_mesh_export(mesh.export(file_type="glb"), glb_path)
        return {
            "present": True,
            "format": "glb",
            "path": _relative_output_path(glb_path),
            "stats": stats,
        }
    except Exception:
        obj_path = mesh_dir / "final_mask.obj"
        _write_mesh_export(mesh.export(file_type="obj"), obj_path)
        return {
            "present": True,
            "format": "obj",
            "path": _relative_output_path(obj_path),
            "stats": stats,
        }


def _visualize_transattunet_raw_views(
    output_dir: Path,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    pipeline_result: Any,
) -> list[dict[str, Any]]:
    return _visualize_probability_stage_views(
        output_dir=output_dir,
        volume_xyz=volume_xyz,
        spacing_xyz_mm=spacing_xyz_mm,
        pipeline_result=pipeline_result,
        probability_key="raw_probability_xyz",
        output_subdir="transattunet_raw_views",
        probability_npy_name="raw_probability_xyz.npy",
    )


def _visualize_filtered_local_views(
    output_dir: Path,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    pipeline_result: Any,
) -> list[dict[str, Any]]:
    return _visualize_probability_stage_views(
        output_dir=output_dir,
        volume_xyz=volume_xyz,
        spacing_xyz_mm=spacing_xyz_mm,
        pipeline_result=pipeline_result,
        probability_key="filtered_probability_xyz",
        output_subdir="filtered_local_views",
        probability_npy_name="filtered_probability_xyz.npy",
    )


def _visualize_candidates(
    output_dir: Path,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    visualizations_dir = output_dir / "candidate_views"
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

        z_radius_px = max(0, int(math.ceil(radius_mm / max(spacing_z, 1e-6))))
        z_start = max(0, z_index - z_radius_px)
        z_stop = min(volume_xyz.shape[2], z_index + z_radius_px + 1)
        z_indices = list(range(z_start, z_stop))
        if not z_indices:
            z_indices = [z_index]

        axial_stack_tiles = [
            _compose_candidate_box_rgb(
                _window_hu_to_uint8(volume_xyz[:, :, candidate_z].T),
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
                "stack_z_indices": [int(value) for value in z_indices],
                "views": {
                    "axial_stack": _relative_output_path(axial_stack_path),
                },
            }
        )
    return records


def _visualize_final_mask(
    output_dir: Path,
    volume_xyz: np.ndarray,
    final_mask_xyz: np.ndarray,
) -> dict[str, Any]:
    if not np.asarray(final_mask_xyz).any():
        return {
            "present": False,
            "axial_stack": {},
        }

    mask_coords = np.argwhere(final_mask_xyz)
    center_x, center_y, center_z = [int(round(float(value))) for value in mask_coords.mean(axis=0)]
    center_x = _clip_index(center_x, final_mask_xyz.shape[0])
    center_y = _clip_index(center_y, final_mask_xyz.shape[1])
    center_z = _clip_index(center_z, final_mask_xyz.shape[2])

    axial_contact_sheet = _visualize_final_mask_contact_sheet(
        output_dir=output_dir,
        volume_xyz=np.asarray(volume_xyz),
        final_mask_xyz=np.asarray(final_mask_xyz),
    )

    return {
        "present": True,
        "center_xyz": [int(center_x), int(center_y), int(center_z)],
        "axial_stack": axial_contact_sheet,
    }


def _visualize_final_mask_resampled(
    output_dir: Path,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    pipeline_result: Any,
) -> dict[str, Any]:
    from sandbox.nodule_mask_pipeline import resample_volume_xyz

    final_mask_resampled_xyz = np.asarray(pipeline_result.final_mask_resampled_xyz, dtype=bool)
    if not final_mask_resampled_xyz.any():
        return {
            "present": False,
            "axial_stack": {},
        }

    target_spacing_xyz = tuple(
        float(value)
        for value in pipeline_result.debug.get("target_spacing_xyz_mm", spacing_xyz_mm)
    )
    resampled_volume_xyz = resample_volume_xyz(
        np.asarray(volume_xyz),
        spacing_xyz=spacing_xyz_mm,
        new_spacing_xyz=target_spacing_xyz,
        order=1,
    ).astype(np.float32, copy=False)

    occupied_coords = np.argwhere(final_mask_resampled_xyz)
    center_x, center_y, center_z = [int(round(float(value))) for value in occupied_coords.mean(axis=0)]
    center_x = _clip_index(center_x, final_mask_resampled_xyz.shape[0])
    center_y = _clip_index(center_y, final_mask_resampled_xyz.shape[1])
    center_z = _clip_index(center_z, final_mask_resampled_xyz.shape[2])

    axial_contact_sheet = _visualize_final_mask_contact_sheet(
        output_dir=output_dir,
        volume_xyz=np.asarray(resampled_volume_xyz),
        final_mask_xyz=final_mask_resampled_xyz,
        output_subdir="final_mask_resampled_views",
        stem_prefix="axial_stack_resampled",
    )
    return {
        "present": True,
        "center_xyz_resampled": [int(center_x), int(center_y), int(center_z)],
        "axial_stack": axial_contact_sheet,
    }


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


def _save_local_json(output_path: str, payload: dict[str, Any]) -> None:
    resolved = Path(output_path).expanduser()
    if not resolved.is_absolute():
        resolved = (REPO_ROOT / resolved).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[sandbox-modal] Wrote result to {resolved}")


def _build_pipeline(device: str) -> Any:
    from processing.Segmentation import LungSegmenter
    from sandbox.deeplung import DeepLungDetector, DeepLungDetectorConfig
    from sandbox.nodule_mask_pipeline import NoduleMaskPipeline, NoduleMaskPipelineConfig
    from sandbox.transattunet import (
        TransAttUnetPatchSegmenter,
        TransAttUnetPatchSegmenterConfig,
    )

    detector = DeepLungDetector.from_checkpoint(
        "/root/backend/sandbox/checkpoints/detection/DeepLung.ckpt",
        config=DeepLungDetectorConfig(device=device),
    )
    patch_segmenter = TransAttUnetPatchSegmenter.from_checkpoint(
        "/root/backend/sandbox/checkpoints/segmentation/TransAttUnet_v2.pth",
        config=TransAttUnetPatchSegmenterConfig(device=device),
    )
    lung_segmenter = LungSegmenter(
        hu_threshold=-400,
        min_lung_volume=50_000,
        fill_holes=True,
    )
    return NoduleMaskPipeline(
        detector=detector,
        patch_segmenter=patch_segmenter,
        lung_segmenter=lung_segmenter,
        config=NoduleMaskPipelineConfig(),
    )


def _serialize_pipeline_result(
    pipeline_result: Any,
    output_dir: Path,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
) -> dict[str, Any]:
    final_mask_original_path = output_dir / "final_mask_original.npy"
    final_mask_resampled_path = output_dir / "final_mask_resampled.npy"
    lung_mask_path = output_dir / "lung_mask.npy"
    candidates_path = output_dir / "candidates.json"

    np.save(final_mask_original_path, np.asarray(pipeline_result.final_mask_xyz, dtype=np.uint8))
    np.save(final_mask_resampled_path, np.asarray(pipeline_result.final_mask_resampled_xyz, dtype=np.uint8))
    np.save(lung_mask_path, np.asarray(pipeline_result.lung_mask_xyz, dtype=np.uint8))
    candidates_path.write_text(json.dumps(pipeline_result.candidates, indent=2), encoding="utf-8")

    candidate_visualizations = _visualize_candidates(
        output_dir=output_dir,
        volume_xyz=np.asarray(volume_xyz),
        spacing_xyz_mm=spacing_xyz_mm,
        candidates=list(pipeline_result.candidates),
    )
    detector_debug_artifacts = _serialize_detector_debug_artifacts(
        output_dir=output_dir,
        pipeline_result=pipeline_result,
    )
    segmentor_debug_artifacts = _serialize_segmentor_debug_artifacts(
        output_dir=output_dir,
        pipeline_result=pipeline_result,
    )
    final_mask_views = _visualize_final_mask(
        output_dir=output_dir,
        volume_xyz=np.asarray(volume_xyz),
        final_mask_xyz=np.asarray(pipeline_result.final_mask_xyz),
    )
    final_mask_resampled_views = _visualize_final_mask_resampled(
        output_dir=output_dir,
        volume_xyz=np.asarray(volume_xyz),
        spacing_xyz_mm=spacing_xyz_mm,
        pipeline_result=pipeline_result,
    )
    final_mask_mesh = _serialize_final_mask_mesh(
        output_dir=output_dir,
        final_mask_xyz=np.asarray(pipeline_result.final_mask_xyz),
        spacing_xyz_mm=spacing_xyz_mm,
    )
    quantitative_validation = _build_quantitative_validation(
        pipeline_result=pipeline_result,
        spacing_xyz_mm=spacing_xyz_mm,
    )

    payload = {
        "final_mask_voxel_count": int(np.asarray(pipeline_result.final_mask_xyz, dtype=np.uint8).sum()),
        "final_mask_resampled_voxel_count": int(np.asarray(pipeline_result.final_mask_resampled_xyz, dtype=np.uint8).sum()),
        "lung_mask_voxel_count": int(np.asarray(pipeline_result.lung_mask_xyz, dtype=np.uint8).sum()),
        "component_stats": pipeline_result.component_stats,
        "candidates": pipeline_result.candidates,
        "debug": pipeline_result.debug,
        "validation": quantitative_validation,
        "artifacts": {
            "output_volume_name": "sandbox-output",
            "output_mount_path": OUTPUT_PATH,
            "run_dir": str(output_dir),
            "run_dir_relative": _relative_output_path(output_dir),
            "result_json": _relative_output_path(output_dir / "result.json"),
            "final_mask_original_npy": _relative_output_path(final_mask_original_path),
            "final_mask_resampled_npy": _relative_output_path(final_mask_resampled_path),
            "lung_mask_npy": _relative_output_path(lung_mask_path),
            "candidates_json": _relative_output_path(candidates_path),
            "candidate_visualizations": candidate_visualizations,
            "detector_debug": detector_debug_artifacts,
            "segmentor_debug": segmentor_debug_artifacts,
            "final_mask_views": final_mask_views,
            "final_mask_resampled_views": final_mask_resampled_views,
            "final_mask_mesh": final_mask_mesh,
        },
    }
    return payload


def _attach_output_artifacts(
    pipeline_result: Any,
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    source_tag: str,
) -> dict[str, Any]:
    if os.path.exists(OUTPUT_PATH):
        output_volume.reload()

    output_dir = _build_output_dir(source_tag)
    payload = _serialize_pipeline_result(
        pipeline_result=pipeline_result,
        output_dir=output_dir,
        volume_xyz=volume_xyz,
        spacing_xyz_mm=spacing_xyz_mm,
    )
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if os.path.exists(OUTPUT_PATH):
        output_volume.commit()
    return payload


def _run_pipeline_on_volume(
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    source_tag: str,
    provided_lung_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    pipeline = _build_pipeline(device="cuda")
    pipeline_result = pipeline.run(
        volume_hu_xyz=np.asarray(volume_xyz),
        spacing_xyz_mm=spacing_xyz_mm,
        lung_mask_xyz=provided_lung_mask,
    )
    payload = _attach_output_artifacts(
        pipeline_result=pipeline_result,
        volume_xyz=np.asarray(volume_xyz),
        spacing_xyz_mm=spacing_xyz_mm,
        source_tag=source_tag,
    )
    payload["runtime"] = "modal_gpu"
    payload["gpu"] = "A10G"
    return payload


@app.function(
    image=image,
    volumes=SANDBOX_VOLUMES,
    timeout=1800,
    startup_timeout=900,
    retries=1,
    scaledown_window=300,
    gpu="A10G",
)
def run_case_remote(
    case_id: str,
    use_existing_mask: bool = True,
) -> dict[str, Any]:
    if os.path.exists(DATA_PATH):
        data_volume.reload()

    _configure_runtime()

    from api.dependencies import get_repository, reset_dependencies

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

    payload = _run_pipeline_on_volume(
        volume_xyz=np.asarray(volume),
        spacing_xyz_mm=tuple(float(value) for value in metadata.get("spacing", (1.0, 1.0, 1.0))),
        source_tag=f"case-{case_id}",
        provided_lung_mask=np.asarray(lung_mask).astype(bool) if lung_mask is not None else None,
    )
    payload["case_id"] = case_id
    payload["used_existing_mask"] = used_existing_mask
    return payload


@app.function(
    image=image,
    volumes=SANDBOX_VOLUMES,
    timeout=1800,
    startup_timeout=900,
    retries=1,
    scaledown_window=300,
    gpu="A10G",
)
def run_volume_remote(
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
) -> dict[str, Any]:
    return _run_pipeline_on_volume(
        volume_xyz=np.asarray(volume_xyz),
        spacing_xyz_mm=spacing_xyz_mm,
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
def run_volume_from_raw_remote(volume_path: str) -> dict[str, Any]:
    if os.path.exists(RAW_DATA_PATH):
        raw_data_volume.reload()

    resolved_volume_path = _normalize_volume_path(volume_path)
    volume_xyz, spacing_xyz_mm = _load_volume_from_filesystem_path(resolved_volume_path)
    payload = _run_pipeline_on_volume(
        volume_xyz=volume_xyz,
        spacing_xyz_mm=tuple(float(value) for value in spacing_xyz_mm),
        source_tag=Path(str(resolved_volume_path).rstrip("/\\")).name or "raw-volume",
    )
    payload["volume_path"] = volume_path
    payload["resolved_volume_path"] = str(resolved_volume_path)
    payload["data_source"] = "data_raw_volume"
    result_json_relative = payload.get("artifacts", {}).get("result_json")
    if result_json_relative:
        result_json_path = Path(OUTPUT_PATH) / result_json_relative
        result_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if os.path.exists(OUTPUT_PATH):
            output_volume.commit()
    return payload


@app.local_entrypoint()
def main(
    volume_path: str = "",
    output_path: str = "",
    use_existing_mask: bool = True,
):
    if volume_path:
        result = run_volume_from_raw_remote.remote(volume_path=volume_path)
    else:
        #run all volume
        data_path = Path(RAW_DATA_PATH/"Dicoms")
        for patients in data_path.iterdir():
            if patients.is_dir():
                for case in patients.iterdir():
                    if case.is_dir():
                        print(f"Processing case: {case.name}")
                        result = run_volume_from_raw_remote.remote(volume_path=str(case))
                    else:
                        print(f"Skipping non-directory entry: {case}")
            else:
                print(f"Skipping non-directory entry: {patients}")
    if output_path:
        _save_local_json(output_path, result)
