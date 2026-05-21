"""
Debug script: Lung Segmentation Pipeline - xuất contact sheet cho từng bước.

Mỗi bước trong LungSegmenter.segment() sẽ được chụp và lưu thành PNG contact sheet.

Usage (local):
    python backend/sandbox/demos/debug_lung_segmentation.py --dicom-dir /path/to/dicom
    python backend/sandbox/demos/debug_lung_segmentation.py --nifti /path/to/file.nii.gz

Usage (modal):
    modal run backend/sandbox/demos/debug_lung_segmentation.py::debug_modal \
        --volume-path dataset/LIDC-IDRI-0001

Output sẽ được lưu vào:
    Local: ./lung_seg_debug/
    Modal: sandbox-output volume -> lung_seg_debug/<source_tag>/
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
if Path("/root/backend").exists():
    BACKEND_ROOT = Path("/root/backend")
elif (CURRENT_FILE.parents[2] / "processing").exists():
    BACKEND_ROOT = CURRENT_FILE.parents[2]
else:
    BACKEND_ROOT = CURRENT_FILE.parents[2]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# ---------------------------------------------------------------------------
# Modal setup (lazy – only used when running remotely)
# ---------------------------------------------------------------------------
RAW_DATA_PATH = "/data_raw"
OUTPUT_PATH = "/sandbox_output"

# ===========================================================================
# Visualization helpers
# ===========================================================================

def _window_hu_to_uint8(slice_hu: np.ndarray) -> np.ndarray:
    window_low, window_high = -1200.0, 600.0
    normalized = (np.asarray(slice_hu, dtype=np.float32) - window_low) / (window_high - window_low)
    return np.rint(np.clip(normalized, 0.0, 1.0) * 255.0).astype(np.uint8)


def _mask_to_uint8_rgb(mask_2d: np.ndarray, color=(255, 64, 64)) -> np.ndarray:
    """Binary mask → RGB canvas with filled region + yellow outline."""
    mask_bool = np.asarray(mask_2d, dtype=bool)
    canvas = np.zeros((*mask_bool.shape, 3), dtype=np.uint8)
    canvas[mask_bool] = color

    # Outline
    padded = np.pad(mask_bool, 1, constant_values=False)
    neighbor_count = sum(
        padded[1 + dr : 1 + dr + mask_bool.shape[0], 1 + dc : 1 + dc + mask_bool.shape[1]]
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if not (dr == 0 and dc == 0)
    )
    outline = mask_bool & (neighbor_count < 8)
    if outline.any():
        canvas[outline] = (255, 230, 64)
    return canvas


def _overlay_mask_on_hu(hu_2d: np.ndarray, mask_2d: np.ndarray, alpha: int = 140) -> np.ndarray:
    """CT slice (HU) + semi-transparent mask overlay → RGB uint8."""
    from PIL import Image

    base = Image.fromarray(_window_hu_to_uint8(hu_2d), mode="L").convert("RGBA")
    mask_bool = np.asarray(mask_2d, dtype=bool)
    overlay = np.zeros((*mask_bool.shape, 4), dtype=np.uint8)
    overlay[mask_bool] = (255, 64, 64, alpha)

    # Yellow outline
    padded = np.pad(mask_bool, 1, constant_values=False)
    neighbor_count = sum(
        padded[1 + dr : 1 + dr + mask_bool.shape[0], 1 + dc : 1 + dc + mask_bool.shape[1]]
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if not (dr == 0 and dc == 0)
    )
    outline = mask_bool & (neighbor_count < 8)
    if outline.any():
        overlay[outline] = (255, 230, 64, 255)

    blended = Image.alpha_composite(base, Image.fromarray(overlay, mode="RGBA"))
    return np.asarray(blended.convert("RGB"), dtype=np.uint8)


def _save_contact_sheet(
    tiles: list[np.ndarray],
    output_path: Path,
    labels: list[str] | None = None,
    label_height: int = 20,
) -> None:
    """Tile a list of RGB arrays into a contact-sheet PNG."""
    from PIL import Image, ImageDraw

    if not tiles:
        return

    tile_h, tile_w = int(tiles[0].shape[0]), int(tiles[0].shape[1])
    cols = max(1, int(math.ceil(math.sqrt(len(tiles)))))
    rows = int(math.ceil(len(tiles) / cols))
    lh = label_height if labels else 0

    canvas = np.zeros((rows * (tile_h + lh), cols * tile_w, 3), dtype=np.uint8)
    for idx, tile in enumerate(tiles):
        r, c = idx // cols, idx % cols
        y0 = r * (tile_h + lh)
        x0 = c * tile_w
        if lh:
            canvas[y0 : y0 + lh, x0 : x0 + tile_w] = 30
        canvas[y0 + lh : y0 + lh + tile_h, x0 : x0 + tile_w] = np.asarray(tile, dtype=np.uint8)

    image = Image.fromarray(canvas, mode="RGB")
    if labels:
        draw = ImageDraw.Draw(image)
        for idx, label in enumerate(labels):
            r, c = idx // cols, idx % cols
            draw.text((c * tile_w + 4, r * (tile_h + lh) + 2), label, fill=(255, 255, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _sample_z_indices(total_z: int, max_slices: int = 64) -> list[int]:
    if total_z <= max_slices:
        return list(range(total_z))
    positions = np.linspace(0, total_z - 1, num=max_slices)
    return sorted({int(round(float(p))) for p in positions})


def _active_z_from_mask(mask_xyz: np.ndarray, max_slices: int = 64) -> list[int]:
    """Return z indices where mask has any True voxel, sampled to max_slices."""
    occupied = np.where(np.asarray(mask_xyz, dtype=bool).any(axis=(0, 1)))[0]
    if occupied.size == 0:
        # Fallback: evenly spaced across entire volume
        return _sample_z_indices(mask_xyz.shape[2], max_slices)
    occupied_list = [int(z) for z in occupied.tolist()]
    if len(occupied_list) <= max_slices:
        return occupied_list
    positions = np.linspace(0, len(occupied_list) - 1, num=max_slices)
    return [occupied_list[int(round(float(p)))] for p in positions]


# ===========================================================================
# Stepped LungSegmenter – captures intermediate masks
# ===========================================================================

class LungSegmenterDebug:
    """
    Wraps LungSegmenter and captures each intermediate mask for visualization.

    Returns a list of StepRecord dicts:
        {
            "step":        int        – step index (0-based)
            "name":        str        – human-readable step name
            "description": str        – what changed
            "mask_xyz":    np.ndarray – bool mask (X, Y, Z) after this step
                                        None for the raw HU input step
            "volume_xyz":  np.ndarray – HU volume (only set for step 0)
        }
    """

    def __init__(self, **segmenter_kwargs):
        from processing.segment_lung import LungSegmenter
        self._seg = LungSegmenter(**segmenter_kwargs)

    def run_debug(self, volume_hu: np.ndarray) -> tuple[dict, list[dict]]:
        """
        Execute the full pipeline step-by-step, capturing masks.

        Returns:
            result   – same dict as LungSegmenter.segment()
            steps    – list of StepRecord dicts
        """
        steps: list[dict] = []
        seg = self._seg

        steps.append({
            "step": 0,
            "name": "Input HU Volume",
            "description": f"Raw CT volume shape={volume_hu.shape} dtype={volume_hu.dtype}",
            "mask_xyz": None,
            "volume_xyz": volume_hu,
        })

        # Step 1: body mask
        body_mask = seg._create_body_mask(volume_hu)
        steps.append({
            "step": 1,
            "name": "Body Mask",
            "description": (
                f"HU > {seg.body_threshold} → morphology open+close per slice. "
                f"Voxels={int(body_mask.sum())}"
            ),
            "mask_xyz": body_mask,
            "volume_xyz": volume_hu,
        })

        # Step 2: internal air
        internal_air = seg._extract_internal_air(volume_hu, body_mask)
        steps.append({
            "step": 2,
            "name": "Internal Air",
            "description": (
                f"air (HU < {seg.hu_threshold}) ∩ body_mask. "
                f"Voxels={int(internal_air.sum())}"
            ),
            "mask_xyz": internal_air,
            "volume_xyz": volume_hu,
        })

        # Step 3: keep lung components
        lung_mask_v1 = seg._keep_lung_components(internal_air)
        steps.append({
            "step": 3,
            "name": "Lung Components",
            "description": (
                f"Keep largest 3D connected components (min_volume={seg.min_lung_volume}). "
                f"Voxels={int(lung_mask_v1.sum())}"
            ),
            "mask_xyz": lung_mask_v1,
            "volume_xyz": volume_hu,
        })

        # Step 4: postprocess
        lung_mask_v2 = seg._postprocess_3d(lung_mask_v1)
        steps.append({
            "step": 4,
            "name": "Post-processed Lung",
            "description": (
                f"fill_holes={seg.fill_holes}, closing 3x3, re-filter components. "
                f"Voxels={int(lung_mask_v2.sum())}"
            ),
            "mask_xyz": lung_mask_v2,
            "volume_xyz": volume_hu,
        })

        # Step 5: left/right split
        left_mask, right_mask = seg._separate_lobes(lung_mask_v2)
        steps.append({
            "step": 5,
            "name": "Left Lung",
            "description": f"Separated left lobe. Voxels={int(left_mask.sum())}",
            "mask_xyz": left_mask,
            "volume_xyz": volume_hu,
        })
        steps.append({
            "step": 6,
            "name": "Right Lung",
            "description": f"Separated right lobe. Voxels={int(right_mask.sum())}",
            "mask_xyz": right_mask,
            "volume_xyz": volume_hu,
        })

        # Final combined
        components = seg._build_components(lung_mask_v2, left_mask, right_mask)
        stats = seg._compute_stats(lung_mask_v2, left_mask, right_mask)
        result = {
            "lung_mask": lung_mask_v2,
            "left_mask": left_mask,
            "right_mask": right_mask,
            "components": components,
            "stats": stats,
        }
        return result, steps


# ===========================================================================
# Visualization: generate all sheets for each step
# ===========================================================================

def render_step_sheets(
    steps: list[dict],
    output_dir: Path,
    max_slices_per_sheet: int = 64,
) -> list[dict[str, Any]]:
    """
    For each step, generate:
      - axial_hu_contact_sheet.png       (raw HU, no mask)
      - axial_mask_only_contact_sheet.png
      - axial_overlay_contact_sheet.png  (HU + mask overlay)

    Returns a list of artifact records (one per step).
    """
    records: list[dict[str, Any]] = []

    for step_rec in steps:
        step_idx = int(step_rec["step"])
        step_name = str(step_rec["name"])
        step_desc = str(step_rec["description"])
        mask_xyz: np.ndarray | None = step_rec.get("mask_xyz")
        volume_xyz: np.ndarray = np.asarray(step_rec["volume_xyz"])

        step_dir = output_dir / f"step_{step_idx:02d}_{_slugify(step_name)}"
        step_dir.mkdir(parents=True, exist_ok=True)

        # Choose z indices to visualize
        if mask_xyz is not None and np.asarray(mask_xyz).any():
            z_indices = _active_z_from_mask(mask_xyz, max_slices_per_sheet)
        else:
            z_indices = _sample_z_indices(volume_xyz.shape[2], max_slices_per_sheet)

        labels = [f"z={z}" for z in z_indices]

        # --- HU raw sheet (step 0 or always for context) ---
        hu_tiles = [
            np.stack([_window_hu_to_uint8(volume_xyz[:, :, z].T)] * 3, axis=-1)
            for z in z_indices
        ]
        hu_path = step_dir / "axial_hu_contact_sheet.png"
        _save_contact_sheet(hu_tiles, hu_path, labels=labels)

        artifact: dict[str, Any] = {
            "step": step_idx,
            "name": step_name,
            "description": step_desc,
            "slice_count": len(z_indices),
            "z_indices": z_indices,
            "artifacts": {
                "axial_hu_contact_sheet": str(hu_path),
            },
        }

        if mask_xyz is not None:
            mask_xyz_bool = np.asarray(mask_xyz, dtype=bool)

            # mask-only sheet
            mask_tiles = [
                _mask_to_uint8_rgb(mask_xyz_bool[:, :, z].T)
                for z in z_indices
            ]
            mask_path = step_dir / "axial_mask_only_contact_sheet.png"
            _save_contact_sheet(mask_tiles, mask_path, labels=labels)

            # overlay sheet
            overlay_tiles = [
                _overlay_mask_on_hu(volume_xyz[:, :, z].T, mask_xyz_bool[:, :, z].T)
                for z in z_indices
            ]
            overlay_path = step_dir / "axial_overlay_contact_sheet.png"
            _save_contact_sheet(overlay_tiles, overlay_path, labels=labels)

            artifact["voxel_count"] = int(mask_xyz_bool.sum())
            artifact["artifacts"]["axial_mask_only_contact_sheet"] = str(mask_path)
            artifact["artifacts"]["axial_overlay_contact_sheet"] = str(overlay_path)

        records.append(artifact)
        print(
            f"[DEBUG] Step {step_idx:02d} '{step_name}': "
            f"{len(z_indices)} slices written → {step_dir}"
        )

    return records


def _slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()


# ===========================================================================
# Main debug runner
# ===========================================================================

def run_debug_pipeline(
    volume_xyz: np.ndarray,
    spacing_xyz_mm: tuple[float, float, float],
    output_dir: Path,
    max_slices: int = 64,
    segmenter_kwargs: dict | None = None,
) -> dict[str, Any]:
    """
    Run full debug pipeline, write sheets, return summary dict.
    """
    import json

    print(f"[DEBUG] Volume shape={volume_xyz.shape}, spacing={spacing_xyz_mm}")
    print(f"[DEBUG] Output dir: {output_dir}")

    kwargs = segmenter_kwargs or {}
    debugger = LungSegmenterDebug(**kwargs)

    print("[DEBUG] Running segmentation steps...")
    result, steps = debugger.run_debug(np.asarray(volume_xyz))

    print(f"[DEBUG] Rendering contact sheets ({len(steps)} steps)...")
    records = render_step_sheets(steps, output_dir, max_slices_per_sheet=max_slices)

    summary = {
        "volume_shape_xyz": [int(v) for v in volume_xyz.shape],
        "spacing_xyz_mm": [float(v) for v in spacing_xyz_mm],
        "segmentation_stats": result["stats"],
        "steps": records,
    }

    summary_path = output_dir / "debug_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[DEBUG] Summary written → {summary_path}")
    return summary


# ===========================================================================
# Modal remote function
# ===========================================================================

def _build_modal_image():
    import modal

    def _ignore(path: str | Path) -> bool:
        path = Path(path)
        return any(p in {"venv", ".venv", "__pycache__", ".git"} for p in path.parts)

    return (
        modal.Image.debian_slim(python_version="3.11")
        .pip_install(
            "trimesh", "numpy", "scipy", "scikit-image", "Pillow",
            "pydicom", "nibabel", "SimpleITK",
            "modal>=0.55.0", "pydantic>=2.0",
        )
        .add_local_dir(
            local_path=str(BACKEND_ROOT),
            remote_path="/root/backend",
            ignore=_ignore,
        )
    )


def _get_modal_app():
    import modal
    app = modal.App("sandbox-lung-seg-debug")
    raw_data_volume = modal.Volume.from_name("data_raw", create_if_missing=False)
    output_volume = modal.Volume.from_name("sandbox-output", create_if_missing=True)
    return app, raw_data_volume, output_volume


try:
    import modal as _modal_check  # noqa: F401
    _modal_available = True
except ImportError:
    _modal_available = False


if _modal_available:
    import modal

    _app = modal.App("sandbox-lung-seg-debug")
    _raw_data_volume = modal.Volume.from_name("data_raw", create_if_missing=False)
    _output_volume = modal.Volume.from_name("sandbox-output", create_if_missing=True)
    _image = _build_modal_image()

    @_app.function(
        image=_image,
        volumes={
            RAW_DATA_PATH: _raw_data_volume,
            OUTPUT_PATH: _output_volume,
        },
        timeout=1800,
        cpu=4,
        memory=8192,
    )
    def debug_lung_seg_remote(
        volume_path: str,
        max_slices: int = 64,
    ) -> dict[str, Any]:
        """Modal remote: load volume and run lung seg debug."""
        import json

        if os.path.exists(RAW_DATA_PATH):
            _raw_data_volume.reload()

        resolved = _resolve_raw_path(volume_path)
        volume_xyz, spacing_xyz_mm = _load_volume(resolved)

        source_tag = _slugify(Path(str(resolved).rstrip("/\\")).name or "volume")
        output_dir = Path(OUTPUT_PATH) / "lung_seg_debug" / source_tag
        output_dir.mkdir(parents=True, exist_ok=True)

        summary = run_debug_pipeline(
            volume_xyz=volume_xyz,
            spacing_xyz_mm=spacing_xyz_mm,
            output_dir=output_dir,
            max_slices=max_slices,
        )
        summary["source_tag"] = source_tag
        summary["volume_path"] = volume_path
        summary["output_dir"] = str(output_dir)

        if os.path.exists(OUTPUT_PATH):
            _output_volume.commit()

        return summary

    @_app.local_entrypoint()
    def debug_modal(
        volume_path: str = "",
        max_slices: int = 64,
        output_json: str = "",
    ):
        """
        modal run backend/sandbox/demos/debug_lung_segmentation.py::debug_modal \
            --volume-path dataset/LIDC-IDRI-0001
        """
        if not volume_path:
            raise ValueError("Provide --volume-path <path-in-data_raw-volume>")

        import json

        result = debug_lung_seg_remote.remote(
            volume_path=volume_path,
            max_slices=max_slices,
        )
        print(json.dumps(result, indent=2))
        if output_json:
            Path(output_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"[DEBUG] Saved result → {output_json}")


# ===========================================================================
# Local helpers
# ===========================================================================

def _resolve_raw_path(volume_path: str) -> Path:
    resolved = Path(volume_path).expanduser()
    if resolved.is_absolute():
        return resolved
    return (Path(RAW_DATA_PATH) / resolved).resolve()


def _load_volume(path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    from processing.loader import MedicalVolumeLoader

    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_dir():
        dicom_files = sorted(str(p) for p in path.rglob("*.dcm"))
        if dicom_files:
            return MedicalVolumeLoader.load_dicom_from_files(dicom_files)
        raise ValueError(f"No DICOM files found under: {path}")

    name = path.name.lower()
    if name.endswith(".nii") or name.endswith(".nii.gz"):
        return MedicalVolumeLoader.load_nifti(str(path))
    if name.endswith(".zip"):
        return MedicalVolumeLoader.load_dicom_series(str(path))
    if name.endswith(".dcm"):
        return MedicalVolumeLoader.load_dicom_from_files([str(path)])

    raise ValueError(f"Unsupported file format: {path}")


# ===========================================================================
# CLI entrypoint
# ===========================================================================

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Debug LungSegmenter: export contact sheets for each pipeline step."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dicom-dir", type=str, help="Path to DICOM directory")
    group.add_argument("--nifti", type=str, help="Path to .nii or .nii.gz file")
    group.add_argument("--zip", type=str, help="Path to DICOM zip archive")

    parser.add_argument(
        "--output-dir", type=str, default="lung_seg_debug",
        help="Output directory for contact sheets (default: ./lung_seg_debug)"
    )
    parser.add_argument(
        "--max-slices", type=int, default=64,
        help="Max slices per contact sheet (default: 64)"
    )
    parser.add_argument(
        "--hu-threshold", type=float, default=-400,
        help="HU threshold for air (default: -400)"
    )
    parser.add_argument(
        "--body-threshold", type=float, default=-500,
        help="HU threshold for body mask (default: -500)"
    )
    parser.add_argument(
        "--min-lung-volume", type=int, default=50000,
        help="Minimum lung component volume in voxels (default: 50000)"
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    if args.dicom_dir:
        src = Path(args.dicom_dir)
    elif args.nifti:
        src = Path(args.nifti)
    else:
        src = Path(args.zip)

    print(f"[DEBUG] Loading volume from: {src}")
    volume_xyz, spacing_xyz_mm = _load_volume(src)

    output_dir = Path(args.output_dir).resolve()
    segmenter_kwargs = {
        "hu_threshold": args.hu_threshold,
        "body_threshold": args.body_threshold,
        "min_lung_volume": args.min_lung_volume,
    }

    run_debug_pipeline(
        volume_xyz=volume_xyz,
        spacing_xyz_mm=spacing_xyz_mm,
        output_dir=output_dir,
        max_slices=args.max_slices,
        segmenter_kwargs=segmenter_kwargs,
    )
    print(f"\n[DEBUG] Done! Sheets saved to: {output_dir}")
    print("Steps:")
    for i in range(7):
        print(f"  step_{i:02d}_*/  (axial_hu | axial_mask_only | axial_overlay)")


if __name__ == "__main__":
    main()
