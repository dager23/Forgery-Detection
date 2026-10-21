"""Copy-move (cloned region) detection.

SIFT keypoints are matched against the same image (generalised 2-NN ratio test), then groups of
matches sharing one geometric transform are found with iterative RANSAC. Repeated glyphs in
documents produce matches with *random* displacements, so they rarely form a large consistent
group, whereas a cloned stamp, signature or number does.
"""

from __future__ import annotations

import cv2
import numpy as np

from docauth.forensics.modules.base import AnalysisContext, Module
from docauth.forensics.types import Artifact, Box, Document, Finding, ModuleResult, Page
from docauth.forensics.util import downscale_for

MAX_SIDE = 1800
RATIO = 0.6
MIN_INLIERS = 10
MAX_CLUSTERS = 5
MIN_RESIDUAL_CORR = 0.3


def find_clones(gray: np.ndarray) -> list[dict]:
    h, w = gray.shape
    min_dist = max(24.0, 0.03 * max(h, w))
    sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.02)
    kps, desc = sift.detectAndCompute(gray, None)
    if desc is None or len(kps) < 3 * MIN_INLIERS:
        return []
    pts = np.float32([k.pt for k in kps])
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    knn = matcher.knnMatch(desc, desc, k=min(6, len(kps)))
    pairs = set()
    for row in knn:
        row = [m for m in row if m.trainIdx != m.queryIdx]
        for a, b in zip(row, row[1:], strict=False):  # generalised 2NN
            if a.distance >= RATIO * max(b.distance, 1e-6):
                break
            i, j = a.queryIdx, a.trainIdx
            if np.linalg.norm(pts[i] - pts[j]) < min_dist:
                continue
            pairs.add((min(i, j), max(i, j)))
    if len(pairs) < MIN_INLIERS:
        return []
    src = np.float32([pts[i] for i, _ in pairs])
    dst = np.float32([pts[j] for _, j in pairs])

    clusters = []
    remaining = np.ones(len(src), bool)
    for _ in range(MAX_CLUSTERS):
        idx = np.where(remaining)[0]
        if idx.size < MIN_INLIERS:
            break
        M, inl = cv2.estimateAffinePartial2D(
            src[idx], dst[idx], method=cv2.RANSAC, ransacReprojThreshold=4.0, maxIters=3000
        )
        if M is None or inl is None:
            break
        inl = inl.ravel().astype(bool)
        members = idx[inl]
        if members.size < MIN_INLIERS:
            break
        remaining[members] = False
        scale = float(np.hypot(M[0, 0], M[1, 0]))
        shift = float(np.hypot(M[0, 2], M[1, 2]))
        s, d = src[members], dst[members]
        spread = min(np.ptp(s[:, 0]) * np.ptp(s[:, 1]), np.ptp(d[:, 0]) * np.ptp(d[:, 1]))
        # skip implausible scales and degenerate groups whose keypoints collapse onto a
        # line or a single glyph (table rules, repeated characters)
        if not (0.5 < scale < 2.0) or spread < (min_dist**2) * 0.25:
            continue
        clusters.append(
            {
                "src": s,
                "dst": d,
                "M": M,
                "n": int(members.size),
                "scale": scale,
                "angle": float(np.degrees(np.arctan2(M[1, 0], M[0, 0]))),
                "shift": shift,
            }
        )
    return clusters


def residual_correlation(gray: np.ndarray, M: np.ndarray, src: np.ndarray, pad: int) -> float:
    """Correlation of the high-pass residual between a source region and its supposed copy.

    A real clone copies the paper/sensor noise along with the content, so residuals match.
    Legitimately repeated content (the same word printed twice, a regular layout) shares glyph
    shapes but has independent noise. Strong edges are excluded so shapes don't dominate.
    """
    h, w = gray.shape
    g = gray.astype(np.float32)
    hp = g - cv2.GaussianBlur(g, (0, 0), 1.0)
    grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    flat = cv2.erode((grad < 40).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    x0, y0 = np.maximum(src.min(axis=0).astype(int) - pad, 0)
    x1, y1 = np.minimum(src.max(axis=0).astype(int) + pad, [w - 1, h - 1])
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0
    angle = np.degrees(np.arctan2(M[1, 0], M[0, 0]))
    scale = np.hypot(M[0, 0], M[1, 0])
    best = 0.0
    if abs(angle) < 1.0 and abs(scale - 1) < 0.02:
        tx, ty = int(round(M[0, 2])), int(round(M[1, 2]))
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                dx, dy = tx + ox, ty + oy
                if not (x0 + dx >= 0 and x1 + dx < w and y0 + dy >= 0 and y1 + dy < h):
                    continue
                a = hp[y0:y1, x0:x1]
                b = hp[y0 + dy : y1 + dy, x0 + dx : x1 + dx]
                m = flat[y0:y1, x0:x1] & flat[y0 + dy : y1 + dy, x0 + dx : x1 + dx]
                best = max(best, _pearson(a, b, m))
        return best
    warped = cv2.warpAffine(hp, M, (w, h), flags=cv2.INTER_LINEAR)
    wflat = cv2.warpAffine(flat.astype(np.uint8), M, (w, h), flags=cv2.INTER_NEAREST) > 0
    corners = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    dc = cv2.transform(corners[None], M)[0]
    X0, Y0 = np.maximum(dc.min(axis=0).astype(int), 0)
    X1, Y1 = np.minimum(dc.max(axis=0).astype(int), [w - 1, h - 1])
    if X1 - X0 < 8 or Y1 - Y0 < 8:
        return 0.0
    m = flat[Y0:Y1, X0:X1] & wflat[Y0:Y1, X0:X1] & (warped[Y0:Y1, X0:X1] != 0)
    return _pearson(hp[Y0:Y1, X0:X1], warped[Y0:Y1, X0:X1], m)


def _pearson(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    if m.sum() < 150:
        return 0.0
    a, b = a[m].astype(np.float64), b[m].astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    if den < 1e-6 or np.sqrt((a * a).mean()) < 0.3:  # no measurable noise to compare
        return 0.0
    return float((a * b).sum() / den)


def _bbox(p: np.ndarray, f: float, pad: int) -> tuple[int, int, int, int]:
    x0, y0 = p.min(axis=0) / f
    x1, y1 = p.max(axis=0) / f
    return int(x0) - pad, int(y0) - pad, int(x1 - x0) + 2 * pad, int(y1 - y0) + 2 * pad


class CopyMoveModule(Module):
    key = "copymove"
    title = "Copy-move detection"
    description = "Finds regions cloned from elsewhere in the same image."

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:
        res = self.result()
        best = 0
        for page in doc.pages:
            best = max(best, self._page(page, res, ctx))
        res.metrics["max_inliers"] = best
        x = float(np.log1p(best)) if best else 0.0
        res.metrics["evidence"] = round(x, 4)
        res.suspicion = self.calibrated(ctx, x) if best else 0.0
        res.confidence = 0.8
        if best:
            res.summary = res.findings[-1].message
        else:
            res.summary = "No cloned regions found."
        return res

    def _page(self, page: Page, res: ModuleResult, ctx: AnalysisContext) -> int:
        small, f = downscale_for(page.image, MAX_SIDE)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        full_gray = cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY)
        clusters = []
        rejected = 0
        for c in find_clones(gray):
            M_full = c["M"].copy()
            M_full[:, 2] /= f
            corr = residual_correlation(full_gray, M_full, c["src"] / f, pad=6)
            c["residual_corr"] = round(corr, 3)
            if corr >= MIN_RESIDUAL_CORR:
                clusters.append(c)
            else:
                rejected += 1
        res.metrics.setdefault("pages", []).append(
            {
                "page": page.index,
                "clusters": len(clusters),
                "rejected_repeats": rejected,
                "residual_corr": [c["residual_corr"] for c in clusters],
            }
        )
        h, w = page.shape
        overlay = np.zeros((h, w, 4), np.uint8)
        best = 0
        pad = max(4, int(0.01 * max(h, w)))
        t = max(1, min(h, w) // 600)
        for k, c in enumerate(clusters):
            best = max(best, c["n"])
            score = float(min(1.0, c["n"] / 40))
            for pts, label in ((c["src"], "cloned source"), (c["dst"], "cloned copy")):
                x, y, bw, bh = _bbox(pts, f, pad)
                x, y = max(0, x), max(0, y)
                res.boxes.append(Box(page.index, x, y, bw, bh, f"{label} #{k + 1}", score))
                color = (255, 200, 0) if label == "cloned source" else (0, 60, 255)
                cv2.rectangle(overlay, (x, y), (x + bw, y + bh), (*color, 235), t + 1)
            for a, b in zip(c["src"][:120], c["dst"][:120], strict=False):
                pa = tuple(int(v) for v in a / f)
                pb = tuple(int(v) for v in b / f)
                cv2.line(overlay, pa, pb, (0, 255, 120, 190), t)
                cv2.circle(overlay, pa, t + 2, (255, 200, 0, 255), -1)
                cv2.circle(overlay, pb, t + 2, (0, 60, 255, 255), -1)
            res.findings.append(
                Finding(
                    "high" if c["n"] >= 25 else "medium",
                    f"Page {page.index + 1}: a region appears to be cloned ({c['n']} matching "
                    f"keypoints, shifted {c['shift'] / f:.0f}px, rotated {c['angle']:.0f} deg, "
                    f"noise correlation {c['residual_corr']:.2f}).",
                    page.index,
                )
            )
        res.artifacts.append(Artifact("copymove", "Cloned regions", page.index, overlay, "overlay"))
        return best
