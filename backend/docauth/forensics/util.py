"""Image helpers shared by the forensic modules."""

from __future__ import annotations

import cv2
import numpy as np

from docauth.forensics.types import Box


def gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def luma(image: np.ndarray) -> np.ndarray:
    """JPEG luminance channel (Y of YCrCb) as float32."""
    if image.ndim == 2:
        return image.astype(np.float32)
    return cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)[:, :, 0].astype(np.float32)


def jpeg_roundtrip(image: np.ndarray, quality: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:  # pragma: no cover - cv2 always encodes uint8 images
        raise RuntimeError("JPEG encode failed")
    flag = cv2.IMREAD_GRAYSCALE if image.ndim == 2 else cv2.IMREAD_COLOR
    return cv2.imdecode(buf, flag)


def block_reduce(arr: np.ndarray, block: int, fn=np.mean) -> np.ndarray:
    """Reduce an (H, W) array over non-overlapping block x block tiles (edges cropped)."""
    h, w = arr.shape[:2]
    hb, wb = h // block, w // block
    if hb == 0 or wb == 0:
        return np.zeros((0, 0), dtype=np.float32)
    a = arr[: hb * block, : wb * block].reshape(hb, block, wb, block)
    return fn(a, axis=(1, 3)).astype(np.float32)


def robust_z(values: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Median/MAD z-score, statistics computed only where ``mask`` is True."""
    ref = values[mask] if mask is not None else values.ravel()
    if ref.size == 0:
        return np.zeros_like(values, dtype=np.float32)
    med = float(np.median(ref))
    mad = float(np.median(np.abs(ref - med))) * 1.4826
    mad = max(mad, 1e-6 + 0.02 * abs(med))
    return ((values - med) / mad).astype(np.float32)


def upsample_blocks(blocks: np.ndarray, block: int, shape: tuple[int, int]) -> np.ndarray:
    """Expand a block map back to pixel resolution (nearest), padding the cropped edge."""
    h, w = shape
    up = np.repeat(np.repeat(blocks, block, axis=0), block, axis=1)
    out = np.zeros((h, w), dtype=up.dtype)
    out[: up.shape[0], : up.shape[1]] = up[:h, :w]
    return out


def heatmap_overlay(
    values: np.ndarray,
    shape: tuple[int, int],
    vmin: float = 0.0,
    vmax: float = 1.0,
    alpha_floor: float = 0.15,
    blur: bool = True,
) -> np.ndarray:
    """Render a scalar map as a transparent BGRA overlay (low values fully transparent)."""
    h, w = shape
    v = values.astype(np.float32)
    if v.shape != (h, w):
        v = cv2.resize(v, (w, h), interpolation=cv2.INTER_LINEAR)
    if blur:
        k = max(3, (min(h, w) // 150) | 1)
        v = cv2.GaussianBlur(v, (k, k), 0)
    n = np.clip((v - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    colored = cv2.applyColorMap((n * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    alpha = np.where(n < alpha_floor, 0, np.clip(0.25 + 0.7 * n, 0, 0.95))
    return np.dstack([colored, (alpha * 255).astype(np.uint8)])


def colorize(values: np.ndarray, vmin: float, vmax: float, cmap=cv2.COLORMAP_JET) -> np.ndarray:
    n = np.clip((values.astype(np.float32) - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    return cv2.applyColorMap((n * 255).astype(np.uint8), cmap)


def mask_to_boxes(
    mask: np.ndarray,
    page: int,
    label: str,
    scale: float = 1.0,
    min_area: int = 0,
    score_map: np.ndarray | None = None,
    max_boxes: int = 12,
) -> list[Box]:
    """Connected components of a binary mask -> boxes (``scale`` maps mask px to page px)."""
    m = (mask > 0).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    boxes: list[Box] = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        score = 1.0
        if score_map is not None:
            score = float(np.clip(score_map[y : y + h, x : x + w].max(), 0, 1))
        boxes.append(
            Box(page, int(x * scale), int(y * scale), int(w * scale), int(h * scale), label, score)
        )
    boxes.sort(key=lambda b: b.w * b.h * b.score, reverse=True)
    return boxes[:max_boxes]


def draw_boxes(image: np.ndarray, boxes: list[Box], color=(0, 0, 255)) -> np.ndarray:
    out = image.copy()
    t = max(2, min(image.shape[:2]) // 400)
    for b in boxes:
        cv2.rectangle(out, (b.x, b.y), (b.x + b.w, b.y + b.h), color, t)
    return out


def boxes_overlay(shape: tuple[int, int], boxes: list[Box], color=(40, 40, 255)) -> np.ndarray:
    """Transparent BGRA overlay with filled + outlined boxes."""
    h, w = shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    t = max(2, min(h, w) // 350)
    for b in boxes:
        x2, y2 = min(w - 1, b.x + b.w), min(h - 1, b.y + b.h)
        out[b.y : y2, b.x : x2] = (*color, 60)
        cv2.rectangle(out, (b.x, b.y), (x2, y2), (*color, 235), t)
    return out


def jpeg_grid_offset(y: np.ndarray) -> tuple[int, int, float]:
    """Estimate the 8x8 JPEG block grid origin (dy, dx) and its strength.

    Blocking artefacts are small luminance steps across block boundaries. Clipped first
    differences (so real edges don't dominate) averaged per column/row phase mod 8 peak at the
    boundary phase. Strength ~ (peak / median) - 1, close to 0 when there is no grid.
    """
    col_phase, row_phase = grid_phase_profile(y)
    if col_phase is None:
        return 0, 0, 0.0
    px, py = int(np.argmax(col_phase)), int(np.argmax(row_phase))
    sx = col_phase[px] / (np.median(col_phase) + 1e-6) - 1.0
    sy = row_phase[py] / (np.median(row_phase) + 1e-6) - 1.0
    # d[:, p] measures the step between columns p and p+1, so the block origin is (p + 1) mod 8
    return (py + 1) % 8, (px + 1) % 8, float(min(sx, sy))


def grid_phase_profile(y: np.ndarray, clip: float = 6.0):
    """Mean small |first difference| for each of the 8 column and row phases.

    Differences above ``clip`` are real edges (text, ruled lines), not blocking artefacts, and
    are left out entirely - otherwise one straight line creates a fake grid phase.
    """
    y = y.astype(np.float32)
    if min(y.shape) < 16:
        return None, None
    ax = np.abs(np.diff(y, axis=1))
    ay = np.abs(np.diff(y, axis=0))
    mx, my = ax < clip, ay < clip
    dx = (ax * mx).sum(axis=0) / np.maximum(mx.sum(axis=0), 1)
    dy = (ay * my).sum(axis=1) / np.maximum(my.sum(axis=1), 1)
    col_phase = np.array([dx[p::8].mean() for p in range(8)])
    row_phase = np.array([dy[p::8].mean() for p in range(8)])
    return col_phase, row_phase


def compact_components(
    mask: np.ndarray,
    min_area: int,
    max_area: float,
    min_side: int = 2,
    min_fill: float = 0.3,
    max_aspect: float = 10.0,
):
    """Connected components that look like regions, not thin strips (ruled lines, borders)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or area > max_area or min(w, h) < min_side:
            continue
        if area / float(w * h) < min_fill or max(w, h) / max(min(w, h), 1) > max_aspect:
            continue
        out.append(labels == i)
    return out


def textured_mask(image_gray: np.ndarray, block: int, min_std: float = 2.0) -> np.ndarray:
    """Per-block flag: True where the block has enough texture to carry forensic signal."""
    std = block_reduce(image_gray.astype(np.float32), block, np.std)
    return std > min_std


def downscale_for(image: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return image, 1.0
    f = max_side / s
    return cv2.resize(image, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA), f
