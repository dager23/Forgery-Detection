"""ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docauth.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="user")  # "user" | "admin"
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    analyses: Mapped[list[Analysis]] = relationship(back_populates="user")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Template(Base):
    """A ground-truth reference document used for SSIM template matching."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    doc_type: Mapped[str] = mapped_column(String(80), default="generic")
    description: Mapped[str] = mapped_column(Text, default="")
    image_file: Mapped[str] = mapped_column(String(255))  # relative to templates dir
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Normalised [x, y, w, h] boxes (0..1) of fields that legitimately vary (name, photo, date...)
    ignore_regions: Mapped[list[dict[str, float]]] = mapped_column(JSON, default=list)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    auto_template: Mapped[bool] = mapped_column(default=False)

    filename: Mapped[str] = mapped_column(String(255))
    stored_file: Mapped[str] = mapped_column(String(255))  # relative to uploads dir
    mime: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # authenticity 0..100
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="analyses")
    template: Mapped[Template | None] = relationship()
