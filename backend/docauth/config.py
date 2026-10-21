"""Application settings, read from environment variables (prefix ``DOCAUTH_``) or ``.env``."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/docauth/config.py -> project root is two levels above the package
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCAUTH_",
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str | None = None

    # Auth
    secret_key: str | None = None
    token_ttl_minutes: int = 60 * 24
    cookie_name: str = "docauth_session"
    cookie_secure: bool = False
    admin_email: str | None = None
    admin_password: str | None = None
    allow_registration: bool = True

    # HTTP
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"

    # Analysis
    max_upload_mb: int = 25
    max_pdf_pages: int = 10
    analysis_workers: int = 2

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'docauth.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def analyses_dir(self) -> Path:
        return self.data_dir / "analyses"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.analyses_dir, self.templates_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_secret_key(self) -> str:
        """Return the JWT signing key.

        Production requires an explicit ``DOCAUTH_SECRET_KEY``. In development a random key is
        generated once and persisted under the data dir so sessions survive restarts.
        """
        if self.secret_key:
            return self.secret_key
        if self.is_production:
            raise RuntimeError("DOCAUTH_SECRET_KEY must be set in production")
        key_file = self.data_dir / ".secret_key"
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        key_file.write_text(key, encoding="utf-8")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
