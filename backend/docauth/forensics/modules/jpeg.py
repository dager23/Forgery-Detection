"""JPEG compression forensics.

* JPEG ghosts (Farid 2009): a region that was previously compressed at quality q1 re-compresses
  with unusually little error at q1. We look for block clusters whose error at some quality
  is anomalously low compared with similar-texture blocks.
* Block-grid alignment: JPEG leaves an 8x8 blocking grid. Content pasted from another JPEG is
  usually misaligned with the host grid, and digitally inserted content has no grid at all.
* Global double compression: a dip in the global error curve below the final quality.
"""

from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image

from docauth.forensics.modules.base import WEAK, AnalysisContext, Module
from docauth.forensics.modules.metadata import estimate_jpeg_quality
from docauth.forensics.types import Artifact, Box, Document, Finding, ModuleResult, Page
from docauth.forensics.util import (
    block_reduce,
    compact_components,
    grid_phase_profile,
    heatmap_overlay,
    jpeg_grid_offset,
    jpeg_roundtrip,
    luma,
    mask_to_boxes,
    upsample_blocks,
)

GHOST_QUALITIES = list(range(50, 100, 5))
GHOST_BLOCK = 16
GRID_WIN = 64
GRID_STEP = 32


def ghost_analysis(img: np.ndarray, last_q: int | None):
    """JPEG-ghost search in both directions.

    Returns ((kept z-map, quality, evidence, label), global error curve, double-compression q).
    """
    y = luma(img)
    gx, gy = cv2.Sobel(y, cv2.CV_32F, 1, 0), cv2.Sobel(y, cv2.CV_32F, 0, 1)
    smooth = cv2.erode((cv2.magnitude(gx, gy) < 60).astype(np.uint8), np.ones((3, 3), np.uint8))
    smooth = smooth.astype(np.float32)
    n_smooth = block_reduce(smooth, GHOST_BLOCK, np.sum)
    diffs = {}
    for q in GHOST_QUALITIES:
        d = (y - luma(jpeg_roundtrip(img, q))) ** 2 * smooth
        diffs[q] = block_reduce(d, GHOST_BLOCK, np.sum) / np.maximum(n_smooth, 1)
    stack = np.stack([diffs[q] for q in GHOST_QUALITIES])
    # usable blocks respond to re-compression at all (flat paper does not) and are mostly
    # edge-free; pixel variance is NOT required - heavily compressed pastes are very smooth
    tex = (stack.mean(axis=0) > 0.25) & (n_smooth > 0.4 * GHOST_BLOCK * GHOST_BLOCK)
    if tex.size:
        tex[0, :] = tex[-1, :] = tex[:, 0] = tex[:, -1] = False
    curve = [float(diffs[q][tex].mean()) if tex.any() else 0.0 for q in GHOST_QUALITIES]
    dq = _double_compression(curve, last_q)
    best = (None, None, 0.0, "")
    n_tex = int(tex.sum())
    if n_tex < 20:
        return best, curve, dq

    norm = stack / (stack.mean(axis=0, keepdims=True) + 1e-3)
    limit = (last_q - 8) if last_q else 90
    for qi, q in enumerate(GHOST_QUALITIES):
        if q > limit:
            continue
        r = norm[qi]
        vals = r[tex]
        med = np.median(vals)
        mad = max(1.4826 * np.median(np.abs(vals - med)), 0.03)
        tests = [((med - r) / mad, f"JPEG ghost (q~{q})")]  # earlier compression only here
        if dq == q:  # majority shows the earlier compression; find regions that lack it
            tests.append(((r - med) / mad, f"lacks earlier compression (q~{q})"))
        for z, label in tests:
            z = np.where(tex, z, 0.0)
            for comp in compact_components(z > 3.5, 6, 0.3 * n_tex, min_side=3, max_aspect=4.0):
                ev = math.log1p(int(comp.sum())) * min(float(z[comp].mean()) / 5.0, 2.0)
                if ev > best[2]:
                    kept = np.where(comp, z, 0.0)
                    best = (kept, q, ev, label)
    return best, curve, dq


def grid_alignment_map(y: np.ndarray, gdy: int, gdx: int):
    """Per-window anomaly: 1 where the local blocking grid is clearly misaligned.

    (A *missing* local grid is not flagged: flat or text-only windows in high-quality JPEGs
    legitimately show almost no blocking.)
    """
    h, w = y.shape
    rows = list(range(0, max(h - GRID_WIN, 0) + 1, GRID_STEP))
    cols = list(range(0, max(w - GRID_WIN, 0) + 1, GRID_STEP))
    amap = np.zeros((len(rows), len(cols)), np.float32)
    texture = np.zeros_like(amap, dtype=bool)
    gpx, gpy = (gdx - 1) % 8, (gdy - 1) % 8  # diff phase at the global block boundary
    for i, r0 in enumerate(rows):
        for j, c0 in enumerate(cols):
            win = y[r0 : r0 + GRID_WIN, c0 : c0 + GRID_WIN]
            at_border = r0 == 0 or c0 == 0 or r0 + GRID_WIN >= h - 8 or c0 + GRID_WIN >= w - 8
            if at_border or win.std() < 12:
                continue
            texture[i, j] = True
            cp, rp = grid_phase_profile(win)
            # phase index relative to the absolute image coordinates
            cp = np.roll(cp, c0 % 8)
            rp = np.roll(rp, r0 % 8)
            base_c, base_r = np.median(cp) + 1e-6, np.median(rp) + 1e-6
            own = min(cp.max() / base_c, rp.max() / base_r) - 1.0
            # a pasted JPEG keeps its own grid: clear peaks on both axes, both off the host grid
            off_grid = int(np.argmax(cp)) != gpx and int(np.argmax(rp)) != gpy
            dominance = min(cp.max() / (cp[gpx] + 1e-6), rp.max() / (rp[gpy] + 1e-6))
            if off_grid and own > 0.8 and dominance > 1.5:
                amap[i, j] = 1.0
    return amap, texture, rows, cols


class JpegModule(Module):
    key = "jpeg"
    title = "JPEG compression traces"
    description = "JPEG ghosts, 8x8 grid alignment and double-compression history."

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:
        res = self.result()
        best_x, confs = 0.0, []
        any_grid = False
        for page in doc.pages:
            x, conf, has_grid = self._page(page, res)
            any_grid |= has_grid
            best_x = max(best_x, x)
            confs.append(conf)
        if not any_grid:
            res.status = "skipped"
            res.confidence = 0.0
            res.summary = "No JPEG compression traces; compression analysis does not apply."
            return res
        res.metrics["evidence"] = round(best_x, 4)
        res.suspicion = self.calibrated(ctx, best_x)
        res.confidence = float(np.mean(confs))
        if res.boxes and res.suspicion < WEAK:
            res.summary = (
                f"Compression history is broadly consistent ({len(res.boxes)} weak local "
                "variation(s))."
            )
        elif res.boxes:
            res.findings.append(
                Finding(
                    "medium" if res.suspicion > 0.5 else "low",
                    f"{len(res.boxes)} region(s) carry a different JPEG compression history.",
                )
            )
            res.summary = res.findings[-1].message
        else:
            res.summary = "Compression history is consistent across the image."
        return res

    def _page(self, page: Page, res: ModuleResult) -> tuple[float, float, bool]:
        img = page.image
        h, w = img.shape[:2]
        y = luma(img)
        gdy, gdx, strength = jpeg_grid_offset(y)
        has_grid = strength > 0.08
        info = {"page": page.index, "grid_strength": round(strength, 3), "grid_offset": [gdy, gdx]}
        if not has_grid:
            res.metrics.setdefault("pages", []).append(info)
            return 0.0, 0.0, False

        last_q = None
        if page.is_jpeg and page.encoded:
            try:
                last_q = estimate_jpeg_quality(Image.open(io.BytesIO(page.encoded)).quantization)
            except Exception:  # noqa: BLE001
                last_q = None
        info["quality"] = last_q
        if (gdy, gdx) != (0, 0):
            res.findings.append(
                Finding(
                    "low",
                    f"Page {page.index + 1}: JPEG grid is shifted by ({gdx}, {gdy}) px - the image "
                    "was cropped after compression.",
                    page.index,
                )
            )
        aligned = img[gdy:, gdx:]

        # --- JPEG ghosts
        (gz, gq, gev, glabel), curve, dq = ghost_analysis(aligned, last_q)
        info["ghost_curve"] = [round(c, 3) for c in curve]
        anomaly = np.zeros((h, w), np.float32)
        boxes = []
        if gz is not None and gev > 0:
            hot = (gz > 3.5).astype(np.uint8)
            for b in mask_to_boxes(hot, page.index, glabel, GHOST_BLOCK, 3, gz / 8):
                b.x += gdx
                b.y += gdy
                boxes.append(b)
            anomaly[gdy:, gdx:] = np.maximum(
                anomaly[gdy:, gdx:],
                upsample_blocks(np.clip(gz / 8.0, 0, 1), GHOST_BLOCK, (h - gdy, w - gdx)),
            )
            info["ghost_quality"] = gq
        if dq:
            res.findings.append(
                Finding(
                    "info",
                    f"Page {page.index + 1}: image was JPEG-compressed at least twice "
                    f"(earlier quality ~{dq}).",
                    page.index,
                )
            )

        # --- grid alignment
        amap, texture, rows, cols = grid_alignment_map(y, gdy, gdx)
        grid_ev = 0.0
        if texture.sum() >= 12:
            hot = (amap >= 1.0) & texture
            for comp in compact_components(hot, 3, 0.35 * texture.sum(), min_side=1, min_fill=0.4):
                area = int(comp.sum())
                grid_ev = max(grid_ev, math.log1p(area) * 1.2)
                ys, xs = np.where(comp)
                x0, y0 = cols[xs.min()], rows[ys.min()]
                x1, y1 = cols[xs.max()] + GRID_WIN, rows[ys.max()] + GRID_WIN
                boxes.append(Box(page.index, x0, y0, x1 - x0, y1 - y0, "misaligned JPEG grid", 0.8))
                for yy, xx in zip(ys, xs, strict=True):
                    r0, c0 = rows[yy], cols[xx]
                    anomaly[r0 : r0 + GRID_WIN, c0 : c0 + GRID_WIN] = np.maximum(
                        anomaly[r0 : r0 + GRID_WIN, c0 : c0 + GRID_WIN], 0.8
                    )
        info["evidence_ghost"] = round(gev, 4)
        info["evidence_grid"] = round(grid_ev, 4)
        res.metrics.setdefault("pages", []).append(info)
        res.boxes.extend(boxes)
        res.artifacts.append(
            Artifact(
                "jpeg",
                "Compression anomaly map",
                page.index,
                heatmap_overlay(anomaly, (h, w), 0.0, 1.0),
            )
        )

        conf = 0.85 if page.is_jpeg else 0.55
        if page.resampled:
            conf *= 0.4
        return max(gev, grid_ev), conf, True


def _double_compression(curve: list[float], last_q: int | None) -> int | None:
    """Find a pronounced local minimum in the global error curve below the final quality."""
    if not curve or last_q is None:
        return None
    for i in range(1, len(curve) - 1):
        q = GHOST_QUALITIES[i]
        if q >= last_q - 7:
            break
        if curve[i] < 0.85 * curve[i - 1] and curve[i] < 0.85 * curve[i + 1]:
            return q
    return None
