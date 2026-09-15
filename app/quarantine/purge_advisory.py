from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IndexedPath, IndexRoot


ADVISORY_SCOPE = "indexed_roots_only"


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
    """Return read-only indexed-scope evidence about surviving hard links.

    Database rows are candidates only. A path is reported as a survivor only
    after it is confirmed to be inside a currently configured IndexRoot and a
    live lstat proves the exact selected (device, inode). Mutation authority is
    never derived from this advisory result.
    """
    roots = sorted(
        (_absolute_lexical(root) for root in session.scalars(select(IndexRoot.root)).all()),
        key=str,
    )
    excluded_paths = {
        str(_absolute_lexical(item.get("path", "")))
        for item in manifest.get("owned_paths", [])
        if isinstance(item, dict) and item.get("path")
    }

    hardlink_survivors: list[str] = []
    stale_candidates: list[str] = []
    out_of_scope_candidates: list[str] = []

    if not roots:
        return {
            "scope": ADVISORY_SCOPE,
            "status": "incomplete",
            "hardlink_survivors": [],
            "stale_candidates": [],
            "out_of_scope_candidates": [],
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
        except OSError:
            stale_candidates.append(path_text)
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

    return {
        "scope": ADVISORY_SCOPE,
        "status": "verified_found" if hardlink_survivors else "verified_none",
        "hardlink_survivors": hardlink_survivors,
        "stale_candidates": stale_candidates,
        "out_of_scope_candidates": out_of_scope_candidates,
        "diagnostics": [],
    }
