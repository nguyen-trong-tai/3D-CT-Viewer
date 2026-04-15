from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy import ndimage
from scipy.ndimage import zoom
from skimage.morphology import convex_hull_image

from .model import SplitComb


def lum_trans(volume_hu: np.ndarray) -> np.ndarray:
    lung_window = np.array([-1200.0, 600.0], dtype=np.float32)
    normalized = (volume_hu.astype(np.float32) - lung_window[0]) / (lung_window[1] - lung_window[0])
    normalized = np.clip(normalized, 0.0, 1.0)
    return (normalized * 255.0).astype(np.uint8)


def resample_3d(volume: np.ndarray, spacing: np.ndarray, new_spacing: np.ndarray, order: int = 1) -> np.ndarray:
    spacing = np.asarray(spacing, dtype=np.float32)
    new_spacing = np.asarray(new_spacing, dtype=np.float32)
    if volume.ndim != 3:
        raise ValueError(f"Expected a 3D volume, got shape {volume.shape}")
    new_shape = np.round(np.asarray(volume.shape, dtype=np.float32) * spacing / new_spacing).astype(int)
    new_shape = np.maximum(new_shape, 1)
    return zoom(volume, new_shape / np.asarray(volume.shape, dtype=np.float32), mode="nearest", order=order)


def process_mask(mask: np.ndarray) -> np.ndarray:
    if mask.ndim != 3:
        raise ValueError(f"Expected a 3D mask, got shape {mask.shape}")
    convex_mask = np.zeros_like(mask, dtype=bool)
    for z_index in range(mask.shape[0]):
        slice_mask = np.ascontiguousarray(mask[z_index].astype(bool))
        if slice_mask.any():
            hull = convex_hull_image(slice_mask)
            convex_mask[z_index] = slice_mask if hull.sum() > 1.5 * slice_mask.sum() else hull
        else:
            convex_mask[z_index] = slice_mask
    return ndimage.binary_dilation(convex_mask, structure=ndimage.generate_binary_structure(3, 1), iterations=10)


@dataclass(frozen=True)
class DeepLungDetectorConfig:
    anchors: tuple[float, ...] = (5.0, 10.0, 20.0)
    crop_size: tuple[int, int, int] = (96, 96, 96)
    stride: int = 4
    max_stride: int = 16
    pad_value: int = 170
    resample_spacing_zyx_mm: tuple[float, float, float] = (1.0, 1.0, 1.0)
    bbox_margin_mm: int = 5
    tile_side_len: int = 144
    tile_margin: int = 32
    score_threshold: float = -3.0
    nms_threshold: float = 0.1
    batch_size: int = 4
    device: str = "cpu"


@dataclass
class DeepLungPreprocessResult:
    clean_volume_zyx: np.ndarray
    spacing_zyx_mm: np.ndarray
    extendbox_zyx: np.ndarray
    original_shape_zyx: tuple[int, int, int]
    resampled_shape_zyx: tuple[int, int, int]


class DeepLungVolumePreprocessor:
    def __init__(self, config: DeepLungDetectorConfig) -> None:
        self.config = config

    @staticmethod
    def xyz_to_zyx(volume_xyz: np.ndarray) -> np.ndarray:
        return np.transpose(volume_xyz, (2, 1, 0))

    @staticmethod
    def spacing_xyz_to_zyx(spacing_xyz: Iterable[float]) -> np.ndarray:
        spacing_array = np.asarray(tuple(float(value) for value in spacing_xyz), dtype=np.float32)
        if spacing_array.shape != (3,):
            raise ValueError(f"Expected spacing_xyz with 3 elements, got {spacing_array}")
        return spacing_array[[2, 1, 0]]

    def prepare(self, volume_hu_xyz: np.ndarray, spacing_xyz_mm: Iterable[float], lung_mask_xyz: np.ndarray) -> DeepLungPreprocessResult:
        volume_zyx = self.xyz_to_zyx(np.asarray(volume_hu_xyz))
        mask_zyx = self.xyz_to_zyx(np.asarray(lung_mask_xyz, dtype=bool))
        spacing_zyx = self.spacing_xyz_to_zyx(spacing_xyz_mm)
        if not mask_zyx.any():
            raise ValueError("lung_mask is empty; cannot prepare detector input")
        prepared = self._prepare_masked_volume(volume_zyx, mask_zyx)
        extendbox = self._build_extendbox(mask_zyx, spacing_zyx)
        resolution_zyx = np.asarray(self.config.resample_spacing_zyx_mm, dtype=np.float32)
        resampled = resample_3d(prepared, spacing_zyx, resolution_zyx, order=1)
        cropped = resampled[extendbox[0, 0]:extendbox[0, 1], extendbox[1, 0]:extendbox[1, 1], extendbox[2, 0]:extendbox[2, 1]]
        return DeepLungPreprocessResult(
            clean_volume_zyx=cropped[np.newaxis, ...].astype(np.uint8, copy=False),
            spacing_zyx_mm=spacing_zyx,
            extendbox_zyx=extendbox,
            original_shape_zyx=tuple(int(value) for value in volume_zyx.shape),
            resampled_shape_zyx=tuple(int(value) for value in resampled.shape),
        )

    def _prepare_masked_volume(self, volume_zyx: np.ndarray, mask_zyx: np.ndarray) -> np.ndarray:
        dilated_mask = process_mask(mask_zyx)
        prepared = np.asarray(volume_zyx, dtype=np.float32).copy()
        prepared[np.isnan(prepared)] = -2000.0
        prepared = lum_trans(prepared)
        prepared = prepared * dilated_mask.astype(np.uint8) + self.config.pad_value * (~dilated_mask).astype(np.uint8)
        extra_mask = dilated_mask & ~mask_zyx
        prepared[(prepared * extra_mask.astype(np.uint8)) > 210] = self.config.pad_value
        return prepared

    def _build_extendbox(self, mask_zyx: np.ndarray, spacing_zyx: np.ndarray) -> np.ndarray:
        resolution_zyx = np.asarray(self.config.resample_spacing_zyx_mm, dtype=np.float32)
        mask_indices = np.where(mask_zyx)
        bbox = np.array([[np.min(mask_indices[0]), np.max(mask_indices[0])], [np.min(mask_indices[1]), np.max(mask_indices[1])], [np.min(mask_indices[2]), np.max(mask_indices[2])]], dtype=np.float32)
        new_shape = np.maximum(np.round(np.asarray(mask_zyx.shape, dtype=np.float32) * spacing_zyx / resolution_zyx).astype(int), 1)
        scaled_box = np.floor(bbox * np.expand_dims(spacing_zyx, 1) / np.expand_dims(resolution_zyx, 1)).astype(int)
        margin = int(self.config.bbox_margin_mm)
        extendbox = np.vstack([np.maximum([0, 0, 0], scaled_box[:, 0] - margin), np.minimum(new_shape, scaled_box[:, 1] + 2 * margin)]).T.astype(int)
        if np.any(extendbox[:, 0] >= extendbox[:, 1]):
            raise ValueError(f"Invalid detector crop box derived from lung mask: {extendbox.tolist()}")
        return extendbox


class DeepLungTileBuilder:
    def __init__(self, config: DeepLungDetectorConfig, split_comber: SplitComb) -> None:
        self.config = config
        self.split_comber = split_comber

    def build(self, clean_volume_zyx: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[int]]:
        imgs = self._pad_to_stride(np.asarray(clean_volume_zyx, dtype=np.uint8))
        coord = self._build_coord_grid(imgs.shape[1:])
        image_splits, nzhw = self.split_comber.split(imgs)
        coord_splits, coord_nzhw = self.split_comber.split(coord, side_len=self.split_comber.side_len // self.config.stride, max_stride=self.split_comber.max_stride // self.config.stride, margin=self.split_comber.margin // self.config.stride)
        if nzhw != coord_nzhw:
            raise ValueError(f"Image and coord splits disagree: {nzhw} vs {coord_nzhw}")
        return (image_splits.astype(np.float32) - 128.0) / 128.0, coord_splits.astype(np.float32), nzhw

    def _pad_to_stride(self, imgs: np.ndarray) -> np.ndarray:
        depth, height, width = imgs.shape[1:]
        stride = self.config.stride
        padded_shape = [int(np.ceil(float(length) / float(stride)) * stride) for length in (depth, height, width)]
        return np.pad(imgs, [[0, 0], [0, padded_shape[0] - depth], [0, padded_shape[1] - height], [0, padded_shape[2] - width]], mode="constant", constant_values=self.config.pad_value)

    def _build_coord_grid(self, shape_zyx: tuple[int, int, int]) -> np.ndarray:
        stride = self.config.stride
        coord_depth, coord_height, coord_width = [int(length // stride) for length in shape_zyx]
        zz, yy, xx = np.meshgrid(
            np.linspace(-0.5, 0.5, coord_depth, dtype=np.float32),
            np.linspace(-0.5, 0.5, coord_height, dtype=np.float32),
            np.linspace(-0.5, 0.5, coord_width, dtype=np.float32),
            indexing="ij",
        )
        return np.concatenate([zz[np.newaxis, ...], yy[np.newaxis, ...], xx[np.newaxis, ...]], axis=0).astype(np.float32)
