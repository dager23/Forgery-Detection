"""Upload documents for analysis, poll results, fetch artifacts and PDF reports."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from docauth.api.deps import current_user, get_db, get_settings
from docauth.config import Settings
from docauth.forensics.loader import SUPPORTED, sniff_mime
from docauth.models import Analysis, Template, User
from docauth.schemas import AnalysisOut, AnalysisPage, AnalysisSummary, Stats
from docauth.services import storage
from docauth.services.report import build_report

router = APIRouter(prefix="/api/analyses", tags=["analyses"])
CHUNK = 1024 * 1024


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    buf = bytearray()
    while chunk := await file.read(CHUNK):
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(
                413,
                f"File exceeds the {limit // (1024 * 1024)} MB limit",
            )
    return bytes(buf)


def _flag(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"false", "0", "no", "off"}


def _get_owned(db: Session, analysis_id: str, user: User) -> Analysis:
    a = db.get(Analysis, analysis_id)
    # 404 (not 403) for other users' analyses so IDs can't be probed
    if a is None or (a.user_id != user.id and not user.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return a


def _out(a: Analysis) -> AnalysisOut:
    out = AnalysisOut.model_validate(a)
    out.template_name = a.template.name if a.template else None
    out.owner_name = a.user.name if a.user else None
    return out


def _scope(stmt, user: User, scope: str):
    if scope == "all":
        if not user.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
        return stmt
    return stmt.where(Analysis.user_id == user.id)


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    request: Request,
    file: UploadFile = File(...),
    template_id: int | None = Form(None),
    # parsed by hand: newer FastAPI turns an omitted bool form field into False (checkbox
    # semantics), but API clients that don't send it should still get auto-detection
    auto_template: str | None = Form(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> AnalysisOut:
    data = await _read_limited(file, settings.max_upload_bytes)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty")
    mime = sniff_mime(data)
    if mime not in SUPPORTED:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Unsupported file type. Upload a JPEG, PNG, TIFF, BMP, WebP or PDF.",
        )
    if template_id is not None and db.get(Template, template_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selected template does not exist")

    stored = storage.save_upload(settings, data, mime)
    a = Analysis(
        user_id=user.id,
        template_id=template_id,
        auto_template=_flag(auto_template, default=True) and template_id is None,
        filename=storage.safe_display_name(file.filename),
        stored_file=stored,
        mime=mime,
        size_bytes=len(data),
        sha256=storage.sha256(data),
        status="queued",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    request.app.state.runner.submit(a.id)
    return _out(a)


@router.get("", response_model=AnalysisPage)
def list_analyses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_: str | None = Query(None, alias="status", pattern="^(queued|running|done|failed)$"),
    verdict: str | None = Query(None, pattern="^(authentic|suspicious|tampered)$"),
    q: str | None = Query(None, max_length=100),
    scope: str = Query("mine", pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnalysisPage:
    stmt = _scope(select(Analysis), user, scope)
    if status_:
        stmt = stmt.where(Analysis.status == status_)
    if verdict:
        stmt = stmt.where(Analysis.verdict == verdict)
    if q:
        stmt = stmt.where(Analysis.filename.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Analysis.created_at.desc()).limit(limit).offset(offset)).all()
    names = dict(
        db.execute(select(User.id, User.name).where(User.id.in_({r.user_id for r in rows}))).all()
    )
    items = [
        AnalysisSummary.model_validate(r).model_copy(update={"owner_name": names.get(r.user_id)})
        for r in rows
    ]
    return AnalysisPage(items=items, total=total)


@router.get("/stats", response_model=Stats)
def stats(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Stats:
    base = _scope(select(Analysis.status, Analysis.verdict), user, scope).subquery()
    rows = db.execute(
        select(base.c.status, base.c.verdict, func.count()).group_by(base.c.status, base.c.verdict)
    ).all()
    s = {"total": 0, "authentic": 0, "suspicious": 0, "tampered": 0, "pending": 0, "failed": 0}
    for st, verdict, n in rows:
        s["total"] += n
        if st == "done" and verdict in s:
            s[verdict] += n
        elif st in ("queued", "running"):
            s["pending"] += n
        elif st == "failed":
            s["failed"] += n
    return Stats(**s)


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(
    analysis_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> AnalysisOut:
    return _out(_get_owned(db, analysis_id, user))


@router.get("/{analysis_id}/files/{name}")
def get_artifact(
    analysis_id: str,
    name: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
):
    _get_owned(db, analysis_id, user)
    path = storage.artifact_path(settings, analysis_id, name)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{analysis_id}/original")
def get_original(
    analysis_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
):
    a = _get_owned(db, analysis_id, user)
    path = settings.uploads_dir / a.stored_file
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Original file is no longer stored")
    return FileResponse(path, media_type=a.mime, filename=a.filename)


@router.get("/{analysis_id}/report.pdf")
def get_report(
    analysis_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> Response:
    a = _get_owned(db, analysis_id, user)
    if a.status != "done" or not a.result:
        raise HTTPException(status.HTTP_409_CONFLICT, "Analysis has not finished yet")
    pdf = build_report(_out(a).model_dump(), storage.analysis_dir(settings, a.id))
    stem = a.filename.rsplit(".", 1)[0][:60] or "document"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="docauth-{stem}.pdf"'},
    )


@router.post("/{analysis_id}/rerun", response_model=AnalysisOut, status_code=202)
def rerun(
    analysis_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnalysisOut:
    a = _get_owned(db, analysis_id, user)
    if a.status in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Analysis is already in progress")
    a.status, a.error, a.verdict, a.score, a.result = "queued", None, None, None, None
    a.completed_at = None
    db.commit()
    request.app.state.runner.submit(a.id)
    return _out(a)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(
    analysis_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> Response:
    a = _get_owned(db, analysis_id, user)
    stored = a.stored_file
    db.delete(a)
    db.commit()
    storage.delete_analysis_files(settings, analysis_id, stored)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
