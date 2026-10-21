"""Template matching against a ground-truth document using SSIM (README module 4).

1. Align the submitted page to the reference template (SIFT + RANSAC homography).
2. Normalise illumination, compute an SSIM dissimilarity map and "ink" difference maps.
3. Ignore the template's variable fields (name, photo, date...) and report remaining
   differences as boxes labelled *added*, *missing* or *altered* content.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from docauth.forensics.modules.base import AnalysisContext, Module
from docauth.forensics.types import Artifact, Box, Document, Finding, ModuleResult
from docauth.forensics.util import downscale_for, heatmap_overlay

FEATURE_SIDE = 1400
COMPARE_SIDE = 1600
MIN_INLIERS = 20


def _features(gray: np.ndarray):
    sift = cv2.SIFT_create(nfeatures=5000)
    return sift.detectAndCompute(gray, None)


def align(doc_img: np.ndarray, tpl_img: np.ndarray) -> dict | None:
    """Homography mapping document pixels -> template pixels, with quality stats."""
    d_small, fd = downscale_for(cv2.cvtColor(doc_img, cv2.COLOR_BGR2GRAY), FEATURE_SIDE)
    t_small, ft = downscale_for(cv2.cvtColor(tpl_img, cv2.COLOR_BGR2GRAY), FEATURE_SIDE)
    kd, dd = _features(d_small)
    kt, dt = _features(t_small)
    if dd is None or dt is None or len(kd) < MIN_INLIERS or len(kt) < MIN_INLIERS:
        return None
    knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(dd, dt, k=2)
    good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < MIN_INLIERS:
        return None
    src = np.float32([kd[m.queryIdx].pt for m in good])
    dst = np.float32([kt[m.trainIdx].pt for m in good])
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None:
        return None
    n_in = int(inl.sum())
    if n_in < MIN_INLIERS:
        return None
    # lift to full resolution: H_full = S_t^-1 . H . S_d
    S_d = np.diag([fd, fd, 1.0])
    S_t_inv = np.diag([1 / ft, 1 / ft, 1.0])
    H_full = S_t_inv @ H @ S_d
    h, w = doc_img.shape[:2]
    corners = cv2.perspectiveTransform(np.float32([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]), H_full)
    th, tw = tpl_img.shape[:2]
    area = cv2.contourArea(corners)
    if not cv2.isContourConvex(corners.astype(np.int32)) or not (0.25 < area / (tw * th) < 4.0):
        return None
    return {"H": H_full, "inliers": n_in, "ratio": n_in / len(good)}


def _normalise(gray: np.ndarray) -> np.ndarray:
    g = gray.astype(np.float32)
    k = max(15, (max(g.shape) // 30) | 1)
    bg = cv2.morphologyEx(g, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 3)
    n = np.clip(g / np.maximum(bg, 1.0) * 255.0, 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(n, (3, 3), 0)


def _ink(n: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        n, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 18
    ).astype(bool)


def compare(tpl_img: np.ndarray, warped: np.ndarray, valid: np.ndarray, ignore: np.ndarray):
    """Return (dissimilarity map, labelled change boxes in template px, stats)."""
    t = _normalise(cv2.cvtColor(tpl_img, cv2.COLOR_BGR2GRAY))
    d = _normalise(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY))
    h, w = t.shape
    _, S = structural_similarity(
        t, d, win_size=7, gaussian_weights=True, sigma=1.5, data_range=255, full=True
    )
    dssim = np.clip((1.0 - S) / 2.0, 0, 1).astype(np.float32)

    tol = max(3, int(round(0.004 * w)))
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * tol + 1, 2 * tol + 1))
    ink_t, ink_d = _ink(t), _ink(d)
    added = ink_d & ~cv2.dilate(ink_t.astype(np.uint8), kern).astype(bool)
    missing = ink_t & ~cv2.dilate(ink_d.astype(np.uint8), kern).astype(bool)
    struct = cv2.dilate((dssim > 0.12).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    usable = valid & ~ignore
    added &= struct & usable
    missing &= struct & usable

    changed = (added | missing).astype(np.uint8)
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    cw, ch = max(3, int(0.012 * w)), max(3, int(0.006 * h))
    merged = cv2.morphologyEx(changed, cv2.MORPH_CLOSE, np.ones((ch, cw), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    min_area = max(12, int(0.00012 * h * w))
    regions = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        comp = labels == i
        n_add = int((added & comp).sum())
        n_miss = int((missing & comp).sum())
        if n_add + n_miss < min_area or min(bw, bh) < 3:
            continue
        if n_add > 3 * n_miss:
            label = "added content"
        elif n_miss > 3 * n_add:
            label = "missing content"
        else:
            label = "altered content"
        score = float(np.clip(dssim[comp].mean() * 4, 0.3, 1.0))
        regions.append(
            {
                "x": int(x),
                "y": int(y),
                "w": int(bw),
                "h": int(bh),
                "label": label,
                "score": score,
                "pixels": n_add + n_miss,
            }
        )
    regions.sort(key=lambda r: r["pixels"], reverse=True)
    stats_out = {
        "changed_pct": float(changed.sum() / max(int(usable.sum()), 1) * 100.0),
        "mean_ssim": float(S[usable].mean()) if usable.any() else 0.0,
        "ignored_pct": float(ignore.mean() * 100.0),
    }
    return dssim * usable, regions[:20], stats_out


def ignore_mask(shape: tuple[int, int], regions: list[dict]) -> np.ndarray:
    h, w = shape
    m = np.zeros((h, w), bool)
    for r in regions or []:
        x0, y0 = int(r["x"] * w), int(r["y"] * h)
        x1, y1 = int((r["x"] + r["w"]) * w), int((r["y"] + r["h"]) * h)
        m[max(0, y0) : min(h, y1), max(0, x0) : min(w, x1)] = True
    return m


class TemplateModule(Module):
    key = "template"
    title = "Template matching (SSIM)"
    description = "Compares the document with a verified original of the same document type."

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:
        res = self.result()
        tpl, page, al = self._pick(doc, ctx, res)
        if tpl is None:
            res.status = "skipped"
            res.confidence = 0.0
            res.summary = "No reference template selected or recognised."
            return res
        if al is None:
            res.confidence = 0.5
            res.suspicion = 0.5
            res.findings.append(
                Finding(
                    "medium",
                    f'Document layout could not be aligned with template "{tpl.name}" - '
                    "it is a different document type or heavily altered.",
                )
            )
            res.summary = res.findings[-1].message
            return res

        res.metrics["template"] = tpl.name
        res.metrics["alignment_inliers"] = al["inliers"]
        res.metrics["alignment_ratio"] = round(al["ratio"], 3)

        # Compare in template space at a bounded resolution
        tpl_small, ft = downscale_for(tpl.image, COMPARE_SIDE)
        th, tw = tpl_small.shape[:2]
        S = np.diag([ft, ft, 1.0])
        H = S @ al["H"]  # doc -> small template
        warped = cv2.warpPerspective(page.image, H, (tw, th), flags=cv2.INTER_AREA)
        valid = cv2.warpPerspective(
            np.full(page.shape, 255, np.uint8), H, (tw, th), flags=cv2.INTER_NEAREST
        )
        valid = cv2.erode(valid, np.ones((9, 9), np.uint8)) > 0
        ign = ignore_mask((th, tw), tpl.ignore_regions)
        dmap, regions, stats = compare(tpl_small, warped, valid, ign)
        res.metrics.update({k: round(v, 4) for k, v in stats.items()})
        res.metrics["regions"] = len(regions)

        # Map regions back onto the uploaded page for display
        H_inv = np.linalg.inv(H)
        ph, pw = page.shape
        for r in regions:
            pts = np.float32(
                [
                    [[r["x"], r["y"]]],
                    [[r["x"] + r["w"], r["y"]]],
                    [[r["x"] + r["w"], r["y"] + r["h"]]],
                    [[r["x"], r["y"] + r["h"]]],
                ]
            )
            q = cv2.perspectiveTransform(pts, H_inv).reshape(-1, 2)
            x0, y0 = np.clip(q.min(axis=0), 0, [pw - 1, ph - 1])
            x1, y1 = np.clip(q.max(axis=0), 0, [pw - 1, ph - 1])
            res.boxes.append(
                Box(
                    page.index, int(x0), int(y0), int(x1 - x0), int(y1 - y0), r["label"], r["score"]
                )
            )
        back = cv2.warpPerspective(dmap, H_inv, (pw, ph), flags=cv2.INTER_LINEAR)
        res.artifacts.append(
            Artifact(
                "template_diff",
                f'Differences vs "{tpl.name}"',
                page.index,
                heatmap_overlay(back, (ph, pw), 0.08, 0.45, alpha_floor=0.2),
            )
        )
        res.artifacts.append(
            Artifact(
                "template_side",
                "Template vs aligned document",
                page.index,
                _side_by_side(tpl_small, warped, regions, ign),
                "image",
            )
        )

        x = (
            (math.log1p(len(regions)) + math.log1p(stats["changed_pct"] * 10))
            if regions
            else (math.log1p(stats["changed_pct"] * 2))
        )
        res.metrics["evidence"] = round(x, 4)
        res.suspicion = self.calibrated(ctx, x)
        res.confidence = float(np.clip(0.5 + al["ratio"] * 0.6, 0.5, 0.95))
        if regions:
            kinds = {}
            for r in regions:
                kinds[r["label"]] = kinds.get(r["label"], 0) + 1
            desc = ", ".join(f"{v} {k}" for k, v in kinds.items())
            res.findings.append(
                Finding(
                    "high" if res.suspicion > 0.6 else "medium",
                    f'Compared with "{tpl.name}": {desc} outside the variable fields.',
                    page.index,
                )
            )
            res.summary = res.findings[-1].message
        else:
            res.summary = (
                f'Matches template "{tpl.name}" (SSIM {stats["mean_ssim"]:.2f}) outside the '
                "variable fields."
            )
        return res

    def _pick(self, doc: Document, ctx: AnalysisContext, res: ModuleResult):
        if ctx.template is not None:
            for page in doc.pages:
                al = align(page.image, ctx.template.image)
                if al is not None:
                    return ctx.template, page, al
            return ctx.template, doc.pages[0], None
        best = (None, None, None)
        for tpl in ctx.candidate_templates:
            al = align(doc.pages[0].image, tpl.image)
            if (
                al
                and al["inliers"] >= 30
                and al["ratio"] >= 0.25
                and (best[2] is None or al["inliers"] > best[2]["inliers"])
            ):
                best = (tpl, doc.pages[0], al)
        if best[0] is not None:
            res.metrics["auto_selected"] = True
            res.findings.append(Finding("info", f'Template auto-detected: "{best[0].name}".'))
        return best


def _side_by_side(tpl: np.ndarray, warped: np.ndarray, regions: list[dict], ign: np.ndarray):
    a, b = tpl.copy(), warped.copy()
    shade = np.zeros_like(a)
    shade[ign] = (255, 180, 60)
    a = cv2.addWeighted(a, 1.0, shade, 0.25, 0)
    t = max(2, a.shape[1] // 400)
    colors = {
        "added content": (0, 0, 230),
        "missing content": (230, 120, 0),
        "altered content": (180, 0, 200),
    }
    for r in regions:
        c = colors.get(r["label"], (0, 0, 230))
        for img in (a, b):
            cv2.rectangle(img, (r["x"], r["y"]), (r["x"] + r["w"], r["y"] + r["h"]), c, t)
    gap = np.full((a.shape[0], max(8, a.shape[1] // 80), 3), 255, np.uint8)
    return np.hstack([a, gap, b])
