"""Base class and shared context for forensic modules."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from docauth.forensics.types import Document, ModuleResult, TemplateRef


@dataclass
class AnalysisContext:
    template: TemplateRef | None = None
    # Candidate templates for auto-detection when no template was chosen
    candidate_templates: list[TemplateRef] = field(default_factory=list)
    calibration: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


class Module:
    key: str = ""
    title: str = ""
    description: str = ""

    def available(self) -> bool:
        """False when a dependency (e.g. model weights) is missing."""
        return True

    def unavailable_reason(self) -> str:
        return ""

    def result(self) -> ModuleResult:
        return ModuleResult(self.key, self.title)

    def run(self, doc: Document, ctx: AnalysisContext) -> ModuleResult:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def logistic(x: float, center: float, slope: float) -> float:
        z = max(-60.0, min(60.0, slope * (x - center)))
        return 1.0 / (1.0 + math.exp(-z))

    def calibrated(self, ctx: AnalysisContext, x: float, center: float, slope: float) -> float:
        """Map a raw module metric to suspicion, using fitted parameters when available."""
        params = ctx.calibration.get("modules", {}).get(self.key, {})
        return self.logistic(x, params.get("center", center), params.get("slope", slope))
