from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import IndexRoot, ScanJob, WorkJob, utcnow
from app.path_safety import require_allowed_path, require_unreserved_path


@dataclass(frozen=True)
class EnqueuedJob:
    work_job: WorkJob
    index_root: IndexRoot | None = None
    scan_job: ScanJob | None = None
    normalized_roots: tuple[str, ...] = ()
    index_root_created: bool = False


def _normalize_allowed_unreserved_root(settings: Settings, raw: str) -> str:
    safe = require_allowed_path(raw, settings.allowed_roots)
    safe = require_unreserved_path(safe, settings.quarantine_root)
    return str(safe)


def enqueue_index_work(
    session: Session,
    settings: Settings,
    *,
    root: str,
    existing_index_root_id: int | None = None,
    allow_create_index_root: bool = True,
) -> EnqueuedJob:
    root_str = _normalize_allowed_unreserved_root(settings, root)
    safe_root = require_allowed_path(root_str, settings.allowed_roots)
    if not safe_root.is_dir():
        raise ValueError(f"Not a directory: {safe_root}")

    idx_root: IndexRoot | None
    created = False
    if existing_index_root_id is not None:
        idx_root = session.get(IndexRoot, existing_index_root_id)
        if idx_root is None:
            raise ValueError(f"Index root #{existing_index_root_id} not found")
        if idx_root.root != root_str:
            raise ValueError(
                f"Index root #{existing_index_root_id} no longer matches scheduled root"
            )
    else:
        idx_root = session.scalar(select(IndexRoot).where(IndexRoot.root == root_str))
        if idx_root is None:
            if not allow_create_index_root:
                raise ValueError(f"Index root not found: {root_str}")
            idx_root = IndexRoot(root=root_str, created_at=utcnow())
            session.add(idx_root)
            session.flush()
            created = True

    work = WorkJob(
        kind="index-root",
        status="queued",
        state_json=json.dumps({"root": root_str}, ensure_ascii=False),
    )
    session.add(work)
    session.flush()
    return EnqueuedJob(
        work_job=work,
        index_root=idx_root,
        normalized_roots=(root_str,),
        index_root_created=created,
    )


def enqueue_scan_work(
    session: Session,
    settings: Settings,
    *,
    name: str,
    roots: list[str],
    isolate: bool = False,
    min_size: str | None = None,
    name_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    require_existing_dirs: bool = False,
    require_unique_roots: bool = False,
) -> EnqueuedJob:
    safe_roots = [_normalize_allowed_unreserved_root(settings, root) for root in roots]
    if not safe_roots:
        raise ValueError("At least one root is required")
    if require_unique_roots and len(set(safe_roots)) != len(safe_roots):
        raise ValueError("Scan roots must be unique")
    if isolate and len(safe_roots) < 2:
        raise ValueError("Isolate scan requires at least two roots")

    if require_existing_dirs:
        for root in safe_roots:
            if not require_allowed_path(root, settings.allowed_roots).is_dir():
                raise ValueError(f"Not a directory: {root}")

    scan = ScanJob(
        name=name,
        mode="isolate" if isolate else "normal",
        roots_json=json.dumps(safe_roots, ensure_ascii=False),
        status="queued",
        fclones_args_json=json.dumps(
            {
                "min_size": min_size,
                "name_patterns": name_patterns,
                "exclude_patterns": exclude_patterns,
            },
            ensure_ascii=False,
        ),
    )
    session.add(scan)
    session.flush()

    work = WorkJob(
        kind="fclones-scan",
        status="queued",
        state_json=json.dumps(
            {
                "scan_job_id": scan.id,
                "roots": safe_roots,
                "isolate": isolate,
                "min_size": min_size,
                "name_patterns": name_patterns,
                "exclude_patterns": exclude_patterns,
            },
            ensure_ascii=False,
        ),
    )
    session.add(work)
    session.flush()
    return EnqueuedJob(
        work_job=work,
        scan_job=scan,
        normalized_roots=tuple(safe_roots),
    )


def validate_media_roots_in_session(
    session: Session,
    settings: Settings,
    root_keys: list[str],
    *,
    require_unreserved: bool = False,
) -> list[str]:
    if not root_keys:
        raise ValueError("At least one indexed root is required")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in root_keys:
        safe = require_allowed_path(raw, settings.allowed_roots)
        if require_unreserved:
            safe = require_unreserved_path(safe, settings.quarantine_root)
        root = str(safe)
        if root not in seen:
            seen.add(root)
            normalized.append(root)

    known = set(
        session.scalars(
            select(IndexRoot.root).where(IndexRoot.root.in_(normalized))
        ).all()
    )
    missing = [root for root in normalized if root not in known]
    if missing:
        raise ValueError(f"Indexed roots not found: {missing}")
    return normalized


def enqueue_media_work(
    session: Session,
    settings: Settings,
    *,
    kind: str,
    root_keys: list[str],
    require_unreserved: bool = False,
) -> EnqueuedJob:
    if kind not in {"media-analysis", "media-integrity-verify"}:
        raise ValueError(f"Unsupported media work kind: {kind}")

    normalized = validate_media_roots_in_session(
        session,
        settings,
        root_keys,
        require_unreserved=require_unreserved,
    )
    work = WorkJob(
        kind=kind,
        status="queued",
        state_json=json.dumps({"root_keys": normalized}, ensure_ascii=False),
    )
    session.add(work)
    session.flush()
    return EnqueuedJob(
        work_job=work,
        normalized_roots=tuple(normalized),
    )
