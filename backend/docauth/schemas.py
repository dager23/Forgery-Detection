"""Pydantic request / response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from docauth.security import MAX_PASSWORD_BYTES

Verdict = Literal["authentic", "suspicious", "tampered"]
Status = Literal["queued", "running", "done", "failed"]


def _check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    if v.isdigit() or v.isalpha():
        raise ValueError("Password must mix letters with numbers or symbols")
    return v


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check_password(v)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class AuthOut(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"


class UserUpdateIn(BaseModel):
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None


class Region(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)
    label: str | None = Field(default=None, max_length=60)


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    doc_type: str
    description: str
    width: int
    height: int
    ignore_regions: list[dict[str, Any]]
    created_at: datetime


class TemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    doc_type: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    ignore_regions: list[Region] | None = None


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    mime: str
    size_bytes: int
    status: Status
    verdict: Verdict | None
    score: float | None
    page_count: int | None
    template_id: int | None
    created_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    user_id: int


class AnalysisOut(AnalysisSummary):
    sha256: str
    error: str | None
    result: dict[str, Any] | None
    template_name: str | None = None
    owner_name: str | None = None


class AnalysisPage(BaseModel):
    items: list[AnalysisSummary]
    total: int


class Stats(BaseModel):
    total: int
    authentic: int
    suspicious: int
    tampered: int
    pending: int
    failed: int
