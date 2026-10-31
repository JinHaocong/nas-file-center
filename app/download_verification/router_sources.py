"""Admin-managed AList / OpenList verification sources and read-only remote browsing."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select, text

from app.auth.dependencies import require_admin_user
from .models import DownloadVerificationSource
from .sources import AListAPIClient, validate_source_url, source_secret_path, write_secret, clear_source_session
from .webdav import WebDAVError, relative_parts


router = APIRouter(prefix="/api/download-verifications/sources", tags=["download-verification"],
                   dependencies=[Depends(require_admin_user)])


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(pattern="^(alist|openlist)$")
    base_url: str = Field(min_length=8, max_length=512)
    username: str = Field(default="", max_length=255)
    password: SecretStr | None = None


class SourceOTP(BaseModel):
    model_config = ConfigDict(extra="forbid")
    otp_code: str = Field(pattern=r"^[0-9]{6,8}$")


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, pattern="^(alist|openlist)$")
    base_url: str | None = Field(default=None, min_length=8, max_length=512)
    username: str | None = Field(default=None, max_length=255)
    password: SecretStr | None = None


def _public(s: DownloadVerificationSource) -> dict:
    return {"id": s.id, "name": s.name, "provider": s.provider,
            "base_url": s.base_url, "username": s.username,
            "has_password": bool(s.secret_file), "revision": s.revision, "active": s.active}


def _origin(url: str) -> str:
    try:
        return validate_source_url(url)
    except (ValueError, OverflowError):
        raise HTTPException(422, "INVALID_SOURCE_URL") from None


def _source(session, source_id: int) -> DownloadVerificationSource:
    source = session.get(DownloadVerificationSource, source_id)
    if source is None or not source.active:
        raise HTTPException(404, "SOURCE_NOT_FOUND")
    return source


@router.get("")
def list_sources(request: Request):
    with request.app.state.service.SessionLocal() as session:
        rows = session.scalars(select(DownloadVerificationSource).where(
            DownloadVerificationSource.active.is_(True)).order_by(DownloadVerificationSource.id)).all()
        return {"items": [_public(source) for source in rows]}


@router.post("", status_code=201)
def create_source(request: Request, body: SourceCreate):
    config_dir = Path(request.app.state.settings.config_dir)
    if not body.name.strip():
        raise HTTPException(422, "SOURCE_NAME_REQUIRED")
    secret = None
    password = body.password.get_secret_value() if body.password is not None else ""
    if body.username and not password:
        raise HTTPException(422, "SOURCE_PASSWORD_REQUIRED")
    if not body.username and password:
        raise HTTPException(422, "SOURCE_USERNAME_REQUIRED")
    url = _origin(body.base_url)
    if password:
        secret = "source-" + uuid4().hex + ".secret"
        try:
            write_secret(config_dir, secret, password)
        except (OSError, ValueError):
            raise HTTPException(422, "SOURCE_SECRET_UNAVAILABLE") from None
    try:
        with request.app.state.service.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            source = DownloadVerificationSource(
                name=body.name.strip(), provider=body.provider, base_url=url,
                username=body.username, secret_file=secret, revision=1, active=True)
            session.add(source)
            session.commit()
            return _public(source)
    except BaseException:
        if secret:
            source_secret_path(config_dir, secret).unlink(missing_ok=True)
        raise


@router.put("/{source_id}")
def update_source(request: Request, source_id: int, body: SourceUpdate):
    config_dir = Path(request.app.state.settings.config_dir)
    new_secret = None
    old_secret = None
    if body.name is not None and not body.name.strip():
        raise HTTPException(422, "SOURCE_NAME_REQUIRED")
    password = body.password.get_secret_value() if body.password is not None else None
    if password == "":
        raise HTTPException(422, "EMPTY_PASSWORD_NOT_ALLOWED")
    try:
        with request.app.state.service.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            source = _source(session, source_id)
            old_secret = source.secret_file
            name = body.name.strip() if body.name is not None else source.name
            username = body.username if body.username is not None else source.username
            if username and not (password or source.secret_file):
                raise HTTPException(422, "SOURCE_PASSWORD_REQUIRED")
            if not username and password:
                raise HTTPException(422, "SOURCE_USERNAME_REQUIRED")
            if password is not None:
                new_secret = "source-" + uuid4().hex + ".secret"
                write_secret(config_dir, new_secret, password)
            source.name = name
            source.provider = body.provider if body.provider is not None else source.provider
            source.base_url = _origin(body.base_url) if body.base_url is not None else source.base_url
            source.username = username
            if new_secret:
                source.secret_file = new_secret
            elif not username:
                source.secret_file = None
            source.revision += 1
            session.commit()
            result = _public(source)
            current_secret = source.secret_file
        if old_secret and old_secret != current_secret:
            try:
                clear_source_session(config_dir, old_secret)
                source_secret_path(config_dir, old_secret).unlink(missing_ok=True)
            except OSError:
                pass
        return result
    except BaseException:
        if new_secret:
            source_secret_path(config_dir, new_secret).unlink(missing_ok=True)
        raise


@router.delete("/{source_id}")
def disable_source(request: Request, source_id: int):
    # Soft delete retains historical run provenance. Queued jobs now fail closed.
    with request.app.state.service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        source = _source(session, source_id)
        old_secret = source.secret_file
        source.active = False
        source.secret_file = None
        source.revision += 1
        session.commit()
    if old_secret:
        try:
            clear_source_session(Path(request.app.state.settings.config_dir), old_secret)
            source_secret_path(Path(request.app.state.settings.config_dir), old_secret).unlink(missing_ok=True)
        except OSError:
            pass
    return {"disabled": True}


@router.get("/{source_id}/browse")
def browse_source(request: Request, source_id: int, path: str = ""):
    try:
        parts = relative_parts(path)
    except WebDAVError:
        raise HTTPException(422, "INVALID_REMOTE_PATH") from None
    with request.app.state.service.SessionLocal() as session:
        source = _source(session, source_id)
        base_url, username, secret_name = source.base_url, source.username, source.secret_file
    try:
        password_file = str(source_secret_path(
            Path(request.app.state.settings.config_dir), secret_name)) if secret_name else None
        client = AListAPIClient(base_url=base_url, username=username, password_file=password_file,
                                session_config_dir=Path(request.app.state.settings.config_dir),
                                session_secret_name=secret_name)
        items = client.list_directory(parts)
    except (ValueError, OSError, WebDAVError):
        raise HTTPException(502, "SOURCE_BROWSE_UNAVAILABLE") from None
    return {"path": "/".join(parts), "items": [
        {"name": key[-1], "kind": meta["kind"], "size": meta["size"]}
        for key, meta in sorted(items.items(), key=lambda p: (p[1]["kind"] != "directory", p[0]))
    ]}


@router.post("/{source_id}/authenticate")
def authenticate_source(request: Request, source_id: int, body: SourceOTP):
    """Administrator supplies an ephemeral OTP; never persist or echo the code."""
    with request.app.state.service.SessionLocal() as session:
        source = _source(session, source_id)
        base_url, username, secret_name = source.base_url, source.username, source.secret_file
    if not username or not secret_name:
        raise HTTPException(422, "SOURCE_CREDENTIALS_REQUIRED")
    config_dir = Path(request.app.state.settings.config_dir)
    try:
        # Force fresh login even if an older cached session exists.
        client = AListAPIClient(
            base_url=base_url, username=username,
            password_file=str(source_secret_path(config_dir, secret_name)),
            session_config_dir=config_dir, session_secret_name=secret_name,
            otp_code=body.otp_code)
        client.list_directory(())
    except (ValueError, OSError, WebDAVError):
        raise HTTPException(401, "SOURCE_OTP_AUTH_FAILED") from None
    return {"authenticated": True}
