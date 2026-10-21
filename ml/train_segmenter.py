"""Train the two-stream RGB + DCT manipulation segmenter (README module 3).

    python ml/train_segmenter.py --sources synthetic,casia2,doctamper --epochs 12

Any listed source that isn't on disk is skipped. Use ``--init`` to fine-tune a checkpoint.
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

from docauth_ml.data import SegDataset, build_sources  # noqa: E402
from docauth_ml.models import TwoStreamSegNet  # noqa: E402
from docauth_ml.train_common import (  # noqa: E402
    DATA_ROOT,
    RUNS,
    Logger,
    amp_supported,
    best_threshold,
    device,
    pixel_f1,
    roc_auc,
    save_ckpt,
    seed_everything,
)


def dice_loss(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    p = torch.sigmoid(logits)
    inter = (p * target).sum((1, 2, 3))
    den = p.sum((1, 2, 3)) + target.sum((1, 2, 3))
    has = (target.sum((1, 2, 3)) > 0).float()
    d = 1 - (2 * inter + 1) / (den + 1)
    # dice only for crops that contain tampering; empty crops are handled by BCE
    return (d * has).sum() / has.sum().clamp(min=1)


@torch.no_grad()
def evaluate(model, loader, dev, amp: bool) -> dict:
    model.eval()
    tp = fp = fn = 0.0
    scores, labels = [], []
    for x, m in loader:
        x, m = x.to(dev), m.to(dev)
        with torch.autocast("cuda", dtype=torch.float16, enabled=amp):
            prob = torch.sigmoid(model(x).float())
        a, b, c = pixel_f1(prob, m)
        tp, fp, fn = tp + a, fp + b, fn + c
        flat = prob.flatten(1)
        k = max(1, flat.shape[1] // 1000)
        scores += flat.topk(k, dim=1).values.mean(1).cpu().tolist()
        labels += (m.flatten(1).amax(1) > 0).int().cpu().tolist()
    f1 = 2 * tp / max(2 * tp + fp + fn, 1)
    thr, bacc = best_threshold(np.array(scores), np.array(labels))
    return {
        "pixel_f1": f1,
        "img_auc": roc_auc(np.array(scores), np.array(labels)),
        "img_bacc": bacc,
        "img_thr": thr,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="synthetic,casia2,doctamper")
    ap.add_argument("--weights", default="", help="sampling weight per source, e.g. 1,1,2")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--iters", type=int, default=800, help="iterations per epoch")
    ap.add_argument("--lr", type=float, default=4e-4)
    ap.add_argument("--val-n", type=int, default=480)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--doctamper-limit", type=int, default=30000)
    ap.add_argument("--init", type=Path, default=None)
    ap.add_argument("--run", default="segmenter")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-amp", action="store_true", help="force fp32")
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
    log.log(
        event="start",
        used_sources=used,
        sizes=[len(s) for s in train_src],
        device=str(dev),
        args={k: str(v) for k, v in vars(a).items()},
    )

    train_ds = SegDataset(train_src, a.size, a.iters * a.batch, weights, train=True)
    val_ds = SegDataset(val_src, a.size, a.val_n, weights, train=False, seed=1)
    tl = DataLoader(
        train_ds,
        a.batch,
        num_workers=a.workers,
        pin_memory=True,
        persistent_workers=a.workers > 0,
        drop_last=True,
    )
    vl = DataLoader(val_ds, a.batch, num_workers=a.workers, persistent_workers=a.workers > 0)

    model = TwoStreamSegNet(pretrained=a.init is None).to(dev)
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location=dev)["state_dict"])
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=a.lr, total_steps=a.epochs * a.iters, pct_start=0.08
    )
    amp = amp_supported(dev) and not a.no_amp
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    log.log(event="precision", amp=amp)
    pos_weight = torch.tensor([2.0], device=dev)
    best = -1.0
    step = 0
    for epoch in range(a.epochs):
        model.train()
        run_loss = 0.0
        for x, m in tl:
            x, m = x.to(dev, non_blocking=True), m.to(dev, non_blocking=True)
            with torch.autocast("cuda", dtype=torch.float16, enabled=amp):
                logits = model(x)
            logits = logits.float()
            loss = F.binary_cross_entropy_with_logits(logits, m, pos_weight=pos_weight)
            loss = loss + dice_loss(logits, m)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            run_loss += loss.item()
            if step % 100 == 0:
                log.log(
                    event="train",
                    epoch=epoch,
                    step=step,
                    loss=round(run_loss / 100, 4),
                    lr=round(sched.get_last_lr()[0], 6),
                )
                run_loss = 0.0
        metrics = evaluate(model, vl, dev, amp)
        log.log(event="val", epoch=epoch, **{k: round(v, 4) for k, v in metrics.items()})
        score = metrics["pixel_f1"] + 0.5 * metrics["img_auc"]
        save_ckpt(run_dir / "last.pt", model, epoch=epoch, metrics=metrics, sources=used)
        if score > best:
            best = score
            save_ckpt(run_dir / "best.pt", model, epoch=epoch, metrics=metrics, sources=used)
            log.log(event="best", epoch=epoch, score=round(score, 4))
    log.log(event="done", best=round(best, 4))


if __name__ == "__main__":
    main()
