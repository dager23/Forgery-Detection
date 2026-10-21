"""Health / capability endpoint (public, no secrets)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from docauth import __version__
from docauth.forensics.deep import runtime as deep_rt

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health(request: Request) -> dict:
    engine = request.app.state.runner.engine
    settings = request.app.state.settings
    return {
        "status": "ok",
        "version": __version__,
        "modules": engine.catalog(),
        "models": {
            n: deep_rt.model_info(n) for n in ("classifier", "segmenter") if deep_rt.has_model(n)
        },
        "calibrated": bool(engine.calibration),
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_pdf_pages": settings.max_pdf_pages,
        },
        "registration_open": settings.allow_registration,
    }
