"""Train the SRM-initialised patch classifier (README module 2).

python ml/train_classifier.py --sources synthetic,casia2,doctamper --epochs 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docauth_ml.data import PatchDataset, build_sources  # noqa: E402
from docauth_ml.models import SRMPatchNet  # noqa: E402
from docauth_ml.train_common import (  # noqa: E402
    DATA_ROOT,
    RUNS,
    Logger,
    best_threshold,
    device,
    roc_auc,
    save_ckpt,
    seed_everything,
)


@torch.no_grad()
def evaluate(model, loader, dev) -> dict:
    model.eval()
    probs, labels = [], []
    for x, y in loader:
        logits = model(x.to(dev)).float()
        probs += torch.softmax(logits, 1)[:, 1].cpu().tolist()
        labels += y.tolist()
    p, y = np.array(probs), np.array(labels)
    thr, bacc = best_threshold(p, y)
    return {
        "auc": roc_auc(p, y),
        "acc@0.5": float(((p >= 0.5) == y).mean()),
        "bacc": bacc,
        "thr": thr,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="synthetic,casia2,doctamper")
    ap.add_argument("--weights", default="")
    ap.add_argument("--batch", type=int, default=96)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-n", type=int, default=4000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--doctamper-limit", type=int, default=30000)
    ap.add_argument("--init", type=Path, default=None)
    ap.add_argument("--run", default="classifier")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    seed_everything(a.seed)
    dev = device()
    names = [s.strip() for s in a.sources.split(",") if s.strip()]
    train_src = build_sources(names, "train", DATA_ROOT, a.doctamper_limit)
    val_src = build_sources(names, "val", DATA_ROOT, a.doctamper_limit)
    if not train_src:
        raise SystemExit("No training sources found on disk.")
    weights = [float(w) for w in a.weights.split(",")] if a.weights else None
    used = [s.name for s in train_src]
    run_dir = RUNS / a.run
    log = Logger(run_dir)
    log.log(event="start", sources=used, sizes=[len(s) for s in train_src], device=str(dev))

    tl = DataLoader(
        PatchDataset(train_src, length=a.iters * a.batch, weights=weights),
        a.batch,
        num_workers=a.workers,
        pin_memory=True,
        persistent_workers=a.workers > 0,
        drop_last=True,
    )
    vl = DataLoader(
        PatchDataset(val_src, length=a.val_n, weights=weights, train=False, seed=1),
        256,
        num_workers=a.workers,
        persistent_workers=a.workers > 0,
    )

    model = SRMPatchNet().to(dev)
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location=dev)["state_dict"])
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=5e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=a.lr, total_steps=a.epochs * a.iters, pct_start=0.1
    )
    best = -1.0
    step = 0
    for epoch in range(a.epochs):
        model.train()
        run_loss, n = 0.0, 0
        for x, y in tl:
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            loss = F.cross_entropy(model(x), y, label_smoothing=0.05)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            step += 1
            run_loss += loss.item()
            n += 1
            if step % 100 == 0:
                log.log(event="train", epoch=epoch, step=step, loss=round(run_loss / n, 4))
                run_loss, n = 0.0, 0
        metrics = evaluate(model, vl, dev)
        log.log(event="val", epoch=epoch, **{k: round(v, 4) for k, v in metrics.items()})
        save_ckpt(run_dir / "last.pt", model, epoch=epoch, metrics=metrics, sources=used)
        if metrics["auc"] > best:
            best = metrics["auc"]
            save_ckpt(run_dir / "best.pt", model, epoch=epoch, metrics=metrics, sources=used)
            log.log(event="best", epoch=epoch, auc=round(best, 4))
    log.log(event="done", best_auc=round(best, 4))


if __name__ == "__main__":
    main()
