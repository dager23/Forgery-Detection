"""Forensic engine: runs every module, fuses their evidence into one verdict."""

from __future__ import annotations

import json
import logging
import math
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from docauth import __version__
from docauth.forensics.deep import runtime as deep_rt
from docauth.forensics.deep.modules import CnnClassifierModule, SegmentationModule
from docauth.forensics.modules.base import AnalysisContext, Module
from docauth.forensics.modules.copymove import CopyMoveModule
from docauth.forensics.modules.ela import ElaModule
from docauth.forensics.modules.jpeg import JpegModule
from docauth.forensics.modules.metadata import MetadataModule
from docauth.forensics.modules.noise import NoiseModule
from docauth.forensics.modules.template import TemplateModule
from docauth.forensics.types import Document, ModuleResult, TemplateRef, noisy_or

log = logging.getLogger("docauth.engine")

# Maximum share of the final suspicion a single module can contribute (noisy-OR fusion).
DEFAULT_WEIGHTS: dict[str, float] = {
    "metadata": 0.55,
    "ela": 0.5,
    "noise": 0.45,
    "jpeg": 0.55,
    "copymove": 0.7,
    "template": 0.9,
    "cnn": 0.75,
    "segmentation": 0.8,
}
# Authenticity score bands (0-100), mirroring the README's green / amber / red flags
DEFAULT_THRESHOLDS = {"authentic": 70.0, "tampered": 40.0}
DISPLAY_MAX_SIDE = 2400


def default_modules() -> list[Module]:
    return [
        MetadataModule(),
        ElaModule(),
        NoiseModule(),
        JpegModule(),
        CopyMoveModule(),
        TemplateModule(),
        CnnClassifierModule(),
        SegmentationModule(),
    ]


def load_calibration() -> dict[str, Any]:
    path = deep_rt.weights_dir() / "calibration.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Ignoring unreadable calibration file %s", path)
    return {}


@dataclass
class EngineReport:
    document: Document
    modules: list[ModuleResult]
    verdict: str
    score: float
    summary: str
    fusion: dict[str, Any]
    thresholds: dict[str, float]
    duration_ms: int
    template: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def save(self, out_dir: Path) -> dict[str, Any]:
        """Write page images + artifacts to ``out_dir`` and return the JSON-able report."""
        out_dir.mkdir(parents=True, exist_ok=True)
        pages = []
        for p in self.document.pages:
            name = f"page_{p.index}.jpg"
            cv2.imwrite(str(out_dir / name), _fit(p.image), [cv2.IMWRITE_JPEG_QUALITY, 90])
            h, w = p.shape
            pages.append(
                {
                    "index": p.index,
                    "width": w,
                    "height": h,
                    "source": p.source,
                    "format": p.fmt,
                    "image": name,
                }
            )
        names: dict[int, str] = {}
        for m in self.modules:
            for a in m.artifacts:
                if a.image.ndim == 3 and a.image.shape[2] == 4:
                    name = f"{a.key}_p{a.page}.png"
                    cv2.imwrite(
                        str(out_dir / name), _fit(a.image), [cv2.IMWRITE_PNG_COMPRESSION, 6]
                    )
                else:
                    name = f"{a.key}_p{a.page}.jpg"
                    cv2.imwrite(str(out_dir / name), _fit(a.image), [cv2.IMWRITE_JPEG_QUALITY, 88])
                names[id(a)] = name
        return self.to_dict(pages, names)

    def to_dict(self, pages=None, names=None) -> dict[str, Any]:
        d = self.document
        return {
            "engine_version": __version__,
            "verdict": self.verdict,
            "score": round(self.score, 1),
            "summary": self.summary,
            "thresholds": self.thresholds,
            "fusion": self.fusion,
            "template": self.template,
            "document": {
                "filename": d.filename,
                "mime": d.mime,
                "kind": d.kind,
                "page_count": d.page_count,
                "analysed_pages": len(d.pages),
                "notes": d.notes,
            },
            "pages": pages
            or [
                {
                    "index": p.index,
                    "width": p.shape[1],
                    "height": p.shape[0],
                    "source": p.source,
                    "format": p.fmt,
                }
                for p in d.pages
            ],
            "modules": [m.to_dict(names) for m in self.modules],
            "duration_ms": self.duration_ms,
        }


def _fit(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    s = max(h, w)
    if s <= DISPLAY_MAX_SIDE:
        return img
    f = DISPLAY_MAX_SIDE / s
    interp = cv2.INTER_AREA if img.shape[-1] != 4 else cv2.INTER_LINEAR
    return cv2.resize(img, (round(w * f), round(h * f)), interpolation=interp)


class Engine:
    def __init__(self, modules: list[Module] | None = None, calibration: dict | None = None):
        self.modules = modules if modules is not None else default_modules()
        self.calibration = calibration if calibration is not None else load_calibration()

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "key": m.key,
                "title": m.title,
                "description": m.description,
                "available": m.available(),
                "reason": "" if m.available() else m.unavailable_reason(),
            }
            for m in self.modules
        ]

    def analyze(
        self,
        doc: Document,
        template: TemplateRef | None = None,
        candidates: list[TemplateRef] | None = None,
        only: set[str] | None = None,
    ) -> EngineReport:
        t0 = time.perf_counter()
        ctx = AnalysisContext(template, candidates or [], self.calibration)
        results: list[ModuleResult] = []
        for m in self.modules:
            if only and m.key not in only:
                continue
            if not m.available():
                r = m.result()
                r.status, r.confidence, r.summary = "skipped", 0.0, m.unavailable_reason()
                results.append(r)
                continue
            t = time.perf_counter()
            try:
                r = m.run(doc, ctx)
            except Exception as e:  # noqa: BLE001 - one broken module must not sink the report
                log.error("Module %s failed: %s\n%s", m.key, e, traceback.format_exc())
                r = m.result()
                r.status, r.confidence = "error", 0.0
                r.summary = f"Module failed: {type(e).__name__}: {e}"
            r.duration_ms = int((time.perf_counter() - t) * 1000)
            results.append(r)

        fusion, score = self.fuse(results)
        thresholds = {**DEFAULT_THRESHOLDS, **self.calibration.get("thresholds", {})}
        if score >= thresholds["authentic"]:
            verdict = "authentic"
        elif score >= thresholds["tampered"]:
            verdict = "suspicious"
        else:
            verdict = "tampered"

        tpl_info = None
        tmod = next((r for r in results if r.key == "template" and r.status == "ok"), None)
        if tmod is not None and "template" in tmod.metrics:
            tpl_info = {
                "name": tmod.metrics["template"],
                "auto_selected": bool(tmod.metrics.get("auto_selected")),
            }
        return EngineReport(
            document=doc,
            modules=results,
            verdict=verdict,
            score=score,
            summary=_summary(verdict, score, results, fusion["contributions"]),
            fusion=fusion,
            thresholds=thresholds,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            template=tpl_info,
        )

    def fuse(self, results: list[ModuleResult]) -> tuple[dict[str, Any], float]:
        cal = self.calibration.get("fusion", {})
        weights = {**DEFAULT_WEIGHTS, **cal.get("weights", {})}
        contributions = {
            r.key: weights.get(r.key, 0.5) * r.confidence * r.suspicion
            for r in results
            if r.status == "ok"
        }
        if cal.get("method") == "logistic" and cal.get("coef"):
            z = float(cal.get("bias", 0.0))
            for r in results:
                if r.status == "ok" and r.key in cal["coef"]:
                    z += cal["coef"][r.key] * r.suspicion * r.confidence
            p = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))
            method = "logistic"
        else:
            p = noisy_or(list(contributions.values()))
            method = "noisy-or"
        return (
            {
                "method": method,
                "contributions": {k: round(v, 4) for k, v in contributions.items()},
                "weights": weights,
            },
            100.0 * (1.0 - p),
        )


def _summary(verdict: str, score: float, results: list[ModuleResult], contrib: dict) -> str:
    lead = {
        "authentic": "No significant signs of manipulation were found.",
        "suspicious": "Some indicators of possible manipulation need a closer look.",
        "tampered": "Strong evidence that the document has been manipulated.",
    }[verdict]
    top = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)
    reasons = []
    for key, value in top[:3]:
        if value < 0.15:
            break
        r = next(x for x in results if x.key == key)
        reasons.append(f"{r.title}: {r.summary}")
    return lead + (" " + " ".join(reasons) if reasons else "")
