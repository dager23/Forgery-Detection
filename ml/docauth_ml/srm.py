"""The 30 SRM high-pass filters (Fridrich & Kodovsky "rich models"), as used by Rao & Ni (2016)
to initialise the first layer of a forgery-detection CNN.

1st order (8) + 2nd order (4) + 3rd order (8) + SQUARE 3x3 (1) + SQUARE 5x5 (1)
+ EDGE 3x3 (4) + EDGE 5x5 (4) = 30 kernels, each embedded in a 5x5 grid.
"""

from __future__ import annotations

import numpy as np

DIRS8 = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]
DIRS4 = [(0, 1), (1, 0), (1, 1), (1, -1)]

SQUARE3 = np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]], np.float32) / 4.0
SQUARE5 = (
    np.array(
        [
            [-1, 2, -2, 2, -1],
            [2, -6, 8, -6, 2],
            [-2, 8, -12, 8, -2],
            [2, -6, 8, -6, 2],
            [-1, 2, -2, 2, -1],
        ],
        np.float32,
    )
    / 12.0
)
EDGE3 = np.array([[-1, 2, -1], [2, -4, 2], [0, 0, 0]], np.float32) / 4.0
EDGE5 = (
    np.array(
        [
            [-1, 2, -2, 2, -1],
            [2, -6, 8, -6, 2],
            [-2, 8, -12, 8, -2],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
        ],
        np.float32,
    )
    / 12.0
)


def _embed3(k3: np.ndarray) -> np.ndarray:
    k = np.zeros((5, 5), np.float32)
    k[1:4, 1:4] = k3
    return k


def srm_kernels() -> np.ndarray:
    """Return the 30 SRM kernels as an array of shape (30, 5, 5)."""
    ks: list[np.ndarray] = []
    for dy, dx in DIRS8:  # 1st order: x(n+d) - x(n)
        k = np.zeros((5, 5), np.float32)
        k[2, 2] = -1
        k[2 + dy, 2 + dx] = 1
        ks.append(k)
    for dy, dx in DIRS4:  # 2nd order: x(n-d) - 2x(n) + x(n+d)
        k = np.zeros((5, 5), np.float32)
        k[2 - dy, 2 - dx] = 1
        k[2, 2] = -2
        k[2 + dy, 2 + dx] = 1
        ks.append(k / 2.0)
    for dy, dx in DIRS8:  # 3rd order: x(n-d) - 3x(n) + 3x(n+d) - x(n+2d)
        k = np.zeros((5, 5), np.float32)
        k[2 - dy, 2 - dx] = 1
        k[2, 2] = -3
        k[2 + dy, 2 + dx] = 3
        k[2 + 2 * dy, 2 + 2 * dx] = -1
        ks.append(k / 3.0)
    ks.append(_embed3(SQUARE3))
    ks.append(SQUARE5.copy())
    for r in range(4):
        ks.append(_embed3(np.rot90(EDGE3, r)))
    for r in range(4):
        ks.append(np.rot90(EDGE5, r).astype(np.float32))
    out = np.stack(ks)
    assert out.shape == (30, 5, 5)
    return out
