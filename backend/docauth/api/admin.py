"""Admin-only user management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from docauth.api.deps import get_db, require_admin
from docauth.models import Analysis, User
from docauth.schemas import UserOut, UserUpdateIn

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminUserOut(UserOut):
    analysis_count: int = 0


@router.get("/users", response_model=list[AdminUserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    counts = dict(
        db.execute(select(Analysis.user_id, func.count()).group_by(Analysis.user_id)).all()
    )
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        AdminUserOut.model_validate(u).model_copy(update={"analysis_count": counts.get(u.id, 0)})
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and (body.role == "user" or body.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or deactivate yourself")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return user
