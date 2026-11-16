"""Atomic bulk Move Plan creation for a completed, read-only media-sort preview.

This deliberately optimizes *only* trusted media-sort preview rows. Generic
Plans retain their existing creation logic. Every row still receives source
existence, containment, quarantine, target-name, and no-symlink checks. The
result is a normal draft Plan: Freeze/Validate/Execute remain mandatory.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.filters.media_types import get_media_type
from app.models import BatchPlan, BatchPlanItem
from app.path_safety import (
    require_allowed_path,
    require_unreserved_path,
    validate_mutation_destination,
)

INSERT_BATCH_SIZE = 750
_TARGET_FOLDER_PATTERN = re.compile(r"(?P<kind>[PV])(?:_[1-9][0-9]*)?", re.IGNORECASE)


def _validated_move(row: dict, settings: Settings, *, sequence: int) -> dict:
    if row.get("conflict") is not False or row.get("media_kind") not in ("image", "video"):
        raise ValueError(f"Media preview item {sequence} is conflicting or invalid")
    source_text = row.get("source")
    target_text = row.get("target")
    size = row.get("expected_size")
    if not isinstance(source_text, str) or not isinstance(target_text, str):
        raise ValueError(f"Media preview item {sequence} has invalid paths")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > 2**63 - 1:
        raise ValueError(f"Media preview item {sequence} has invalid size")

    raw_source = Path(source_text).expanduser()
    raw_target = Path(target_text).expanduser()
    if not raw_source.is_absolute() or not raw_target.is_absolute():
        raise ValueError("Media-sort Move Plan paths must be absolute")
    if raw_source.is_symlink():
        raise ValueError(f"Media-sort source is a symlink: {source_text}")

    # Preserve the standard Plan's containment and reserved-store checks.
    source = require_unreserved_path(
        require_allowed_path(raw_source, settings.allowed_roots), settings.quarantine_root,
    )
    if not source.is_file():
        raise ValueError(f"Media-sort source is missing or not a file: {source_text}")
    target = validate_mutation_destination(
        raw_target, settings.allowed_roots, quarantine_root=settings.quarantine_root,
    )
    folder = _TARGET_FOLDER_PATTERN.fullmatch(target.parent.name)
    expected_letter = "P" if row["media_kind"] == "image" else "V"
    if (not folder or folder.group("kind").upper() != expected_letter
            or target.parent.parent != source.parent
            or target == source
            or get_media_type(source.suffix) != row["media_kind"]):
        raise ValueError(f"Media-sort item {sequence} escapes its source directory or kind")

    return {
        "sequence": sequence,
        "operation": "move",
        "source_path": str(source),
        "target_path": str(target),
        "keep_path": None,
        "expected_size": size,
        "expected_hash": None,
        "expected_mtime_ns": 0,
        "expected_device": 0,
        "expected_inode": 0,
        "state": "planned",
        "metadata_json": "{}",
    }


def create_media_sort_bulk_plan(
    session_factory: sessionmaker,
    settings: Settings,
    *,
    items_file: Path,
    summary: dict,
    preview_job_id: int,
    skip_conflicts: bool = False,
) -> BatchPlan:
    if not isinstance(skip_conflicts, bool):
        raise ValueError("skip_conflicts must be boolean")
    """Insert rows in batches under ONE transaction: all-or-nothing on errors.

    No intermediate, half-generated Plan can be frozen or executed. SQLAlchemy
    Core executemany avoids the enormous per-row ORM identity-map overhead.
    """
    count = summary.get("count")
    conflicting = summary.get("conflict_count")
    ready_count = summary.get("ready_count", count)
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in (count, conflicting, ready_count)):
        raise ValueError("Media-sort preview counts must be integers")
    if (count <= 0 or count > 300_000 or not 0 < ready_count <= count
            or conflicting < 0 or ready_count + conflicting != count):
        raise ValueError("Media-sort preview counts are invalid")
    if conflicting and not skip_conflicts:
        raise ValueError("Media-sort preview contains conflicts; skipping requires explicit confirmation")

    name = ("媒体文件递归分类（每目录 P / V）"
            if summary.get("recursive") else "媒体文件分类（P / V）")
    metadata = {
        "source": "media-sort",
        "preview_job_id": preview_job_id,
        "recursive": summary.get("recursive", False),
        "smart_skip": summary.get("smart_skip", True),
        "conflict_policy": "skip" if skip_conflicts else "block",
        "skipped_conflict_count": conflicting if skip_conflicts else 0,
    }

    with session_factory() as session:
        # The ORM Plan row and all Core item batches share this transaction.
        # If any row is invalid, nothing remains in the database.
        plan = BatchPlan(
            name=name, kind="media-sort", status="draft",
            expected_changes=ready_count, metadata_json=json.dumps(metadata, ensure_ascii=False),
        )
        session.add(plan)
        session.flush()
        batch: list[dict] = []
        seen_targets: set[str] = set()
        written = 0
        seen = 0
        skipped = 0
        with items_file.open("r", encoding="utf-8") as stream:
            for line in stream:
                seen += 1
                if seen > count:
                    raise ValueError("Media preview contains extra plan items")
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError(f"Invalid media preview item {seen}")
                if raw.get("conflict") is True:
                    if not skip_conflicts:
                        raise ValueError("Media preview contains unresolved conflicts")
                    skipped += 1
                    continue
                if raw.get("conflict") is not False:
                    raise ValueError(f"Media preview item {seen} has invalid conflict status")
                move = _validated_move(raw, settings, sequence=written + 1)
                folded = move["target_path"].casefold()
                if folded in seen_targets:
                    raise ValueError(f"Duplicate media-sort target in preview: {move['target_path']}")
                seen_targets.add(folded)
                move["plan_id"] = plan.id
                batch.append(move)
                written += 1
                if len(batch) >= INSERT_BATCH_SIZE:
                    session.execute(insert(BatchPlanItem), batch)
                    batch.clear()
        if seen != count or written != ready_count or skipped != conflicting:
            raise ValueError("Media preview item counts changed; please rescan")
        if batch:
            session.execute(insert(BatchPlanItem), batch)
        session.commit()
        session.refresh(plan)
        return plan
