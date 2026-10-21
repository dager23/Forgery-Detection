"""Forensic modules backed by the trained networks."""

from __future__ import annotations

import cv2
import numpy as np

from docauth.forensics.deep import PATCH, SEG_OVERLAP, SEG_TILE
from docauth.forensics.deep import runtime as rt
from docauth.forensics.modules.base import AnalysisContext, Module
from docauth.forensics.types import Artifact, Document, Finding, ModuleResult, Page
from docauth.forensics.util import heatmap_overlay, mask_to_boxes

MAX_PATCHES = 400
BATCH = 64


class _OnnxModule(Module):
    model_name = ""

    def available(self) -> bool:
        return rt.has_model(self.model_name)

    def unavailable_reason(self) -> str:
        return (
            f"Model '{self.model_name}.onnx' is not installed. Train it with the scripts in "
            "ml/ (see docs/TRAINING.md)."
        )

    def info(self) -> dict:
        return rt.model_info(self.model_name)


class CnnClassifierModule(_OnnxModule):
    """SRM-initialised CNN patch classifier with feature fusion (README module 2)."""

    key = "cnn"
    title = "SRM-CNN tamper classifier"
    description = (
        "CNN whose first layer is initialised with SRM high-pass filters, applied densely to "
        "patches; patch scores are fused into a real/fake decision."
    )
    model_name = "classifier"

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:
        res = self.result()
        info = self.info()
        thr = float(info.get("threshold", 0.5))
        page_scores = []
        for page in doc.pages:
            page_scores.append(self._page(page, res))
        p_fake = max(page_scores) if page_scores else 0.0
        res.metrics.update(
            {"p_fake": round(p_fake, 4), "threshold": thr, "model": info.get("version", "unknown")}
        )
        # recentre so the model's own operating threshold maps to suspicion 0.5
        res.suspicion = float(self.calibrated(ctx, p_fake, center=thr))
        res.metrics["evidence"] = round(p_fake, 4)
        res.confidence = float(info.get("confidence", 0.75))
        if any(p.resampled for p in doc.pages):
            res.confidence *= 0.7
        label = "manipulated" if p_fake >= thr else "authentic"
        res.summary = (
            f"Network output: real {100 * (1 - p_fake):.0f}% / fake {100 * p_fake:.0f}% -> {label}."
        )
        if p_fake >= thr:
            res.findings.append(
                Finding(
                    "high" if p_fake > 0.85 else "medium",
                    f"The CNN classifies the image as manipulated ({100 * p_fake:.0f}%).",
                )
            )
        return res

    def _page(self, page: Page, res: ModuleResult) -> float:
        img = page.image
        h, w = img.shape[:2]
        if min(h, w) < PATCH:
            pad_h, pad_w = max(0, PATCH - h), max(0, PATCH - w)
            img = cv2.copyMakeBorder(img, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)
            h, w = img.shape[:2]
        stride = PATCH * 3 // 4
        n_est = ((h - PATCH) // stride + 1) * ((w - PATCH) // stride + 1)
        while n_est > MAX_PATCHES:
            stride += 16
            n_est = ((h - PATCH) // stride + 1) * ((w - PATCH) // stride + 1)
        ys = list(range(0, h - PATCH + 1, stride))
        xs = list(range(0, w - PATCH + 1, stride))
        coords, patches = [], []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for y in ys:
            for x in xs:
                if gray[y : y + PATCH, x : x + PATCH].std() < 3:
                    continue  # flat patch: no forensic signal
                coords.append((y, x))
                patches.append(rt.to_rgb01(img[y : y + PATCH, x : x + PATCH]))
        if not patches:
            return 0.0
        sess = rt.session(self.model_name)
        probs = []
        arr = np.stack(patches)
        for i in range(0, len(arr), BATCH):
            logits = sess.run(None, {"patches": arr[i : i + BATCH]})[0]
            e = np.exp(logits - logits.max(axis=1, keepdims=True))
            probs.append(e[:, 1] / e.sum(axis=1))
        p = np.concatenate(probs)
        # feature fusion: mean of the top-k most suspicious patches
        k = max(3, int(0.03 * len(p)))
        score = float(np.sort(p)[-k:].mean())

        acc = np.zeros((h, w), np.float32)
        cnt = np.zeros((h, w), np.float32)
        for (y, x), pv in zip(coords, p, strict=True):
            acc[y : y + PATCH, x : x + PATCH] += pv
            cnt[y : y + PATCH, x : x + PATCH] += 1
        pmap = np.where(cnt > 0, acc / np.maximum(cnt, 1), 0)[: page.shape[0], : page.shape[1]]
        res.artifacts.append(
            Artifact(
                "cnn",
                "CNN patch probability",
                page.index,
                heatmap_overlay(pmap, page.shape, 0.3, 1.0, blur=True),
            )
        )
        res.metrics.setdefault("pages", []).append(
            {"page": page.index, "p_fake": round(score, 4), "patches": len(p)}
        )
        return score


class SegmentationModule(_OnnxModule):
    """Two-stream RGB + DCT network producing a pixel heatmap (README module 3)."""

    key = "segmentation"
    title = "Pixel manipulation analyzer"
    description = (
        "Two-stream network (RGB stream + DCT stream on the Y channel, sensitive to double "
        "JPEG compression) predicting which pixels were manipulated."
    )
    model_name = "segmenter"

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:
        res = self.result()
        info = self.info()
        thr = float(info.get("threshold", 0.5))
        worst_pct, worst_peak = 0.0, 0.0
        for page in doc.pages:
            pct, peak = self._page(page, res, thr)
            worst_pct, worst_peak = max(worst_pct, pct), max(worst_peak, peak)
        res.metrics.update(
            {
                "manipulated_pct": round(worst_pct, 3),
                "peak_probability": round(worst_peak, 4),
                "threshold": thr,
                "model": info.get("version", "unknown"),
            }
        )
        # evidence = confidence of the strongest localised region (a forged value can be 0.1 %
        # of a page, so area must not dilute it); isolated hot pixels without a region count half
        region_peak = max((b.score for b in res.boxes), default=0.0)
        x = region_peak if res.boxes else 0.5 * worst_peak
        res.metrics["evidence"] = round(x, 4)
        res.suspicion = float(self.calibrated(ctx, x, center=thr * 0.8))
        res.confidence = float(info.get("confidence", 0.75))
        if any(p.resampled for p in doc.pages):
            res.confidence *= 0.7
        res.summary = f"{worst_pct:.2f}% of pixels predicted as manipulated."
        if res.boxes:
            res.findings.append(
                Finding(
                    "high" if res.suspicion > 0.75 else "medium",
                    f"{len(res.boxes)} manipulated region(s) localised "
                    f"({worst_pct:.2f}% of pixels).",
                )
            )
        return res

    def _page(self, page: Page, res: ModuleResult, thr: float) -> tuple[float, float]:
        prob = segment(page.image, self.model_name)
        h, w = page.shape
        hot = (prob > thr).astype(np.uint8)
        hot = cv2.morphologyEx(hot, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        min_area = max(64, int(0.0004 * h * w))
        boxes = mask_to_boxes(hot, page.index, "manipulated pixels", 1.0, min_area, prob)
        res.boxes.extend(boxes)
        pct = float(hot.mean() * 100)
        peak = float(np.percentile(prob, 99.9)) if prob.size else 0.0
        res.artifacts.append(
            Artifact(
                "segmentation",
                "Pixel manipulation heatmap",
                page.index,
                heatmap_overlay(prob, (h, w), 0.2, 1.0, blur=False),
            )
        )
        res.metrics.setdefault("pages", []).append(
            {"page": page.index, "manipulated_pct": round(pct, 3), "peak": round(peak, 4)}
        )
        return pct, peak


def segment(image: np.ndarray, model_name: str = "segmenter") -> np.ndarray:
    """Tile the image (8-aligned so the JPEG grid is preserved), run the model, blend tiles."""
    h, w = image.shape[:2]
    sess = rt.session(model_name)
    tile = SEG_TILE
    if max(h, w) <= tile:
        ph, pw = -(-h // 32) * 32, -(-w // 32) * 32
        padded = cv2.copyMakeBorder(image, 0, ph - h, 0, pw - w, cv2.BORDER_REFLECT)
        logits = sess.run(None, {"image": rt.to_rgb01(padded)[None]})[0][0, 0]
        return _sigmoid(logits[:h, :w])
    # pad to multiples of 8 so every tile origin stays on the JPEG grid and edges are covered
    ph, pw = max(tile, -(-h // 8) * 8), max(tile, -(-w // 8) * 8)
    padded = cv2.copyMakeBorder(image, 0, ph - h, 0, pw - w, cv2.BORDER_REFLECT)
    stride = tile - SEG_OVERLAP
    ys = list(range(0, ph - tile + 1, stride))
    xs = list(range(0, pw - tile + 1, stride))
    if ys[-1] != ph - tile:
        ys.append(ph - tile)
    if xs[-1] != pw - tile:
        xs.append(pw - tile)
    acc = np.zeros((ph, pw), np.float32)
    wsum = np.zeros((ph, pw), np.float32)
    ramp = np.minimum(np.arange(tile) + 1, np.arange(tile)[::-1] + 1).astype(np.float32)
    weight = np.minimum.outer(ramp, ramp) / ramp.max()
    for y in ys:
        for x in xs:
            crop = padded[y : y + tile, x : x + tile]
            logits = sess.run(None, {"image": rt.to_rgb01(crop)[None]})[0][0, 0]
            acc[y : y + tile, x : x + tile] += _sigmoid(logits) * weight
            wsum[y : y + tile, x : x + tile] += weight
    return (acc / np.maximum(wsum, 1e-6))[:h, :w]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40, 40)))
