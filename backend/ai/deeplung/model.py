from __future__ import annotations

from typing import Iterable

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class SplitComb:
    def __init__(self, side_len: int, max_stride: int, stride: int, margin: int, pad_value: int):
        self.side_len = int(side_len)
        self.max_stride = int(max_stride)
        self.stride = int(stride)
        self.margin = int(margin)
        self.pad_value = int(pad_value)

    def split(
        self,
        data: np.ndarray,
        side_len: int | None = None,
        max_stride: int | None = None,
        margin: int | None = None,
    ) -> tuple[np.ndarray, list[int]]:
        side_len = self.side_len if side_len is None else int(side_len)
        max_stride = self.max_stride if max_stride is None else int(max_stride)
        margin = self.margin if margin is None else int(margin)
        if side_len <= margin:
            raise ValueError(f"side_len must be > margin, got side_len={side_len}, margin={margin}")
        if side_len % max_stride != 0:
            raise ValueError(f"side_len must be divisible by max_stride, got {side_len} and {max_stride}")
        if margin % max_stride != 0:
            raise ValueError(f"margin must be divisible by max_stride, got {margin} and {max_stride}")

        _, depth, height, width = data.shape
        num_depth = int(np.ceil(float(depth) / float(side_len)))
        num_height = int(np.ceil(float(height) / float(side_len)))
        num_width = int(np.ceil(float(width) / float(side_len)))
        nzhw = [num_depth, num_height, num_width]
        pad = [
            [0, 0],
            [margin, num_depth * side_len - depth + margin],
            [margin, num_height * side_len - height + margin],
            [margin, num_width * side_len - width + margin],
        ]
        padded = np.pad(data, pad, mode="edge")
        splits: list[np.ndarray] = []
        for depth_index in range(num_depth):
            for height_index in range(num_height):
                for width_index in range(num_width):
                    start_d = depth_index * side_len
                    end_d = (depth_index + 1) * side_len + 2 * margin
                    start_h = height_index * side_len
                    end_h = (height_index + 1) * side_len + 2 * margin
                    start_w = width_index * side_len
                    end_w = (width_index + 1) * side_len + 2 * margin
                    splits.append(padded[np.newaxis, :, start_d:end_d, start_h:end_h, start_w:end_w])
        return np.concatenate(splits, axis=0), nzhw

    def combine(
        self,
        outputs: np.ndarray,
        nzhw: Iterable[int],
        side_len: int | None = None,
        stride: int | None = None,
        margin: int | None = None,
    ) -> np.ndarray:
        side_len = self.side_len if side_len is None else int(side_len)
        stride = self.stride if stride is None else int(stride)
        margin = self.margin if margin is None else int(margin)
        num_depth, num_height, num_width = [int(value) for value in nzhw]
        if side_len % stride != 0:
            raise ValueError(f"side_len must be divisible by stride, got {side_len} and {stride}")
        if margin % stride != 0:
            raise ValueError(f"margin must be divisible by stride, got {margin} and {stride}")
        side_len_out = side_len // stride
        margin_out = margin // stride
        combined = -1000000.0 * np.ones(
            (
                num_depth * side_len_out,
                num_height * side_len_out,
                num_width * side_len_out,
                outputs[0].shape[3],
                outputs[0].shape[4],
            ),
            dtype=np.float32,
        )
        index = 0
        for depth_index in range(num_depth):
            for height_index in range(num_height):
                for width_index in range(num_width):
                    start_d = depth_index * side_len_out
                    end_d = (depth_index + 1) * side_len_out
                    start_h = height_index * side_len_out
                    end_h = (height_index + 1) * side_len_out
                    start_w = width_index * side_len_out
                    end_w = (width_index + 1) * side_len_out
                    split = outputs[index][
                        margin_out:margin_out + side_len_out,
                        margin_out:margin_out + side_len_out,
                        margin_out:margin_out + side_len_out,
                    ]
                    combined[start_d:end_d, start_h:end_h, start_w:end_w] = split
                    index += 1
        return combined


class Bottleneck(nn.Module):
    def __init__(self, last_planes: int, in_planes: int, out_planes: int, dense_depth: int, stride: int, first_layer: bool) -> None:
        super().__init__()
        self.out_planes = out_planes
        self.conv1 = nn.Conv3d(last_planes, in_planes, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm3d(in_planes)
        self.conv2 = nn.Conv3d(in_planes, in_planes, kernel_size=3, stride=stride, padding=1, groups=8, bias=False)
        self.bn2 = nn.BatchNorm3d(in_planes)
        self.conv3 = nn.Conv3d(in_planes, out_planes + dense_depth, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm3d(out_planes + dense_depth)
        self.shortcut = (
            nn.Sequential(
                nn.Conv3d(last_planes, out_planes + dense_depth, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm3d(out_planes + dense_depth),
            )
            if first_layer
            else nn.Identity()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = F.relu(self.bn1(self.conv1(x)), inplace=False)
        out = F.relu(self.bn2(self.conv2(out)), inplace=False)
        out = self.bn3(self.conv3(out))
        residual = self.shortcut(x)
        main_channels = self.out_planes
        out = torch.cat(
            [residual[:, :main_channels] + out[:, :main_channels], residual[:, main_channels:], out[:, main_channels:]],
            dim=1,
        )
        return F.relu(out, inplace=False)


class DPN3D26(nn.Module):
    def __init__(self, anchors: tuple[float, ...]) -> None:
        super().__init__()
        self.anchors = anchors
        in_planes = (24, 48, 72, 96)
        out_planes = (24, 48, 72, 96)
        num_blocks = (2, 2, 2, 2)
        dense_depth = (8, 8, 8, 8)
        self.conv1 = nn.Conv3d(1, 24, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn1 = nn.BatchNorm3d(24)
        self.last_planes = 24
        self.layer1 = self._make_layer(in_planes[0], out_planes[0], num_blocks[0], dense_depth[0], stride=2)
        self.layer2 = self._make_layer(in_planes[1], out_planes[1], num_blocks[1], dense_depth[1], stride=2)
        self.layer3 = self._make_layer(in_planes[2], out_planes[2], num_blocks[2], dense_depth[2], stride=2)
        self.layer4 = self._make_layer(in_planes[3], out_planes[3], num_blocks[3], dense_depth[3], stride=2)
        self.linear = nn.Linear(out_planes[3] + (num_blocks[3] + 1) * dense_depth[3], 2)
        self.last_planes = 216
        self.layer5 = self._make_layer(128, 128, num_blocks[2], dense_depth[2], stride=1)
        self.last_planes = 224 + 3
        self.layer6 = self._make_layer(224, 224, num_blocks[1], dense_depth[1], stride=1)
        self.last_planes = 120
        self.path1 = nn.Sequential(nn.ConvTranspose3d(self.last_planes, self.last_planes, kernel_size=2, stride=2), nn.BatchNorm3d(self.last_planes), nn.ReLU(inplace=True))
        self.last_planes = 152
        self.path2 = nn.Sequential(nn.ConvTranspose3d(self.last_planes, self.last_planes, kernel_size=2, stride=2), nn.BatchNorm3d(self.last_planes), nn.ReLU(inplace=True))
        self.drop = nn.Dropout3d(p=0.5, inplace=False)
        self.output = nn.Sequential(nn.Conv3d(248, 64, kernel_size=1), nn.ReLU(inplace=True), nn.Conv3d(64, 5 * len(self.anchors), kernel_size=1))

    def _make_layer(self, in_planes: int, out_planes: int, num_blocks: int, dense_depth: int, stride: int) -> nn.Sequential:
        strides = [stride] + [1] * (num_blocks - 1)
        layers: list[nn.Module] = []
        for block_index, block_stride in enumerate(strides):
            layers.append(Bottleneck(self.last_planes, in_planes, out_planes, dense_depth, block_stride, first_layer=(block_index == 0)))
            self.last_planes = out_planes + (block_index + 2) * dense_depth
        return nn.Sequential(*layers)

    def forward(self, x: torch.Tensor, coord: torch.Tensor) -> torch.Tensor:
        out0 = F.relu(self.bn1(self.conv1(x)), inplace=False)
        out1 = self.layer1(out0)
        out2 = self.layer2(out1)
        out3 = self.layer3(out2)
        out4 = self.layer4(out3)
        out5 = self.path1(out4)
        out6 = self.layer5(torch.cat((out3, out5), dim=1))
        out7 = self.path2(out6)
        out8 = self.layer6(torch.cat((out2, out7, coord), dim=1))
        out10 = self.output(self.drop(out8))
        batch, channels, depth, height, width = out10.shape
        out10 = out10.view(batch, channels, -1).transpose(1, 2).contiguous()
        return out10.view(batch, depth, height, width, len(self.anchors), 5)


class GetPBB:
    def __init__(self, stride: int, anchors: tuple[float, ...]) -> None:
        self.stride = int(stride)
        self.anchors = np.asarray(anchors, dtype=np.float32)

    def __call__(self, output: np.ndarray, threshold: float = -3.0) -> np.ndarray:
        output = np.asarray(output, dtype=np.float32).copy()
        offset = (float(self.stride) - 1.0) / 2.0
        depth, height, width = output.shape[:3]
        oz = np.arange(offset, offset + self.stride * (depth - 1) + 1, self.stride)
        oh = np.arange(offset, offset + self.stride * (height - 1) + 1, self.stride)
        ow = np.arange(offset, offset + self.stride * (width - 1) + 1, self.stride)
        output[:, :, :, :, 1] = oz.reshape((-1, 1, 1, 1)) + output[:, :, :, :, 1] * self.anchors.reshape((1, 1, 1, -1))
        output[:, :, :, :, 2] = oh.reshape((1, -1, 1, 1)) + output[:, :, :, :, 2] * self.anchors.reshape((1, 1, 1, -1))
        output[:, :, :, :, 3] = ow.reshape((1, 1, -1, 1)) + output[:, :, :, :, 3] * self.anchors.reshape((1, 1, 1, -1))
        output[:, :, :, :, 4] = np.exp(output[:, :, :, :, 4]) * self.anchors.reshape((1, 1, 1, -1))
        mask = output[..., 0] > threshold
        zz, yy, xx, aa = np.where(mask)
        if zz.size == 0:
            return np.zeros((0, 5), dtype=np.float32)
        return output[zz, yy, xx, aa]


def iou_sphere_like(box0: np.ndarray, box1: np.ndarray) -> float:
    radius0 = box0[3] / 2.0
    start0 = box0[:3] - radius0
    end0 = box0[:3] + radius0
    radius1 = box1[3] / 2.0
    start1 = box1[:3] - radius1
    end1 = box1[:3] + radius1
    overlap = [max(0.0, min(end0[index], end1[index]) - max(start0[index], start1[index])) for index in range(3)]
    intersection = overlap[0] * overlap[1] * overlap[2]
    union = box0[3] ** 3 + box1[3] ** 3 - intersection
    return 0.0 if union <= 0 else float(intersection / union)


def nms_3d(candidates: np.ndarray, nms_threshold: float) -> np.ndarray:
    if len(candidates) == 0:
        return candidates
    ordered = candidates[np.argsort(-candidates[:, 0])]
    kept = [ordered[0]]
    for candidate in ordered[1:]:
        if all(iou_sphere_like(candidate[1:5], existing[1:5]) < nms_threshold for existing in kept):
            kept.append(candidate)
    return np.asarray(kept, dtype=np.float32)
