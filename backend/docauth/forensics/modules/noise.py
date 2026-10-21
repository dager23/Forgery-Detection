"""Noise-residual consistency.

Every capture device (camera sensor, scanner) leaves a characteristic noise level. Content
pasted from another source, or typed digitally onto a scan, carries a different noise level -
typically much *cleaner*. Noise is estimated per block from a median-filter residual (edges
excluded) and compared with blocks of similar brightness, since sensor noise depends on it.
Perfectly uniform patches on otherwise noisy paper are reported separately (whiteout).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from docauth.forensics.modules.base import AnalysisContext, Module
from docauth.forensics.types import Artifact, Document, Finding, ModuleResult, Page
from docauth.forensics.util import block_reduce, heatmap_overlay, mask_to_boxes, upsample_blocks

BLOCK = 32
Z_THRESHOLD = 4.0
N_BINS = 5


def noise_blocks(gray_u8: np.ndarray) -> dict[str, np.ndarray]:
    g = gray_u8.astype(np.float32)
    resid = g - cv2.medianBlur(gray_u8, 3).astype(np.float32)
    grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    edge = cv2.dilate((grad > 40).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)

    h, w = g.shape
    hb, wb = h // BLOCK, w // BLOCK
    sigma = np.full((hb, wb), np.nan, np.float32)
    if hb == 0 or wb == 0:
        return {"sigma": sigma, "mean": sigma, "sat": sigma}
    r = (
        np.abs(resid[: hb * BLOCK, : wb * BLOCK])
        .reshape(hb, BLOCK, wb, BLOCK)
        .transpose(0, 2, 1, 3)
    )
    e = edge[: hb * BLOCK, : wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK).transpose(0, 2, 1, 3)
    r = r.reshape(hb, wb, -1)
    e = e.reshape(hb, wb, -1)
    masked = np.where(e, np.nan, r)
    enough = (~e).mean(axis=2) > 0.3
    # sigma ~ sqrt(pi/2) * E|resid| (the median of |resid| collapses to 0 on clean 8-bit data)
    with np.errstate(all="ignore"):
        mean_abs = np.nanmean(masked, axis=2)
    sigma = np.where(enough, 1.2533 * mean_abs, np.nan).astype(np.float32)
    mean = block_reduce(g, BLOCK)
    sat = block_reduce(((g >= 250) | (g <= 5)).astype(np.float32), BLOCK)
    return {"sigma": sigma, "mean": mean, "sat": sat}


class NoiseModule(Module):
    key = "noise"
    title = "Noise consistency"
    description = "Sensor/scanner noise level compared across regions of similar brightness."

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:
        res = self.result()
        best_x, confs = 0.0, []
        for page in doc.pages:
            x, conf = self._page(page, res)
            best_x = max(best_x, x)
            confs.append(conf)
        res.metrics["evidence"] = round(best_x, 4)
        res.suspicion = self.calibrated(ctx, best_x, center=2.4, slope=2.0)
        res.confidence = float(np.mean(confs)) if confs else 0.0
        if any(b.label.startswith("uniform") for b in res.boxes):
            res.suspicion = max(res.suspicion, 0.6)
        if res.boxes:
            res.findings.append(
                Finding(
                    "medium" if res.suspicion > 0.5 else "low",
                    f"{len(res.boxes)} region(s) have a noise level inconsistent with the rest "
                    "of the page.",
                )
            )
            res.summary = res.findings[-1].message
        elif res.confidence < 0.3:
            res.summary = "Image is nearly noise-free (digital original); test not informative."
        else:
            res.summary = "Noise level is consistent across the page."
        return res

    def _page(self, page: Page, res: ModuleResult) -> tuple[float, float]:
        gray = cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        nb = noise_blocks(gray)
        sigma, mean, sat = nb["sigma"], nb["mean"], nb["sat"]
        if sigma.size == 0:
            return 0.0, 0.0
        valid = ~np.isnan(sigma) & (sat < 0.6)
        valid[0, :] = valid[-1, :] = valid[:, 0] = valid[:, -1] = False
        if valid.sum() < 12:
            return 0.0, 0.1
        global_sigma = float(np.median(sigma[valid]))
        ls = np.log(np.nan_to_num(sigma, nan=0.0) + 0.3)

        # z-score within brightness bins
        z = np.zeros_like(ls)
        edges = np.unique(np.quantile(mean[valid], np.linspace(0, 1, N_BINS + 1)))
        idx = np.clip(np.searchsorted(edges, mean, side="right") - 1, 0, max(len(edges) - 2, 0))
        for b in np.unique(idx[valid]):
            sel = (idx == b) & valid
            if sel.sum() < 6:
                continue
            vals = ls[sel]
            med = np.median(vals)
            mad = max(1.4826 * np.median(np.abs(vals - med)), 0.12)
            z[idx == b] = (ls[idx == b] - med) / mad
        z[~valid] = 0

        hot = (np.abs(z) > Z_THRESHOLD).astype(np.uint8)
        hot = cv2.morphologyEx(hot, cv2.MORPH_OPEN, np.ones((1, 2), np.uint8)) | cv2.morphologyEx(
            hot, cv2.MORPH_OPEN, np.ones((2, 1), np.uint8)
        )
        n, labels, stats, _ = cv2.connectedComponentsWithStats(hot, connectivity=8)
        keep = np.zeros_like(hot)
        x_best = 0.0
        total = max(int(valid.sum()), 1)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < 2 or area > 0.4 * total:  # a "region" covering half the page is the norm
                continue
            mz = float(np.abs(z[labels == i]).mean())
            x_best = max(x_best, math.log1p(area) * min(mz / 4.5, 2.0))
            keep[labels == i] = 1
        conf = float(np.clip((global_sigma - 0.3) / 1.2, 0.1, 0.8))
        if conf < 0.25:  # near noise-free page: inconsistencies are meaningless
            keep[:] = 0
            x_best = 0.0
        boxes = mask_to_boxes(keep, page.index, "noise inconsistency", BLOCK, 2, np.abs(z) / 8.0)

        # Whiteout: perfectly uniform light patches on paper that is otherwise noisy
        light = (mean > 185) & ~np.isnan(sigma)
        paper = light & (sat < 0.6)
        flat_boxes = []
        if paper.sum() >= 10:
            paper_sigma = float(np.median(sigma[paper]))
            flat = light & (np.nan_to_num(sigma, nan=99) < max(0.08, 0.12 * paper_sigma))
            if paper_sigma > 0.5 and flat.sum() < 0.25 * light.sum():
                flat_u8 = flat.astype(np.uint8)
                flat_boxes = mask_to_boxes(
                    flat_u8, page.index, "uniform patch (whiteout?)", BLOCK, 2
                )
                if flat_boxes:
                    res.findings.append(
                        Finding(
                            "medium",
                            f"Page {page.index + 1}: {len(flat_boxes)} perfectly uniform patch(es) "
                            "on noisy paper - consistent with digital whiteout.",
                            page.index,
                        )
                    )
            res.metrics.setdefault("paper_sigma", []).append(round(paper_sigma, 3))
        res.boxes.extend(boxes + flat_boxes)

        zmap = upsample_blocks(np.abs(z) * keep, BLOCK, (h, w))
        res.artifacts.append(
            Artifact(
                "noise",
                "Noise inconsistency map",
                page.index,
                heatmap_overlay(zmap, (h, w), 2.0, 8.0),
            )
        )
        sig_vis = upsample_blocks(np.nan_to_num(sigma, nan=0.0), BLOCK, (h, w))
        vmax = max(float(np.nanpercentile(sigma, 98)) if valid.any() else 1.0, 0.5)
        res.artifacts.append(
            Artifact(
                "noise_level",
                "Noise level",
                page.index,
                cv2.applyColorMap(
                    (np.clip(sig_vis / vmax, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_VIRIDIS
                ),
                "image",
            )
        )
        res.metrics.setdefault("pages", []).append(
            {
                "page": page.index,
                "global_sigma": round(global_sigma, 3),
                "evidence": round(x_best, 4),
            }
        )

        if page.source == "pdf-render":
            conf = min(conf, 0.2)
        if page.resampled:
            conf *= 0.7
        return x_best, conf
