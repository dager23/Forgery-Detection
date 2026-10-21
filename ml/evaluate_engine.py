"""Evaluate the full forensic engine on labelled data and (optionally) calibrate it.

    python ml/evaluate_engine.py --sources synthetic,casia2,doctamper --n 400 --calibrate

* Runs the real Engine (classical modules + installed ONNX models) on the validation split.
* Reports per-module ROC-AUC, the fused AUC/accuracy and the verdict confusion matrix.
* ``--calibrate`` splits the samples in half: the first half fits
    - each module's operating point (suspicion 0.5 at ~5% false positives on genuine files),
    - a logistic-regression fusion over module outputs,
    - verdict thresholds from the genuine-score distribution,
  the second half is used for the reported numbers. Results go to
  backend/docauth/forensics/deep/weights/calibration.json and docs/EVALUATION.md.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT / "backend"))

from docauth_ml.data import build_sources  # noqa: E402
from docauth_ml.train_common import DATA_ROOT, roc_auc  # noqa: E402

from docauth.forensics.modules.base import CURVES  # noqa: E402

WEIGHTS = ROOT / "backend" / "docauth" / "forensics" / "deep" / "weights"
TARGET_FPR = 0.05

_engine = None


def _init(calibration_off: bool):
    global _engine
    from docauth.forensics import Engine

    _engine = Engine(calibration={} if calibration_off else None)


def _run(task):
    src_name, item_id, label, jpeg = task
    from docauth.forensics import load_document

    doc = load_document(jpeg, f"{item_id}.jpg")
    rep = _engine.analyze(doc)
    mods = {}
    for m in rep.modules:
        mods[m.key] = {
            "status": m.status,
            "suspicion": m.suspicion,
            "confidence": m.confidence,
            "evidence": float(m.metrics.get("evidence", 0.0) or 0.0),
        }
    return {
        "source": src_name,
        "id": item_id,
        "label": label,
        "score": rep.score,
        "verdict": rep.verdict,
        "modules": mods,
    }


def collect(names: list[str], n: int, seed: int) -> list[tuple]:
    """Balanced samples from each source's validation split, encoded as JPEG bytes."""
    rng = random.Random(seed)
    tasks = []
    for src in build_sources(names, "val", DATA_ROOT):
        idx = list(range(len(src)))
        rng.shuffle(idx)
        pos, neg = [], []
        for i in idx:
            if len(pos) >= n // 2 and len(neg) >= n // 2:
                break
            item = src.get(i)
            if item is None:
                continue
            bucket = pos if item.label else neg
            if len(bucket) >= n // 2:
                continue
            # keep the original encoding when the source stores JPEG files
            path = None
            if src.name == "synthetic":
                path = src.root / "images" / src.entries[i][0]
            elif src.name == "casia2":
                path = src.entries[i][0]
            if path is not None and str(path).lower().endswith((".jpg", ".jpeg")):
                data = Path(path).read_bytes()
            else:
                data = cv2.imencode(".png", item.image)[1].tobytes()
            bucket.append((src.name, item.id, item.label, data))
        if src.name == "doctamper" and not neg:
            print("[eval] DocTamper has no genuine images; other sources supply negatives")
        tasks += pos + neg
        print(f"[eval] {src.name}: {len(pos)} tampered + {len(neg)} genuine")
    rng.shuffle(tasks)
    return tasks


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 100):
    """Newton-Raphson logistic regression with an L2 penalty (bias unpenalised)."""
    Xb = np.hstack([X, np.ones((len(X), 1))])
    w = np.zeros(Xb.shape[1])
    reg = np.full(Xb.shape[1], l2)
    reg[-1] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(Xb @ w, -30, 30)))
        g = Xb.T @ (p - y) + reg * w
        H = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(reg) + 1e-6 * np.eye(len(w))
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w[:-1], float(w[-1])


def module_keys(rows) -> list[str]:
    keys = set()
    for r in rows:
        keys |= {k for k, v in r["modules"].items() if v["status"] == "ok"}
    return sorted(keys)


def features(rows, keys) -> np.ndarray:
    return np.array(
        [
            [
                r["modules"].get(k, {}).get("suspicion", 0)
                * r["modules"].get(k, {}).get("confidence", 0)
                if r["modules"].get(k, {}).get("status") == "ok"
                else 0.0
                for k in keys
            ]
            for r in rows
        ]
    )


def calibrate(rows) -> dict:
    keys = module_keys(rows)
    genuine = [r for r in rows if r["label"] == 0]
    modules = {}
    for k in keys:
        ev = [
            r["modules"][k]["evidence"]
            for r in genuine
            if r["modules"].get(k, {}).get("status") == "ok"
        ]
        if len(ev) >= 20 and k in CURVES:
            center = float(np.quantile(ev, 1 - TARGET_FPR))
            if center > 0:
                modules[k] = {"center": round(center, 4)}
    return {"modules": modules, "_keys": keys}


def fit_fusion(rows, keys) -> dict:
    X = features(rows, keys)
    y = np.array([r["label"] for r in rows], float)
    coef, bias = fit_logistic(X, y, l2=0.5)
    # verdict thresholds from genuine scores under the fitted fusion
    z = X @ coef + bias
    scores = 100 * (1 - 1 / (1 + np.exp(-z)))
    g = scores[y == 0]
    authentic = float(np.clip(np.quantile(g, 0.10), 55, 85)) if len(g) else 70.0
    tampered = float(np.clip(np.quantile(g, 0.01), 20, min(50, authentic - 10))) if len(g) else 40.0
    return {
        "fusion": {
            "method": "logistic",
            "coef": {k: round(float(c), 4) for k, c in zip(keys, coef, strict=True)},
            "bias": round(bias, 4),
        },
        "thresholds": {"authentic": round(authentic, 1), "tampered": round(tampered, 1)},
    }


def apply_fusion(rows, keys, cal) -> None:
    coef = np.array([cal["fusion"]["coef"].get(k, 0.0) for k in keys])
    X = features(rows, keys)
    z = X @ coef + cal["fusion"]["bias"]
    for r, zi in zip(rows, z, strict=True):
        r["score"] = 100 * (1 - 1 / (1 + math.exp(-max(-30, min(30, zi)))))
        t = cal["thresholds"]
        r["verdict"] = (
            "authentic"
            if r["score"] >= t["authentic"]
            else ("suspicious" if r["score"] >= t["tampered"] else "tampered")
        )


def report(rows, title: str) -> str:
    keys = module_keys(rows)
    y = np.array([r["label"] for r in rows])
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    lines = [f"### {title}", "", f"{len(rows)} samples ({n_pos} tampered, {n_neg} genuine)", ""]
    lines += ["| Module | ROC-AUC | Flag rate genuine | Flag rate tampered |", "|---|---|---|---|"]
    for k in keys:
        s = np.array([r["modules"].get(k, {}).get("suspicion", 0) for r in rows])
        auc = roc_auc(s, y)
        fp, tp = np.mean(s[y == 0] > 0.5), np.mean(s[y == 1] > 0.5)
        lines.append(f"| {k} | {auc:.3f} | {fp:.1%} | {tp:.1%} |")
    fused = np.array([100 - r["score"] for r in rows])
    v = np.array([r["verdict"] for r in rows])
    lines += ["", f"**Fused ROC-AUC: {roc_auc(fused, y):.3f}**", ""]
    lines += ["| Truth \\ Verdict | Accepted | Suspicious | Rejected |", "|---|---|---|---|"]
    for lab, name in ((0, "Genuine"), (1, "Tampered")):
        sel = y == lab
        n = max(int(sel.sum()), 1)
        acc, sus, rej = (np.sum(v[sel] == x) / n for x in ("authentic", "suspicious", "tampered"))
        lines.append(f"| {name} | {acc:.1%} | {sus:.1%} | {rej:.1%} |")
    by_src = {}
    for r in rows:
        by_src.setdefault(r["source"], []).append(r)
    if len(by_src) > 1:
        lines += ["", "| Source | n | Fused ROC-AUC |", "|---|---|---|"]
        for s, rs in by_src.items():
            yy = np.array([r["label"] for r in rs])
            auc = roc_auc(np.array([100 - r["score"] for r in rs]), yy)
            lines.append(f"| {s} | {len(rs)} | {auc:.3f} |")
    return "\n".join(lines) + "\n"


def run_engine(tasks, workers, calibration_off) -> list[dict]:
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(calibration_off,)) as ex:
        out = []
        for i, r in enumerate(ex.map(_run, tasks, chunksize=2), 1):
            out.append(r)
            if i % 25 == 0:
                print(f"[eval] {i}/{len(tasks)}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="synthetic,casia2,doctamper")
    ap.add_argument("--n", type=int, default=300, help="samples per source")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    tasks = collect([s.strip() for s in a.sources.split(",") if s.strip()], a.n, a.seed)
    if not tasks:
        raise SystemExit("No labelled samples found.")
    rows = run_engine(tasks, a.workers, calibration_off=a.calibrate)
    out_md = [f"# DocAuth evaluation\n\nGenerated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}.\n"]

    if a.calibrate:
        half = len(rows) // 2
        fit_rows, test_rows = rows[:half], rows[half:]
        out_md.append(report(test_rows, "Before calibration (default weights, held-out half)"))
        cal = calibrate(fit_rows)
        keys = cal.pop("_keys")
        # re-derive module suspicions with the new operating points before fitting fusion
        for r in rows:
            for k, p in cal["modules"].items():
                m = r["modules"].get(k)
                if m and m["status"] == "ok":
                    z = max(-60.0, min(60.0, CURVES[k][1] * (m["evidence"] - p["center"])))
                    m["suspicion"] = 1 / (1 + math.exp(-z))
        fus = fit_fusion(fit_rows, keys)
        cal.update(fus)
        apply_fusion(test_rows, keys, cal)
        out_md.append(report(test_rows, "After calibration (held-out half)"))
        cal["fitted_on"] = {
            "samples": len(fit_rows),
            "sources": sorted({r["source"] for r in fit_rows}),
            "target_module_fpr": TARGET_FPR,
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        (WEIGHTS / "calibration.json").write_text(json.dumps(cal, indent=2), encoding="utf-8")
        print(json.dumps(cal, indent=2))
    else:
        out_md.append(report(rows, "Current engine"))

    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "EVALUATION.md").write_text("\n".join(out_md), encoding="utf-8")
    (ROOT / "ml" / "runs").mkdir(parents=True, exist_ok=True)
    (ROOT / "ml" / "runs" / "evaluation.json").write_text(json.dumps(rows), encoding="utf-8")
    print("\n".join(out_md))


if __name__ == "__main__":
    main()
