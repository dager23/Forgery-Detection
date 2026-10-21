"""Shared training utilities: device, logging, checkpoints, metrics."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data"
RUNS = ROOT / "ml" / "runs"


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def amp_supported(dev: torch.device) -> bool:
    """fp16 autocast, except on GTX 16xx (TU116/TU117) whose cuDNN fp16 kernels emit NaNs."""
    if dev.type != "cuda":
        return False
    name = torch.cuda.get_device_name(dev)
    return not ("GTX 16" in name or "TU116" in name or "TU117" in name)


class Logger:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self.f = open(run_dir / "log.jsonl", "a", encoding="utf-8")  # noqa: SIM115 - lives with run
        self.t0 = time.time()

    def log(self, **kw) -> None:
        kw["t"] = round(time.time() - self.t0, 1)
        line = json.dumps(kw)
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    scores, labels = np.asarray(scores, np.float64), np.asarray(labels).astype(bool)
    pos, neg = scores[labels], scores[~labels]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, order.size + 1)
    # average ranks for ties
    allv = np.concatenate([pos, neg])
    _, inv, counts = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    ranks = (sums / counts)[inv]
    return float((ranks[: pos.size].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def best_threshold(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    """Threshold maximising balanced accuracy -> (threshold, balanced accuracy)."""
    scores, labels = np.asarray(scores), np.asarray(labels).astype(bool)
    best = (0.5, 0.0)
    for t in np.unique(np.quantile(scores, np.linspace(0.02, 0.98, 97))):
        pred = scores >= t
        tpr = (pred & labels).sum() / max(labels.sum(), 1)
        tnr = (~pred & ~labels).sum() / max((~labels).sum(), 1)
        bacc = (tpr + tnr) / 2
        if bacc > best[1]:
            best = (float(t), float(bacc))
    return best


def pixel_f1(
    prob: torch.Tensor, mask: torch.Tensor, thr: float = 0.5
) -> tuple[float, float, float]:
    """Return (tp, fp, fn) sums for micro-averaged F1."""
    pred = prob >= thr
    m = mask >= 0.5
    return (float((pred & m).sum()), float((pred & ~m).sum()), float((~pred & m).sum()))


def save_ckpt(path: Path, model: torch.nn.Module, **meta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "meta": meta}, path)
