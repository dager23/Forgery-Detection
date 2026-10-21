"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

from docauth import __version__
from docauth.api import admin, analyses, auth, health, templates
from docauth.config import Settings, get_settings
from docauth.db import Database
from docauth.models import User
from docauth.security import LoginThrottle, hash_password
from docauth.services.jobs import AnalysisRunner

log = logging.getLogger("docauth")


def _bootstrap_admin(db: Database, settings: Settings) -> None:
    """Create the admin from DOCAUTH_ADMIN_EMAIL/PASSWORD if no admin exists yet."""
    if not (settings.admin_email and settings.admin_password):
        return
    with db.session() as s:
        if s.scalar(select(User).where(User.role == "admin")):
            return
        email = settings.admin_email.lower()
        user = s.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                name="Administrator",
                email=email,
                password_hash=hash_password(settings.admin_password),
            )
            s.add(user)
        user.role = "admin"
        s.commit()
        log.info("Bootstrapped admin account %s", email)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_url)
        db.create_all()
        _bootstrap_admin(db, settings)
        app.state.db = db
        app.state.runner = AnalysisRunner(db, settings)
        app.state.runner.resume_pending()
        try:
            yield
        finally:
            app.state.runner.shutdown()
            db.engine.dispose()

    app = FastAPI(
        title="DocAuth API",
        version=__version__,
        description="Multi-feature document and image forgery detection.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.secret_key = settings.resolved_secret_key()
    app.state.login_throttle = LoginThrottle()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    for r in (health.router, auth.router, analyses.router, templates.router, admin.router):
        app.include_router(r)

    _mount_frontend(app, settings.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA (if present) so production runs as a single process."""
    index = dist / "index.html"
    if not index.exists():
        return
    dist_root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist_root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist_root):
            return FileResponse(candidate)
        return FileResponse(index)
