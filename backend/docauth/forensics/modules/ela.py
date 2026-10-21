"""Error Level Analysis (README module 2, classical part).

The page is re-compressed at a fixed JPEG quality and the per-pixel error is measured. Regions
whose compression history differs from the rest re-compress differently. Raw ELA is dominated
by edges (text!), so each block's error is compared only with blocks of similar edge density.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from docauth.forensics.modules.base import AnalysisContext, Module
from docauth.forensics.types import Artifact, Document, Finding, ModuleResult, Page
from docauth.forensics.util import (
    block_reduce,
    heatmap_overlay,
    jpeg_grid_offset,
    jpeg_roundtrip,
    luma,
    mask_to_boxes,
    upsample_blocks,
)

QUALITY = 90
BLOCK = 16
Z_THRESHOLD = 4.0
N_BINS = 8


def ela_maps(image: np.ndarray, quality: int = QUALITY) -> tuple[np.ndarray, np.ndarray, tuple]:
    """Return (per-pixel error, edge-conditioned block z-scores, (dy, dx) grid crop)."""
    dy, dx, strength = jpeg_grid_offset(luma(image))
    if strength < 0.08:
        dy = dx = 0
    img = image[dy:, dx:]
    rec = jpeg_roundtrip(img, quality)
    # luminance only: chroma subsampling makes every coloured edge "light up" otherwise
    err = np.abs(luma(img) - luma(rec)).astype(np.float32)

    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    e_blocks = block_reduce(err, BLOCK)
    g_blocks = block_reduce(grad, BLOCK)
    z = np.zeros_like(e_blocks)
    if e_blocks.size == 0:
        return err, z, (dy, dx)

    # Condition on edge energy: bin blocks by gradient quantile, z-score within each bin
    edges = np.unique(np.quantile(g_blocks, np.linspace(0, 1, N_BINS + 1)))
    idx = np.clip(np.searchsorted(edges, g_blocks, side="right") - 1, 0, max(len(edges) - 2, 0))
    for b in np.unique(idx):
        sel = idx == b
        vals = e_blocks[sel]
        med = np.median(vals)
        mad = 1.4826 * np.median(np.abs(vals - med))
        mad = max(mad, 0.15 + 0.05 * med)
        z[sel] = (vals - med) / mad
    z[0, :] = z[-1, :] = z[:, 0] = z[:, -1] = 0  # partial/padded blocks at the image border
    return err, z, (dy, dx)


class ElaModule(Module):
    key = "ela"
    title = "Error level analysis"
    description = "Re-compression error compared across regions of similar texture."

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:
        res = self.result()
        best_x, confs = 0.0, []
        for page in doc.pages:
            x, conf = self._page(page, res)
            best_x = max(best_x, x)
            confs.append(conf)
        res.metrics["evidence"] = round(best_x, 4)
        res.suspicion = self.calibrated(ctx, best_x, center=2.2, slope=2.2)
        res.confidence = float(np.mean(confs)) if confs else 0.0
        if res.boxes:
            res.findings.append(
                Finding(
                    "medium" if res.suspicion > 0.5 else "low",
                    f"{len(res.boxes)} region(s) re-compress differently from similar content "
                    "around them.",
                )
            )
            res.summary = res.findings[0].message
        else:
            res.summary = "Error levels are uniform across comparable regions."
        return res

    def _page(self, page: Page, res: ModuleResult) -> tuple[float, float]:
        img = page.image
        err, z, (dy, dx) = ela_maps(img)
        h, w = img.shape[:2]

        # Amplified ELA image (classic visualisation)
        scale = 255.0 / max(float(np.percentile(err, 99.7)), 1.0)
        ela_vis = np.clip(err * scale, 0, 255).astype(np.uint8)
        ela_vis = cv2.applyColorMap(ela_vis, cv2.COLORMAP_INFERNO)
        canvas = np.zeros((h, w, 3), np.uint8)
        canvas[dy:, dx:] = ela_vis
        res.artifacts.append(
            Artifact("ela", "Error level (amplified)", page.index, canvas, "image")
        )

        if z.size == 0:
            return 0.0, 0.2
        hot = (z > Z_THRESHOLD).astype(np.uint8)
        hot = cv2.morphologyEx(hot, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(hot, connectivity=8)
        x_best = 0.0
        keep = np.zeros_like(hot)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < 3:
                continue
            mean_z = float(z[labels == i].mean())
            x = math.log1p(area) * min(mean_z / 5.0, 2.0)
            x_best = max(x_best, x)
            keep[labels == i] = 1
        res.metrics.setdefault("pages", []).append(
            {
                "page": page.index,
                "outlier_fraction": round(float(hot.mean()), 5),
                "evidence": round(x_best, 4),
            }
        )

        zmap = np.zeros((h, w), np.float32)
        zmap[dy:, dx:] = upsample_blocks(np.clip(z, 0, None), BLOCK, (h - dy, w - dx))
        res.artifacts.append(
            Artifact("ela_z", "ELA anomaly map", page.index, heatmap_overlay(zmap, (h, w), 2.5, 9))
        )
        boxes = mask_to_boxes(
            keep, page.index, "ELA anomaly", scale=BLOCK, min_area=3, score_map=z / 10.0
        )
        for b in boxes:
            b.x += dx
            b.y += dy
        res.boxes.extend(boxes)

        conf = 0.8 if page.is_jpeg else 0.5
        if page.source == "pdf-render":
            conf = 0.3
        if page.resampled:
            conf *= 0.6
        return x_best, conf
