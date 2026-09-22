from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.media.probe import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from app.models import IndexRoot, IndexedPath, MediaAsset, WorkJob
from app.path_safety import require_allowed_path


MEDIA_EXTENSIONS = frozenset(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)


def validate_media_root_keys(
    session_factory: sessionmaker,
    settings: Settings,
    root_keys: list[str],
) -> list[str]:
    if not root_keys:
        raise ValueError("At least one indexed root is required")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in root_keys:
        safe = require_allowed_path(raw, settings.allowed_roots)
        value = str(safe)
        if value not in seen:
            seen.add(value)
            normalized.append(value)

    with session_factory() as session:
        known = set(
            session.scalars(
                select(IndexRoot.root).where(IndexRoot.root.in_(normalized))
            ).all()
        )
    missing = [root for root in normalized if root not in known]
    if missing:
        raise ValueError(f"Indexed roots not found: {missing}")
    return normalized


def enqueue_media_analysis(
    session_factory: sessionmaker,
    settings: Settings,
    root_keys: list[str],
) -> dict[str, Any]:
    normalized = validate_media_root_keys(session_factory, settings, root_keys)
    with session_factory() as session:
        work = WorkJob(
            kind="media-analysis",
            status="queued",
            state_json=json.dumps({"root_keys": normalized}, ensure_ascii=False),
        )
        session.add(work)
        session.commit()
        return {
            "work_job_id": int(work.id),
            "status": str(work.status),
            "root_keys": normalized,
        }


def enqueue_media_integrity_verification(
    session_factory: sessionmaker,
    settings: Settings,
    root_keys: list[str],
) -> dict[str, Any]:
    normalized = validate_media_root_keys(session_factory, settings, root_keys)
    with session_factory() as session:
        work = WorkJob(
            kind="media-integrity-verify",
            status="queued",
            state_json=json.dumps({"root_keys": normalized}, ensure_ascii=False),
        )
        session.add(work)
        session.commit()
        return {
            "work_job_id": int(work.id),
            "status": str(work.status),
            "root_keys": normalized,
        }


def _media_filters(
    *,
    root_key: str | None,
    media_kind: str | None,
    integrity_status: str | None,
    verification_status: str | None,
    search: str | None,
):
    filters = [IndexedPath.id == MediaAsset.indexed_path_id]
    if root_key:
        filters.append(IndexedPath.root_key == root_key)
    if media_kind:
        if media_kind not in {"image", "video"}:
            raise ValueError("media_kind must be image or video")
        filters.append(MediaAsset.media_kind == media_kind)
    if integrity_status:
        if integrity_status not in {"healthy", "corrupt", "unknown"}:
            raise ValueError("integrity_status must be healthy, corrupt, or unknown")
        filters.append(MediaAsset.integrity_status == integrity_status)
    if verification_status:
        if verification_status not in {"unverified", "baseline", "verified", "changed", "unknown"}:
            raise ValueError(
                "verification_status must be unverified, baseline, verified, changed, or unknown"
            )
        filters.append(MediaAsset.verification_status == verification_status)
    if search:
        needle = f"%{search.strip()}%"
        if needle != "%%":
            filters.append(
                or_(
                    IndexedPath.absolute_path.ilike(needle),
                    IndexedPath.basename.ilike(needle),
                )
            )
    return filters


def list_media_assets(
    session_factory: sessionmaker,
    *,
    page: int = 1,
    page_size: int = 50,
    root_key: str | None = None,
    media_kind: str | None = None,
    integrity_status: str | None = None,
    verification_status: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 500))
    offset = (page - 1) * page_size
    filters = _media_filters(
        root_key=root_key,
        media_kind=media_kind,
        integrity_status=integrity_status,
        verification_status=verification_status,
        search=search,
    )

    with session_factory() as session:
        total = session.scalar(
            select(func.count(MediaAsset.id))
            .select_from(MediaAsset)
            .join(IndexedPath, IndexedPath.id == MediaAsset.indexed_path_id)
            .where(*filters[1:])
        ) or 0
        rows = session.execute(
            select(MediaAsset, IndexedPath)
            .join(IndexedPath, IndexedPath.id == MediaAsset.indexed_path_id)
            .where(*filters[1:])
            .order_by(MediaAsset.id.desc())
            .limit(page_size)
            .offset(offset)
        ).all()

    items = []
    for asset, indexed in rows:
        items.append(
            {
                "id": int(asset.id),
                "indexed_path_id": int(indexed.id),
                "root_key": indexed.root_key,
                "path": indexed.absolute_path,
                "relative_path": indexed.relative_path,
                "basename": indexed.basename,
                "size": int(indexed.size),
                "mtime_ns": int(indexed.mtime_ns),
                "media_kind": asset.media_kind,
                "width": asset.width,
                "height": asset.height,
                "format": asset.format,
                "date_taken": asset.date_taken,
                "camera": asset.camera,
                "orientation": asset.orientation,
                "duration_seconds": asset.duration_seconds,
                "codec": asset.codec,
                "bitrate": asset.bitrate,
                "fps": asset.fps,
                "audio_codec": asset.audio_codec,
                "integrity_status": asset.integrity_status,
                "integrity_reason_code": asset.integrity_reason_code,
                "integrity_detail": asset.integrity_detail,
                "verification_status": asset.verification_status,
                "verification_reason_code": asset.verification_reason_code,
                "verification_detail": asset.verification_detail,
                "verification_checked_at": (
                    asset.verification_checked_at.isoformat()
                    if asset.verification_checked_at
                    else None
                ),
                "can_direct_delete": (
                    asset.integrity_status == "corrupt"
                    and isinstance(asset.corrupt_sha256, str)
                    and len(asset.corrupt_sha256) == 64
                    and int(asset.observed_device) == int(indexed.device)
                    and int(asset.observed_inode) == int(indexed.inode)
                    and int(asset.observed_size) == int(indexed.size)
                    and int(asset.observed_mtime_ns) == int(indexed.mtime_ns)
                ),
                "probed_at": asset.probed_at.isoformat() if asset.probed_at else None,
            }
        )

    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


def media_summary(session_factory: sessionmaker) -> dict[str, int]:
    with session_factory() as session:
        total = session.scalar(select(func.count(MediaAsset.id))) or 0
        image = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.media_kind == "image")
        ) or 0
        video = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.media_kind == "video")
        ) or 0
        healthy = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.integrity_status == "healthy")
        ) or 0
        corrupt = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.integrity_status == "corrupt")
        ) or 0
        unknown = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.integrity_status == "unknown")
        ) or 0
        verification_unverified = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.verification_status == "unverified")
        ) or 0
        verification_baseline = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.verification_status == "baseline")
        ) or 0
        verification_verified = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.verification_status == "verified")
        ) or 0
        verification_changed = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.verification_status == "changed")
        ) or 0
        verification_unknown = session.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.verification_status == "unknown")
        ) or 0
    return {
        "total": int(total),
        "image": int(image),
        "video": int(video),
        "healthy": int(healthy),
        "corrupt": int(corrupt),
        "unknown": int(unknown),
        "verification_unverified": int(verification_unverified),
        "verification_baseline": int(verification_baseline),
        "verification_verified": int(verification_verified),
        "verification_changed": int(verification_changed),
        "verification_unknown": int(verification_unknown),
    }
