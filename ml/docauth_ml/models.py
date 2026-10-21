"""PyTorch models. Both take RGB in [0, 1] so the ONNX contract stays simple.

* ``SRMPatchNet`` - README module 2: CNN whose first layer is initialised with the 30 SRM
  high-pass filters, used as a dense patch descriptor (2 output neurons: real / fake).
* ``TwoStreamSegNet`` - README module 3: RGB stream (ResNet-18) + DCT stream on the JPEG
  luminance channel (block DCT, one-hot histogram features that expose double compression),
  fused into an FPN decoder that predicts a per-pixel manipulation heatmap.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from docauth_ml.srm import srm_kernels


def conv_bn(cin: int, cout: int, k: int = 3, s: int = 1, d: int = 1) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, k, s, padding=d * (k // 2), dilation=d, bias=False),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
    )


class SRMConv(nn.Module):
    """5x5 conv initialised with the 30 SRM kernels, followed by truncation (TLU)."""

    def __init__(self, trainable: bool = True, threshold: float = 8.0):
        super().__init__()
        k = torch.from_numpy(srm_kernels())  # (30, 5, 5)
        w = k[:, None].repeat(1, 3, 1, 1) / 3.0  # applied to the channel average
        self.conv = nn.Conv2d(3, 30, 5, padding=2, bias=False)
        self.conv.weight.data.copy_(w)
        self.conv.weight.requires_grad_(trainable)
        self.threshold = threshold

    def forward(self, x01: torch.Tensor) -> torch.Tensor:
        r = self.conv(x01 * 255.0)
        return torch.clamp(r, -self.threshold, self.threshold) / self.threshold


class SRMPatchNet(nn.Module):
    def __init__(self, width: int = 32, dropout: float = 0.3):
        super().__init__()
        self.srm = SRMConv()
        w = width
        # the SRM residuals are dense, so the first conv can stride: ~4x fewer FLOPs than
        # full-resolution blocks, which matters for CPU inference over hundreds of patches
        self.features = nn.Sequential(
            conv_bn(30, w, s=2),  # 64
            conv_bn(w, w),
            nn.MaxPool2d(2),  # 32
            conv_bn(w, 2 * w),
            conv_bn(2 * w, 2 * w),
            nn.MaxPool2d(2),  # 16
            conv_bn(2 * w, 4 * w),
            conv_bn(4 * w, 4 * w),
            nn.MaxPool2d(2),  # 8
            conv_bn(4 * w, 8 * w),
        )
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(8 * w, 2))

    def embed(self, x: torch.Tensor) -> torch.Tensor:
        f = self.features(self.srm(x))
        return torch.flatten(F.adaptive_avg_pool2d(f, 1), 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.embed(x))


def _zigzag(n: int = 8) -> list[int]:
    order = sorted(
        ((u, v) for u in range(n) for v in range(n)),
        key=lambda p: (p[0] + p[1], p[1] if (p[0] + p[1]) % 2 else p[0]),
    )
    return [u * n + v for u, v in order]


class BlockDCT(nn.Module):
    """8x8 orthonormal DCT-II of the JPEG luminance channel (stride 8, JPEG grid aligned)."""

    def __init__(self):
        super().__init__()
        basis = np.zeros((64, 1, 8, 8), np.float32)
        for u in range(8):
            for v in range(8):
                cu = math.sqrt(1 / 8) if u == 0 else math.sqrt(2 / 8)
                cv = math.sqrt(1 / 8) if v == 0 else math.sqrt(2 / 8)
                for x in range(8):
                    for y in range(8):
                        basis[u * 8 + v, 0, x, y] = (
                            cu
                            * cv
                            * math.cos((2 * x + 1) * u * math.pi / 16)
                            * math.cos((2 * y + 1) * v * math.pi / 16)
                        )
        self.register_buffer("basis", torch.from_numpy(basis))
        self.register_buffer("ycoef", torch.tensor([0.299, 0.587, 0.114]).view(1, 3, 1, 1))

    def forward(self, x01: torch.Tensor) -> torch.Tensor:
        y = (x01 * self.ycoef).sum(1, keepdim=True) * 255.0 - 128.0
        return F.conv2d(y, self.basis, stride=8)


class DCTStream(nn.Module):
    """Histogram-style DCT features: one-hot |round(c)| for low-frequency AC coefficients."""

    def __init__(self, n_coef: int = 15, n_bins: int = 16, out8: int = 128, out16: int = 256):
        super().__init__()
        self.dct = BlockDCT()
        zz = _zigzag()[1 : 1 + n_coef]  # skip DC
        self.register_buffer("sel", torch.tensor(zz, dtype=torch.long))
        self.register_buffer("bins", torch.arange(n_bins, dtype=torch.float32).view(1, 1, -1, 1, 1))
        self.n_bins = n_bins
        cin = n_coef * n_bins + 64
        self.s8 = nn.Sequential(
            conv_bn(cin, out8, 1), conv_bn(out8, out8), conv_bn(out8, out8, d=2)
        )
        self.s16 = nn.Sequential(conv_bn(out8, out16, s=2), conv_bn(out16, out16))

    def features(self, x01: torch.Tensor) -> torch.Tensor:
        c = self.dct(x01.float())  # (B, 64, H/8, W/8)
        a = torch.clamp(
            torch.round(torch.abs(torch.index_select(c, 1, self.sel))), max=float(self.n_bins - 1)
        )
        onehot = (a.unsqueeze(2) == self.bins).float()  # (B, n_coef, n_bins, h, w)
        b, n, k, h, w = onehot.shape
        onehot = onehot.reshape(b, n * k, h, w)
        mag = torch.log1p(torch.abs(c)) / 4.0
        return torch.cat([onehot, mag], 1)

    def forward(self, x01: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        # coefficient histograms need full precision: keep the transform out of fp16 autocast
        if x01.is_cuda:
            with torch.autocast("cuda", enabled=False):
                feats = self.features(x01)
        else:
            feats = self.features(x01)
        f8 = self.s8(feats)
        return f8, self.s16(f8)


class TwoStreamSegNet(nn.Module):
    def __init__(self, pretrained: bool = True):
        super().__init__()
        import torchvision

        weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        r = torchvision.models.resnet18(weights=weights)
        self.stem = nn.Sequential(r.conv1, r.bn1, r.relu, r.maxpool)
        self.l1, self.l2, self.l3, self.l4 = r.layer1, r.layer2, r.layer3, r.layer4
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))
        self.dct = DCTStream()
        c = 128
        self.fuse8 = conv_bn(128 + 128, c, 1)
        self.fuse16 = conv_bn(256 + 256, c, 1)
        self.lat32 = conv_bn(512, c, 1)
        self.lat4 = conv_bn(64, c, 1)
        self.smooth16 = conv_bn(c, c)
        self.smooth8 = conv_bn(c, c)
        self.smooth4 = conv_bn(c, c)
        self.head = nn.Sequential(conv_bn(c, 64), nn.Conv2d(64, 1, 1))

    @staticmethod
    def _up(x: torch.Tensor, ref: torch.Tensor) -> torch.Tensor:
        return F.interpolate(x, size=ref.shape[-2:], mode="bilinear", align_corners=False)

    def forward(self, x01: torch.Tensor) -> torch.Tensor:
        x = (x01 - self.mean) / self.std
        r1 = self.l1(self.stem(x))  # s4, 64
        r2 = self.l2(r1)  # s8, 128
        r3 = self.l3(r2)  # s16, 256
        r4 = self.l4(r3)  # s32, 512
        d8, d16 = self.dct(x01)
        p32 = self.lat32(r4)
        p16 = self.smooth16(self.fuse16(torch.cat([r3, d16], 1)) + self._up(p32, r3))
        p8 = self.smooth8(self.fuse8(torch.cat([r2, d8], 1)) + self._up(p16, r2))
        p4 = self.smooth4(self.lat4(r1) + self._up(p8, r1))
        logits = self.head(p4)
        return F.interpolate(logits, size=x01.shape[-2:], mode="bilinear", align_corners=False)
