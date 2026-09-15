from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import DuplicateFile, DuplicateGroup, IndexedPath, IndexRoot


ADVISORY_SCOPE = "indexed_roots_only"
SAME_CONTENT_SCOPE = "duplicate_scan_index"


def _absolute_lexical(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def discover_unlink_purge_advisory(
    session: Session,
    entry: Any,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return read-only indexed-scope evidence about purge survivors/copies.

    IndexedPath rows are candidates only. A path is reported as a hard-link
    survivor only after it is confirmed inside a current IndexRoot and a live
    lstat proves the exact selected (device, inode).

    Same-content/different-inode copies are reported separately from duplicate
    scan/index data. That section is informational and may be stale; it is never
    mutation authority and never upgrades a path into the hard-link section.
    """
    try:
        roots = sorted(
            (
                _absolute_lexical(root)
                for root in session.scalars(select(IndexRoot.root)).all()
            ),
            key=str,
        )
    except SQLAlchemyError:
        return {
            "scope": ADVISORY_SCOPE,
            "status": "incomplete",
            "hardlink_survivors": [],
            "stale_candidates": [],
            "out_of_scope_candidates": [],
            "same_content_scope": SAME_CONTENT_SCOPE,
            "same_content_status": "scan_index_unavailable",
            "same_content_independent_copies": [],
            "diagnostics": ["ADVISORY_DB_READ_FAILED"],
        }

    excluded_paths = {
        str(_absolute_lexical(item.get("path", "")))
        for item in manifest.get("owned_paths", [])
        if isinstance(item, dict) and item.get("path")
    }

    hardlink_survivors: list[str] = []
    stale_candidates: list[str] = []
    out_of_scope_candidates: list[str] = []
    same_content_independent_copies: list[str] = []
    diagnostics: list[str] = []

    if not roots:
        return {
            "scope": ADVISORY_SCOPE,
            "status": "incomplete",
            "hardlink_survivors": [],
            "stale_candidates": [],
            "out_of_scope_candidates": [],
            "same_content_scope": SAME_CONTENT_SCOPE,
            "same_content_status": "scan_index_unavailable",
            "same_content_independent_copies": [],
            "diagnostics": ["NO_INDEX_ROOTS"],
        }

    candidates = session.scalars(
        select(IndexedPath)
        .where(IndexedPath.device == entry.device)
        .where(IndexedPath.inode == entry.inode)
        .order_by(IndexedPath.absolute_path)
    ).all()

    for candidate in candidates:
        path = _absolute_lexical(candidate.absolute_path)
        path_text = str(path)

        if path_text in excluded_paths:
            continue
        if not any(_is_within(path, root) for root in roots):
            out_of_scope_candidates.append(path_text)
            continue

        try:
            st = os.lstat(path)
        except FileNotFoundError:
            stale_candidates.append(path_text)
            continue
        except OSError:
            diagnostics.append(f"LIVE_LSTAT_FAILED:{path_text}")
            continue

        if not stat.S_ISREG(st.st_mode):
            stale_candidates.append(path_text)
            continue

        if st.st_dev != entry.device or st.st_ino != entry.inode:
            stale_candidates.append(path_text)
            continue

        hardlink_survivors.append(path_text)

    hardlink_survivors = sorted(set(hardlink_survivors))
    stale_candidates = sorted(set(stale_candidates))
    out_of_scope_candidates = sorted(set(out_of_scope_candidates))
    diagnostics = sorted(set(diagnostics))

    same_content_status = "scan_index_unavailable"
    if entry.content_hash:
        copy_candidates = session.scalars(
            select(DuplicateFile)
            .join(DuplicateGroup, DuplicateFile.group_id == DuplicateGroup.id)
            .where(DuplicateGroup.content_hash == entry.content_hash)
            .order_by(DuplicateFile.absolute_path)
        ).all()

        for candidate in copy_candidates:
            path = _absolute_lexical(candidate.absolute_path)
            path_text = str(path)

            if path_text in excluded_paths:
                continue
            if not any(_is_within(path, root) for root in roots):
                continue
            if (candidate.device, candidate.inode) == (entry.device, entry.inode):
                continue

            same_content_independent_copies.append(path_text)

        same_content_independent_copies = sorted(set(same_content_independent_copies))
        same_content_status = (
            "scan_index_found" if same_content_independent_copies else "scan_index_none"
        )

    hardlink_status = (
        "incomplete"
        if diagnostics
        else ("verified_found" if hardlink_survivors else "verified_none")
    )

    return {
        "scope": ADVISORY_SCOPE,
        "status": hardlink_status,
        "hardlink_survivors": hardlink_survivors,
        "stale_candidates": stale_candidates,
        "out_of_scope_candidates": out_of_scope_candidates,
        "same_content_scope": SAME_CONTENT_SCOPE,
        "same_content_status": same_content_status,
        "same_content_independent_copies": same_content_independent_copies,
        "diagnostics": diagnostics,
    }
