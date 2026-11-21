"""MediaPackage report namespace and retention safety.

SQLite may reuse a deleted highest INTEGER PRIMARY KEY value.  Private
report artifacts are *not* deleted alongside task-history rows, so a new
MediaPackage task must reserve IDs that are absent from both the database
and either report namespace.  Call inside a BEGIN IMMEDIATE transaction.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import WorkJob


_REPORT_ID = re.compile(r"^([1-9][0-9]*)(?:[.]|$)")


def _highest_report_id(directory: Path) -> int:
    """Read filenames only; never remove or follow report artifacts."""
    if directory.is_symlink():
        raise ValueError(f"Unsafe MediaPackage report directory: {directory}")
    if not directory.exists():
        return 0
    if not directory.is_dir():
        raise ValueError(f"MediaPackage report namespace is not a directory: {directory}")
    largest = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            matched = _REPORT_ID.match(entry.name)
            if matched:
                largest = max(largest, int(matched.group(1)))
    return largest


def next_media_package_job_id(session: Session, settings: Settings) -> int:
    """Allocate an unused ID across WorkJobs and immutable report artifacts.

    Caller MUST hold SQLite BEGIN IMMEDIATE until the WorkJob is inserted.
    Failed/completed execution manifests are never overwritten or cleaned up.
    """
    root = settings.reports_dir
    if root.is_symlink():
        raise ValueError("Unsafe MediaPackage reports root")
    highest = int(session.scalar(select(func.max(WorkJob.id))) or 0)
    for kind in ("media_package-previews", "media_package-executions",
                 "media_organizer-executions"):
        highest = max(highest, _highest_report_id(root / kind))
    return highest + 1
