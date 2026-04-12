from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Protocol

import numpy as np

from .models import DetectorStageOutput


class DetectorProtocol(Protocol):
    def detect(
        self,
        volume_hu_xyz: np.ndarray,
        spacing_xyz_mm: Iterable[float],
        lung_mask_xyz: np.ndarray,
        score_threshold: float | None = None,
        nms_threshold: float | None = None,
        top_k: int | None = None,
    ) -> Any:
        ...


class PatchSegmenterProtocol(Protocol):
    def segment_slice_with_mapping(self, slice_2d: np.ndarray, center_y: float, center_x: float) -> Any:
        ...

    def describe(self) -> dict[str, Any]:
        ...


class LungSegmenterProtocol(Protocol):
    def segment(self, volume_xyz: np.ndarray) -> dict[str, Any]:
        ...


def _coerce_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _coerce_array(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    array = np.asarray(value)
    if array.size == 0:
        return np.asarray(value, dtype=np.float32)
    return np.asarray(array, dtype=np.float32)


def _read_field(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def normalize_detector_output(result: Any) -> DetectorStageOutput:
    if isinstance(result, DetectorStageOutput):
        return result

    candidates = list(_read_field(result, "candidates", []) or [])
    debug = _coerce_dict(_read_field(result, "debug", {}))
    preprocess = _coerce_dict(_read_field(result, "preprocess", {}))
    raw_candidates = _coerce_array(_read_field(result, "raw_candidates_zyx"))
    post_nms_candidates = _coerce_array(_read_field(result, "post_nms_candidates_zyx"))

    extras = _coerce_dict(result)
    for key in ("candidates", "debug", "preprocess", "raw_candidates_zyx", "post_nms_candidates_zyx"):
        extras.pop(key, None)

    return DetectorStageOutput(
        candidates=candidates,
        debug=debug,
        preprocess=preprocess,
        raw_candidates_zyx=raw_candidates,
        post_nms_candidates_zyx=post_nms_candidates,
        extras=extras,
    )
