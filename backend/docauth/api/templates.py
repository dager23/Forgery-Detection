"""Ground-truth templates for SSIM template matching (admin-managed)."""

from __future__ import annotations

import json
import uuid

import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from docauth.api.analyses import _read_limited
from docauth.api.deps import current_user, get_db, get_settings, require_admin
from docauth.config import Settings
from docauth.forensics.loader import UnsupportedFile, load_template_image
from docauth.models import Template, User
from docauth.schemas import Region, TemplateOut, TemplateUpdateIn

router = APIRouter(prefix="/api/templates", tags=["templates"])
_regions = TypeAdapter(list[Region])


def _parse_regions(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        return [r.model_dump(exclude_none=True) for r in _regions.validate_python(json.loads(raw))]
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid ignore_regions: {e}"
        ) from e


@router.get("", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Template).order_by(Template.name)).all()


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=120),
    doc_type: str = Form("generic", min_length=1, max_length=80),
    description: str = Form("", max_length=2000),
    ignore_regions: str | None = Form(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: User = Depends(require_admin),
) -> Template:
    data = await _read_limited(file, settings.max_upload_bytes)
    try:
        img = load_template_image(data)
    except UnsupportedFile as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    regions = _parse_regions(ignore_regions)
    fname = f"{uuid.uuid4().hex}.png"
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not store template")
    (settings.templates_dir / fname).write_bytes(buf.tobytes())
    t = Template(
        name=name.strip(),
        doc_type=doc_type.strip(),
        description=description.strip(),
        image_file=fname,
        width=img.shape[1],
        height=img.shape[0],
        ignore_regions=regions,
        created_by_id=admin.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return t


@router.get("/{template_id}/image")
def template_image(
    template_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(current_user),
):
    t = db.get(Template, template_id)
    path = settings.templates_dir / t.image_file if t else None
    if path is None or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: int,
    body: TemplateUpdateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Template:
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    if body.name is not None:
        t.name = body.name.strip()
    if body.doc_type is not None:
        t.doc_type = body.doc_type.strip()
    if body.description is not None:
        t.description = body.description.strip()
    if body.ignore_regions is not None:
        t.ignore_regions = [r.model_dump(exclude_none=True) for r in body.ignore_regions]
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_admin),
) -> Response:
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    path = settings.templates_dir / t.image_file
    db.delete(t)
    db.commit()
    path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
