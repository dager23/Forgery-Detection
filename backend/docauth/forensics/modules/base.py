"""Base class and shared context for forensic modules."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from docauth.forensics.types import Document, ModuleResult, TemplateRef

# Below this suspicion a module's regions are reported as weak variations, not findings
WEAK = 0.35

# Default evidence -> suspicion curves: suspicion = logistic(slope * (evidence - center)).
# ``ml/evaluate_engine.py`` refits the centres on labelled data (calibration.json); a centre of
# None means the module derives it at run time (the deep models use their own threshold).
CURVES: dict[str, tuple[float | None, float]] = {
    "ela": (2.2, 2.2),
    "noise": (2.4, 2.0),
    "jpeg": (2.3, 2.0),
    "copymove": (3.0, 3.0),
    "template": (1.0, 3.0),
    "cnn": (None, 1.0),  # deep modules: evidence is in log-odds units
    "segmentation": (None, 1.0),
}


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

    def calibrated(self, ctx: AnalysisContext, x: float, center: float | None = None) -> float:
        """Map a raw module metric to suspicion, using fitted parameters when available."""
        default_center, slope = CURVES[self.key]
        params = ctx.calibration.get("modules", {}).get(self.key, {})
        c = params.get("center", center if center is not None else default_center)
        return self.logistic(x, c, params.get("slope", slope))
