from datetime import datetime
import json
import re
from typing import Any
from sqlalchemy.orm import Session

from app.models import TaskEvent, utcnow

MAX_CONTEXT_BYTES = 16384
SENSITIVE_KEYS = {"password", "secret", "token", "auth", "authorization", "cookie", "session", "key"}

REDACT_PATTERNS = [
    # 1. Authorization: Bearer <secret>
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;'\"<>]+"), r"\g<1>[REDACTED]"),
    # 2. JSON-style quoted string pairs: "key": "value" or 'key': 'value'
    (re.compile(r"""(?i)(["'])(password|passwd|token|cookie|session|api[_-]?key|secret|auth|authorization)\1\s*:\s*(["'])(.*?)\3"""), r"\1\2\1: \3[REDACTED]\3"),
    # 3. key=value or key: value for password, token, cookie, session, api_key, etc.
    (re.compile(r"(?i)\b(password|passwd|token|cookie|session|api[_-]?key|secret|auth|authorization)\s*([:=])\s*([^\s,;'\"<>]+)"), r"\1\2[REDACTED]"),
]


def sanitize_text(text: str) -> str:
    """Redact sensitive credentials, auth tokens, passwords, and API keys from text."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for pattern, replacement in REDACT_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def is_sensitive_key(k: str) -> bool:
    k_lower = str(k).lower()
    for sens in {"password", "passwd", "secret", "token", "auth", "authorization", "cookie", "session"}:
        if sens in k_lower:
            return True
    if any(s in k_lower for s in ("api_key", "apikey", "secret_key", "private_key", "auth_key", "access_key")):
        return True
    parts = set(re.split(r"[^a-zA-Z0-9]+", k_lower))
    if "key" in parts and k_lower in {"key", "app_key", "secret_key"}:
        return True
    return False


def sanitize_context(obj: Any) -> Any:
    """Recursively redact sensitive keys and string values."""
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            if is_sensitive_key(str(k)):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_context(v)
        return sanitized
    if isinstance(obj, list):
        return [sanitize_context(item) for item in obj]
    if isinstance(obj, str):
        return sanitize_text(obj)
    return obj


def serialize_context(context: dict | None) -> str:
    """Serialize context to JSON and enforce size limits."""
    if not context:
        return "{}"
    sanitized = sanitize_context(context)
    try:
        raw = json.dumps(sanitized, ensure_ascii=False)
    except Exception:
        return json.dumps({"error": "Failed to serialize context"}, ensure_ascii=False)

    if len(raw.encode("utf-8")) > MAX_CONTEXT_BYTES:
        # Compact and truncate
        truncated = {
            "truncated": True,
            "keys": list(sanitized.keys()) if isinstance(sanitized, dict) else [],
            "summary": "Context exceeded 16KB limit",
        }
        return json.dumps(truncated, ensure_ascii=False)
    return raw


def log_task_event(
    session: Session,
    *,
    job_id: int,
    event_type: str,
    message: str,
    level: str = "info",
    context: dict | None = None,
    timestamp: datetime | None = None,
) -> TaskEvent:
    """Insert a structured task event into the database with redacted secrets."""
    sanitized_message = sanitize_text(message)
    event = TaskEvent(
        job_id=job_id,
        timestamp=timestamp or utcnow(),
        level=level,
        event_type=event_type,
        message=sanitized_message,
        context_json=serialize_context(context),
    )
    session.add(event)
    session.flush()
    return event
