"""Pre-generate the synthetic forged-document dataset.

    python ml/generate_synthetic.py --train 5000 --val 600

Writes data/synthetic/{train,val}/{images,masks}/ + index.csv. Half of the samples are
tampered (text replacement, copy-move, splicing, erasure, inserted text) with pixel masks.
"""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _one(args):
    seed, tampered, out = args
    from docauth import synth

    data, mask, meta = synth.make_sample(seed, tampered)
    name = f"{seed:07d}.jpg"
    (Path(out) / "images" / name).write_bytes(data)
    mname = ""
    if mask is not None:
        mname = f"{seed:07d}.png"
        cv2.imwrite(str(Path(out) / "masks" / mname), (mask * 255).astype(np.uint8))
    return {
        "file": name,
        "label": int(tampered),
        "mask": mname,
        "kind": meta.get("kind", ""),
        "doc_type": meta["doc_type"],
        "q1": meta["q1"],
        "q2": meta.get("q2", ""),
    }


def generate(out: Path, n: int, seed0: int, workers: int) -> None:
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "masks").mkdir(parents=True, exist_ok=True)
    jobs = [(seed0 + i, i % 2 == 1, str(out)) for i in range(n)]
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(_one, jobs, chunksize=16))
    with open(out / "index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"{out}: {len(rows)} samples ({sum(r['label'] for r in rows)} tampered)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synthetic")
    ap.add_argument("--train", type=int, default=5000)
    ap.add_argument("--val", type=int, default=600)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    generate(a.out / "train", a.train, 1_000_000, a.workers)
    generate(a.out / "val", a.val, 9_000_000, a.workers)


if __name__ == "__main__":
    main()
