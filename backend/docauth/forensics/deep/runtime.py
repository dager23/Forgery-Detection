"""Lazy, thread-safe ONNX Runtime sessions."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

from docauth.forensics.deep import WEIGHTS_DIR

_lock = threading.Lock()
_sessions: dict[Path, Any] = {}


def weights_dir() -> Path:
    override = os.environ.get("DOCAUTH_WEIGHTS_DIR")
    return Path(override) if override else WEIGHTS_DIR


def model_path(name: str) -> Path:
    return weights_dir() / f"{name}.onnx"


def model_info(name: str) -> dict[str, Any]:
    meta = weights_dir() / f"{name}.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def has_model(name: str) -> bool:
    return model_path(name).exists()


def session(name: str):
    path = model_path(name)
    with _lock:
        s = _sessions.get(path)
        if s is None:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
            providers = [
                p
                for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                if p in ort.get_available_providers()
            ]
            s = ort.InferenceSession(str(path), opts, providers=providers)
            _sessions[path] = s
        return s


def clear_cache() -> None:
    with _lock:
        _sessions.clear()


def to_rgb01(bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 HxWx3 -> RGB float32 3xHxW in [0, 1]."""
    return np.ascontiguousarray(bgr[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32) / 255.0
