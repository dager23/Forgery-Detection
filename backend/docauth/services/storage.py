"""File storage helpers for uploads, analysis artifacts and templates."""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from pathlib import Path

from docauth.config import Settings

EXT_FOR_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
ARTIFACT_NAME = re.compile(r"^[a-z0-9_]{1,64}\.(png|jpg)$")


def safe_display_name(name: str | None) -> str:
    """Strip any path components / control chars from a client-supplied filename."""
    name = (name or "upload").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "upload"
    return name[:200]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_upload(settings: Settings, data: bytes, mime: str) -> str:
    """Persist an upload under a random name; returns the name relative to uploads_dir."""
    name = f"{uuid.uuid4().hex}{EXT_FOR_MIME.get(mime, '.bin')}"
    path = settings.uploads_dir / name
    path.write_bytes(data)
    return name


def analysis_dir(settings: Settings, analysis_id: str) -> Path:
    return settings.analyses_dir / analysis_id


def artifact_path(settings: Settings, analysis_id: str, name: str) -> Path | None:
    if not ARTIFACT_NAME.match(name):
        return None
    p = analysis_dir(settings, analysis_id) / name
    return p if p.is_file() else None


def delete_analysis_files(settings: Settings, analysis_id: str, stored_file: str | None) -> None:
    shutil.rmtree(analysis_dir(settings, analysis_id), ignore_errors=True)
    if stored_file:
        (settings.uploads_dir / stored_file).unlink(missing_ok=True)
