from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class DoubleConv(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, mid_channels: int | None = None) -> None:
        super().__init__()
        resolved_mid = out_channels if mid_channels is None else mid_channels
        self.double_conv = nn.Sequential(
            nn.Conv2d(in_channels, resolved_mid, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(resolved_mid),
            nn.ReLU(inplace=True),
            nn.Conv2d(resolved_mid, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.double_conv(x)


class Down(nn.Module):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.maxpool_conv = nn.Sequential(
            nn.MaxPool2d(2),
            DoubleConv(in_channels, out_channels),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.maxpool_conv(x)


class UpFlexible(nn.Module):
    def __init__(self, in_channels: int, skip_channels: int, out_channels: int, bilinear: bool = True) -> None:
        super().__init__()
        if bilinear:
            self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
        else:
            self.up = nn.ConvTranspose2d(in_channels, in_channels, kernel_size=2, stride=2)
        self.conv = DoubleConv(in_channels + skip_channels, out_channels, out_channels)

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
        x1 = self.up(x1)
        diff_y = x2.size()[2] - x1.size()[2]
        diff_x = x2.size()[3] - x1.size()[3]
        x1 = F.pad(x1, [diff_x // 2, diff_x - diff_x // 2, diff_y // 2, diff_y - diff_y // 2])
        return self.conv(torch.cat([x2, x1], dim=1))


class SelfAwareAttention(nn.Module):
    def __init__(self, in_channels: int, num_heads: int = 8) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.d_k = in_channels // num_heads
        self.query_conv = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.key_conv = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.value_conv = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.reduced_channels = in_channels // 8
        self.gsa_conv_m = nn.Conv2d(in_channels, self.reduced_channels, kernel_size=1)
        self.gsa_conv_n = nn.Conv2d(in_channels, self.reduced_channels, kernel_size=1)
        self.gsa_conv_w = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.gsa_conv_out = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.gamma_tsa = nn.Parameter(torch.zeros(1))
        self.gamma_gsa = nn.Parameter(torch.zeros(1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, channels, height, width = x.size()
        proj_query = self.query_conv(x).view(batch_size, self.num_heads, self.d_k, -1)
        proj_key = self.key_conv(x).view(batch_size, self.num_heads, self.d_k, -1)
        proj_value = self.value_conv(x).view(batch_size, self.num_heads, self.d_k, -1)
        energy = torch.matmul(proj_query.permute(0, 1, 3, 2), proj_key)
        attention = F.softmax(energy / (self.d_k ** 0.5), dim=-1)
        tsa_out = torch.matmul(attention, proj_value.permute(0, 1, 3, 2))
        tsa_out = tsa_out.permute(0, 1, 3, 2).contiguous().view(batch_size, channels, height, width)

        m = self.gsa_conv_m(x).view(batch_size, self.reduced_channels, -1).permute(0, 2, 1)
        n = self.gsa_conv_n(x).view(batch_size, self.reduced_channels, -1)
        position_attention = F.softmax(torch.matmul(m, n), dim=-1)
        w = self.gsa_conv_w(x).view(batch_size, channels, -1)
        gsa_out = torch.matmul(w, position_attention.permute(0, 2, 1))
        gsa_out = gsa_out.view(batch_size, channels, height, width)
        gsa_out = self.gsa_conv_out(gsa_out)
        return (self.gamma_tsa * tsa_out) + (self.gamma_gsa * gsa_out) + x


class TransAttUnet(nn.Module):
    def __init__(self, n_channels: int = 1, n_classes: int = 2, bilinear: bool = True) -> None:
        super().__init__()
        self.inc = DoubleConv(n_channels, 32)
        self.down1 = Down(32, 64)
        self.down2 = Down(64, 128)
        self.down3 = Down(128, 256)
        self.down4_conv = nn.Sequential(nn.MaxPool2d(2), DoubleConv(256, 512))
        self.saa_bridge = SelfAwareAttention(in_channels=512)
        self.up1 = UpFlexible(512, 256, 256, bilinear=bilinear)
        self.up2 = UpFlexible(768, 128, 128, bilinear=bilinear)
        self.up3 = UpFlexible(384, 64, 64, bilinear=bilinear)
        self.up4 = UpFlexible(192, 32, 32, bilinear=bilinear)
        self.outc = nn.Conv2d(96, n_classes, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4_conv(x4)
        x5_att = self.saa_bridge(x5)
        x6 = self.up1(x5_att, x4)
        x5_scale = F.interpolate(x5_att, size=x6.shape[2:], mode="bilinear", align_corners=True)
        x6_cat = torch.cat((x5_scale, x6), dim=1)
        x7 = self.up2(x6_cat, x3)
        x6_scale = F.interpolate(x6, size=x7.shape[2:], mode="bilinear", align_corners=True)
        x7_cat = torch.cat((x6_scale, x7), dim=1)
        x8 = self.up3(x7_cat, x2)
        x7_scale = F.interpolate(x7, size=x8.shape[2:], mode="bilinear", align_corners=True)
        x8_cat = torch.cat((x7_scale, x8), dim=1)
        x9 = self.up4(x8_cat, x1)
        x8_scale = F.interpolate(x8, size=x9.shape[2:], mode="bilinear", align_corners=True)
        return self.outc(torch.cat((x8_scale, x9), dim=1))
