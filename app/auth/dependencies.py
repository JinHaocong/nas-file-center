from __future__ import annotations

from urllib.parse import urlparse
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as DbSession

from app.auth.sessions import get_valid_session
from app.models import Session, User


def get_client_ip(request: Request) -> str:
    direct_ip = request.client.host if request.client and request.client.host else "127.0.0.1"
    settings = getattr(request.app.state, "settings", None)
    
    # Only trust forwarded headers if the direct connecting client is a trusted reverse proxy
    if settings and settings.is_trusted_proxy(direct_ip):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[0]
        real_ip = request.headers.get("x-real-ip")
        if real_ip and real_ip.strip():
            return real_ip.strip()

    return direct_ip


def verify_csrf_and_origin(request: Request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host = request.headers.get("host")
    direct_ip = request.client.host if request.client and request.client.host else "127.0.0.1"
    settings = getattr(request.app.state, "settings", None)

    # Build allowed hosts list (Host is always trusted as actual connected host)
    expected_hosts = set()
    if host:
        host_clean = host.strip().lower()
        expected_hosts.add(host_clean)
        if ":" in host_clean:
            expected_hosts.add(host_clean.split(":")[0])

    # ONLY trust X-Forwarded-Host / X-Forwarded-Server if connecting client is in TRUSTED_PROXIES
    if settings and settings.is_trusted_proxy(direct_ip):
        forwarded_host = request.headers.get("x-forwarded-host")
        forwarded_server = request.headers.get("x-forwarded-server")
        for raw in (forwarded_host, forwarded_server):
            if raw:
                raw_clean = raw.strip().lower()
                expected_hosts.add(raw_clean)
                if ":" in raw_clean:
                    expected_hosts.add(raw_clean.split(":")[0])

    if not origin and not referer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: missing Origin or Referer header on mutation request",
        )

    if origin:
        parsed_origin = urlparse(origin)
        origin_host = parsed_origin.netloc.lower()
        origin_host_clean = origin_host.split(":")[0] if ":" in origin_host else origin_host
        if origin_host not in expected_hosts and origin_host_clean not in expected_hosts:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"CSRF validation failed: Origin mismatch ({origin_host})",
            )
    elif referer:
        parsed_ref = urlparse(referer)
        ref_host = parsed_ref.netloc.lower()
        ref_host_clean = ref_host.split(":")[0] if ":" in ref_host else ref_host
        if ref_host not in expected_hosts and ref_host_clean not in expected_hosts:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"CSRF validation failed: Referer mismatch ({ref_host})",
            )


def get_current_session(request: Request) -> Session:
    settings = request.app.state.settings
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Validate CSRF on authenticated mutating requests
    verify_csrf_and_origin(request)

    service = request.app.state.service
    with service.SessionLocal() as db_session:
        session_obj = get_valid_session(db_session, raw_token)
        if session_obj is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid",
            )
        return session_obj


def get_current_user(
    request: Request,
    current_session: Session = Depends(get_current_session),
) -> User:
    return current_session.user


def require_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user
