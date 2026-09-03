from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.dependencies import get_client_ip, get_current_session, get_current_user, verify_csrf_and_origin
from app.auth.password import hash_password, verify_password
from app.auth.sessions import create_session, hash_token, revoke_session, revoke_user_sessions
from app.models import Session, User, utcnow


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=256)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str


@router.post("/login", response_model=UserResponse)
def login(request: Request, response: Response, payload: LoginRequest):
    limiter = request.app.state.rate_limiter
    settings = request.app.state.settings
    service = request.app.state.service
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    if limiter.is_rate_limited(payload.username, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过多，账户或IP已被临时锁定15分钟",
        )

    with service.SessionLocal() as db_session:
        user = db_session.scalar(
            select(User).where(User.username == payload.username.strip())
        )
        if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
            limiter.record_failure(payload.username, ip)
            # Avoid user enumeration by generic message
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )

        limiter.record_success(payload.username, ip)
        user.last_login_at = utcnow()
        db_session.commit()

        session_obj, raw_token = create_session(
            db_session,
            user_id=user.id,
            max_age_seconds=settings.session_max_age_seconds,
            ip_address=ip,
            user_agent=user_agent,
        )

        response.set_cookie(
            key=settings.session_cookie_name,
            value=raw_token,
            max_age=settings.session_max_age_seconds,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
            path="/",
        )

        return UserResponse(id=user.id, username=user.username, role=user.role)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_session: Session = Depends(get_current_session),
):
    settings = request.app.state.settings
    service = request.app.state.service

    with service.SessionLocal() as db_session:
        revoke_session(db_session, current_session.id, current_session.user_id)

    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
    )


@router.post("/change-password")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_session: Session = Depends(get_current_session),
):
    service = request.app.state.service

    with service.SessionLocal() as db_session:
        user = db_session.get(User, current_session.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if not verify_password(payload.old_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="旧密码不正确",
            )

        if len(payload.new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="新密码长度不能少于6位",
            )

        user.password_hash = hash_password(payload.new_password)
        user.updated_at = utcnow()
        db_session.commit()

        # Revoke other sessions for security, preserving the current active session
        revoke_user_sessions(db_session, user.id, except_session_id=current_session.id)

    return {"status": "ok", "message": "密码修改成功"}


@router.get("/sessions")
def list_sessions(
    current_session: Session = Depends(get_current_session),
    request: Request = None,
):
    service = request.app.state.service
    now = utcnow()
    with service.SessionLocal() as db_session:
        sessions = list(
            db_session.scalars(
                select(Session)
                .where(
                    Session.user_id == current_session.user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                )
                .order_by(Session.last_seen_at.desc())
            )
        )
        return {
            "sessions": [
                {
                    "id": s.id,
                    "ip_address": s.ip_address or "Unknown",
                    "user_agent": s.user_agent or "Unknown",
                    "created_at": s.created_at,
                    "last_seen_at": s.last_seen_at,
                    "expires_at": s.expires_at,
                    "is_current": (s.id == current_session.id),
                }
                for s in sessions
            ]
        }


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    response: Response,
    request: Request,
    current_session: Session = Depends(get_current_session),
):
    service = request.app.state.service
    settings = request.app.state.settings

    with service.SessionLocal() as db_session:
        success = revoke_session(db_session, session_id, current_session.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found or already revoked")

    if session_id == current_session.id:
        response.delete_cookie(key=settings.session_cookie_name, path="/")

    return {"status": "ok"}
