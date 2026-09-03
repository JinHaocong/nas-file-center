from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession, joinedload

from app.models import Session, User, utcnow


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(
    db_session: DbSession,
    user_id: int,
    max_age_seconds: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[Session, str]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = utcnow() + timedelta(seconds=max_age_seconds)

    session_obj = Session(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db_session.add(session_obj)
    db_session.commit()
    db_session.refresh(session_obj)
    return session_obj, raw_token


def get_valid_session(db_session: DbSession, raw_token: str) -> Session | None:
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    now = utcnow()
    session_obj = db_session.scalar(
        select(Session)
        .options(joinedload(Session.user))
        .where(
            Session.token_hash == token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )
    if session_obj is not None:
        if not session_obj.user.is_active:
            return None
        # update last_seen_at
        session_obj.last_seen_at = now
        db_session.commit()
    return session_obj


def revoke_session(db_session: DbSession, session_id: int, user_id: int) -> bool:
    session_obj = db_session.scalar(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
    )
    if session_obj is None:
        return False
    session_obj.revoked_at = utcnow()
    db_session.commit()
    return True


def revoke_user_sessions(db_session: DbSession, user_id: int, except_session_id: int | None = None) -> int:
    query = (
        update(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    if except_session_id is not None:
        query = query.where(Session.id != except_session_id)
    result = db_session.execute(query)
    db_session.commit()
    return result.rowcount
