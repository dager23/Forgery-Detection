"""Background execution of analyses (thread pool; status persisted in the database)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select

from docauth.config import Settings
from docauth.db import Database
from docauth.forensics import Engine, TemplateRef, UnsupportedFile, load_document
from docauth.models import Analysis, Template
from docauth.services.storage import analysis_dir

log = logging.getLogger("docauth.jobs")


class TemplateCache:
    """Decoded template images keyed by (id, file mtime)."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, float], np.ndarray] = {}
        self._lock = threading.Lock()

    def ref(self, settings: Settings, t: Template) -> TemplateRef | None:
        path: Path = settings.templates_dir / t.image_file
        if not path.exists():
            return None
        key = (t.id, path.stat().st_mtime)
        with self._lock:
            img = self._cache.get(key)
        if img is None:
            img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return None
            with self._lock:
                self._cache = {k: v for k, v in self._cache.items() if k[0] != t.id}
                self._cache[key] = img
        return TemplateRef(t.id, t.name, img, list(t.ignore_regions or []))


class AnalysisRunner:
    def __init__(self, db: Database, settings: Settings, engine: Engine | None = None):
        self.db = db
        self.settings = settings
        self.engine = engine or Engine()
        self.templates = TemplateCache()
        self.pool = ThreadPoolExecutor(
            max_workers=max(1, settings.analysis_workers), thread_name_prefix="analysis"
        )

    def submit(self, analysis_id: str):
        return self.pool.submit(self._run, analysis_id)

    def resume_pending(self) -> None:
        """Re-queue work interrupted by a restart."""
        with self.db.session() as s:
            ids = s.scalars(
                select(Analysis.id).where(Analysis.status.in_(("queued", "running")))
            ).all()
            for a in s.scalars(select(Analysis).where(Analysis.id.in_(ids))):
                a.status = "queued"
            s.commit()
        for i in ids:
            self.submit(i)
        if ids:
            log.info("Resumed %d pending analyses", len(ids))

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, analysis_id: str) -> None:
        with self.db.session() as s:
            a = s.get(Analysis, analysis_id)
            if a is None or a.status not in ("queued", "running"):
                return
            a.status = "running"
            s.commit()
            stored, filename = a.stored_file, a.filename
            template = candidates = None
            if a.template_id is not None:
                t = s.get(Template, a.template_id)
                template = self.templates.ref(self.settings, t) if t else None
            elif a.auto_template:
                candidates = [
                    r
                    for t in s.scalars(select(Template)).all()
                    if (r := self.templates.ref(self.settings, t)) is not None
                ]
        try:
            data = (self.settings.uploads_dir / stored).read_bytes()
            doc = load_document(data, filename, self.settings.max_pdf_pages)
            report = self.engine.analyze(doc, template, candidates)
            result = report.save(analysis_dir(self.settings, analysis_id))
            self._finish(
                analysis_id,
                "done",
                result=result,
                verdict=report.verdict,
                score=report.score,
                page_count=doc.page_count,
                duration_ms=report.duration_ms,
            )
        except UnsupportedFile as e:
            self._finish(analysis_id, "failed", error=str(e))
        except Exception as e:  # noqa: BLE001 - surface as a failed job, keep the worker alive
            log.exception("Analysis %s crashed", analysis_id)
            self._finish(analysis_id, "failed", error=f"Internal error: {type(e).__name__}")

    def _finish(self, analysis_id: str, status: str, **fields) -> None:
        with self.db.session() as s:
            a = s.get(Analysis, analysis_id)
            if a is None:  # deleted while running
                return
            a.status = status
            a.completed_at = datetime.now(UTC)
            for k, v in fields.items():
                setattr(a, k, v)
            s.commit()
