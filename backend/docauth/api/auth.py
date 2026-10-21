"""Registration, login, logout and current-user endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from docauth.api.deps import current_user, get_db, get_settings
from docauth.config import Settings
from docauth.models import User
from docauth.schemas import AuthOut, LoginIn, RegisterIn, UserOut
from docauth.security import create_token, dummy_verify, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _issue(response: Response, request: Request, settings: Settings, user: User) -> AuthOut:
    token = create_token(user.id, request.app.state.secret_key, settings.token_ttl_minutes)
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.token_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthOut(user=UserOut.model_validate(user), access_token=token)


@router.post("/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthOut:
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(name=body.name, email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _issue(response, request, settings, user)


@router.post("/login", response_model=AuthOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthOut:
    email = body.email.lower()
    client = request.client.host if request.client else "?"
    key = f"{email}|{client}"
    throttle = request.app.state.login_throttle
    wait = throttle.retry_after(key)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        dummy_verify()
        ok = False
    else:
        ok = verify_password(body.password, user.password_hash)
    if not ok or user is None:
        throttle.record_failure(key)
        # Same message for unknown email and wrong password: don't leak which accounts exist
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated")
    throttle.reset(key)
    return _issue(response, request, settings, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, settings: Settings = Depends(get_settings)) -> Response:
    response.delete_cookie(settings.cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
