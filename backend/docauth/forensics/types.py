"""Core data types shared by every forensic module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np

Severity = Literal["info", "low", "medium", "high"]
ArtifactKind = Literal["heatmap", "overlay", "image"]
ModuleStatus = Literal["ok", "skipped", "error"]

# How much a single finding of each severity contributes to a module's suspicion (noisy-OR)
SEVERITY_WEIGHT: dict[str, float] = {"info": 0.0, "low": 0.2, "medium": 0.5, "high": 0.85}


@dataclass
class Page:
    """One raster page to analyse (an image file is a single page; PDFs have several)."""

    index: int
    image: np.ndarray  # BGR uint8, H x W x 3
    source: str = "raster"  # raster | pdf-embedded | pdf-render
    encoded: bytes | None = None  # original compressed bytes when available
    fmt: str | None = None  # jpeg | png | tiff | bmp | webp
    resampled: bool = False  # True when we had to downscale (weakens compression evidence)
    scale: float = 1.0  # analysed size / original size

    @property
    def is_jpeg(self) -> bool:
        return self.fmt == "jpeg"

    @property
    def shape(self) -> tuple[int, int]:
        return self.image.shape[0], self.image.shape[1]


@dataclass
class Document:
    filename: str
    mime: str
    kind: Literal["image", "pdf"]
    data: bytes
    pages: list[Page]
    page_count: int  # total pages in the file (may exceed len(pages) when truncated)
    notes: list[str] = field(default_factory=list)


@dataclass
class TemplateRef:
    """A ground-truth reference document for template matching."""

    id: int | None
    name: str
    image: np.ndarray  # BGR uint8
    ignore_regions: list[dict[str, float]] = field(default_factory=list)  # normalised boxes


@dataclass
class Finding:
    severity: Severity
    message: str
    page: int | None = None


@dataclass
class Box:
    """A region of interest in page pixel coordinates."""

    page: int
    x: int
    y: int
    w: int
    h: int
    label: str
    score: float = 1.0


@dataclass
class Artifact:
    key: str
    label: str
    page: int
    image: np.ndarray  # BGR / BGRA uint8
    kind: ArtifactKind = "heatmap"

    @property
    def filename(self) -> str:
        return f"{self.key}_p{self.page}.png"


@dataclass
class ModuleResult:
    key: str
    title: str
    status: ModuleStatus = "ok"
    suspicion: float = 0.0  # 0 = clean, 1 = certainly manipulated
    confidence: float = 1.0  # how applicable/reliable the module was on this input
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    @property
    def score10(self) -> float:
        """Authenticity on the README's 0-10 scale (10 = clean)."""
        return round(10.0 * (1.0 - self.suspicion), 1)

    def to_dict(self, artifact_names: dict[int, str] | None = None) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "suspicion": round(float(self.suspicion), 4),
            "confidence": round(float(self.confidence), 4),
            "score10": self.score10,
            "summary": self.summary,
            "findings": [asdict(f) for f in self.findings],
            "boxes": [asdict(b) for b in self.boxes],
            "artifacts": [
                {
                    "key": a.key,
                    "label": a.label,
                    "page": a.page,
                    "kind": a.kind,
                    "file": (artifact_names or {}).get(id(a), a.filename),
                }
                for a in self.artifacts
            ],
            "metrics": _jsonable(self.metrics),
            "duration_ms": self.duration_ms,
        }


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, float):
        return round(v, 5)
    return v


def noisy_or(values: list[float]) -> float:
    p = 1.0
    for v in values:
        p *= 1.0 - max(0.0, min(1.0, v))
    return 1.0 - p


def suspicion_from_findings(findings: list[Finding]) -> float:
    return noisy_or([SEVERITY_WEIGHT[f.severity] for f in findings])
