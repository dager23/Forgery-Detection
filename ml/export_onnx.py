"""Export trained checkpoints to the ONNX files the backend serves.

    python ml/export_onnx.py segmenter --ckpt ml/runs/segmenter/best.pt
    python ml/export_onnx.py classifier --ckpt ml/runs/classifier/best.pt

Writes backend/docauth/forensics/deep/weights/{name}.onnx plus a {name}.json sidecar (operating
threshold, validation metrics, training sources) and verifies ONNX Runtime against PyTorch.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):  # Windows consoles choke on the exporter's emoji
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from docauth_ml.models import SRMPatchNet, TwoStreamSegNet  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "backend" / "docauth" / "forensics" / "deep" / "weights"


def _export(model, example, path: Path, in_name: str, out_name: str, dyn: dict) -> None:
    try:
        torch.onnx.export(
            model,
            (example,),
            str(path),
            input_names=[in_name],
            output_names=[out_name],
            opset_version=18,
            dynamo=True,
            external_data=False,
            dynamic_shapes={"x01" if in_name == "image" else "x": dyn},
        )
    except Exception as e:  # noqa: BLE001 - fall back to the TorchScript exporter
        print(f"[export] dynamo exporter failed ({type(e).__name__}: {e}); using legacy exporter")
        axes = {in_name: {k: f"d{k}" for k in dyn}, out_name: {k: f"d{k}" for k in dyn}}
        torch.onnx.export(
            model,
            (example,),
            str(path),
            input_names=[in_name],
            output_names=[out_name],
            opset_version=17,
            dynamo=False,
            dynamic_axes=axes,
            do_constant_folding=True,
        )


def verify(path: Path, model, example: torch.Tensor, in_name: str) -> float:
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    ours = sess.run(None, {in_name: example.numpy()})[0]
    with torch.no_grad():
        ref = model(example).numpy()
    return float(np.abs(ours - ref).max())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["segmenter", "classifier"])
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=WEIGHTS)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--version", default=None)
    a = ap.parse_args()

    ck = torch.load(a.ckpt, map_location="cpu")
    meta = ck.get("meta", {})
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{a.kind}.onnx"
    from torch.export import Dim

    if a.kind == "segmenter":
        model = TwoStreamSegNet(pretrained=False)
        model.load_state_dict(ck["state_dict"])
        model.eval()
        ex = torch.rand(1, 3, 512, 512)
        h, w = Dim("h", min=1, max=128), Dim("w", min=1, max=128)
        _export(model, ex, path, "image", "mask", {2: 32 * h, 3: 32 * w})
        test = torch.rand(1, 3, 384, 640)
        thr = a.threshold if a.threshold is not None else 0.5
        in_name = "image"
    else:
        model = SRMPatchNet()
        model.load_state_dict(ck["state_dict"])
        model.eval()
        ex = torch.rand(4, 3, 128, 128)
        _export(model, ex, path, "patches", "logits", {0: Dim("n", min=1, max=4096)})
        test = torch.rand(7, 3, 128, 128)
        thr = (
            a.threshold
            if a.threshold is not None
            else float(meta.get("metrics", {}).get("thr", 0.5))
        )
        in_name = "patches"

    err = verify(path, model, test, in_name)
    print(f"[export] {path} ({path.stat().st_size / 1e6:.1f} MB), max |onnx - torch| = {err:.2e}")
    if err > 1e-2:
        raise SystemExit("ONNX output deviates from PyTorch - refusing to install this model")
    metrics = {
        k: (round(v, 4) if isinstance(v, float) else v) for k, v in meta.get("metrics", {}).items()
    }
    info = {
        "name": a.kind,
        "version": a.version or datetime.now(UTC).strftime("%Y%m%d-%H%M"),
        "threshold": round(float(thr), 4),
        "confidence": 0.75,
        "trained_on": meta.get("sources", []),
        "epoch": meta.get("epoch"),
        "val_metrics": metrics,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (a.out / f"{a.kind}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
