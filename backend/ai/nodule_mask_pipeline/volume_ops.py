from __future__ import annotations

from typing import Iterable

import numpy as np
from scipy import ndimage


def resample_volume_xyz(
    volume: np.ndarray,
    spacing_xyz: Iterable[float],
    new_spacing_xyz: Iterable[float],
    order: int,
) -> np.ndarray:
    spacing = np.asarray(tuple(float(value) for value in spacing_xyz), dtype=np.float32)
    new_spacing = np.asarray(tuple(float(value) for value in new_spacing_xyz), dtype=np.float32)
    if spacing.shape != (3,) or new_spacing.shape != (3,):
        raise ValueError(f"Expected 3D spacing, got {spacing} and {new_spacing}")
    if volume.ndim != 3:
        raise ValueError(f"Expected 3D volume, got shape {volume.shape}")

    new_shape = np.round(np.asarray(volume.shape, dtype=np.float32) * spacing / new_spacing).astype(int)
    new_shape = np.maximum(new_shape, 1)
    zoom_factor = new_shape / np.asarray(volume.shape, dtype=np.float32)
    return ndimage.zoom(volume, zoom=zoom_factor, order=order, mode="nearest")


def match_volume_shape(volume: np.ndarray, target_shape: tuple[int, int, int], pad_value: float = 0.0) -> np.ndarray:
    target = np.full(target_shape, pad_value, dtype=volume.dtype)
    overlap_shape = tuple(min(int(src), int(dst)) for src, dst in zip(volume.shape, target_shape))
    target[:overlap_shape[0], :overlap_shape[1], :overlap_shape[2]] = volume[
        :overlap_shape[0],
        :overlap_shape[1],
        :overlap_shape[2],
    ]
    return target
