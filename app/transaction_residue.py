from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.models import QuarantineEntry
from app.tasks.recovery import renew_and_assert_worker_lease


_ENTRY_RE = re.compile(r"^entry-(\d+)$")


def _is_plain_dir(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _directory_only_tree(path: Path) -> list[Path] | None:
    """Return directories deepest-last when the tree contains directories only.

    Any file, symlink, socket or other object makes the tree ineligible. The
    caller may then leave the namespace untouched and fail closed.
    """
    if not _is_plain_dir(path):
        return None

    directories: list[Path] = []
    for current, dirnames, filenames in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        if not _is_plain_dir(current_path) or filenames:
            return None
        for dirname in dirnames:
            if not _is_plain_dir(current_path / dirname):
                return None
        directories.append(current_path)
    return list(reversed(directories))


def _entry_namespace_is_retired(
    session_factory: sessionmaker,
    entry_id: int,
) -> bool:
    """Only absent DB rows or durable terminal-purged rows may lose empty residue."""
    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            return True
        return entry.state == "purged" and entry.tx_phase == "purged"


def cleanup_empty_quarantine_tx_residue(
    session_factory: sessionmaker,
    quarantine_root: Path | str,
    *,
    worker_id: str,
) -> dict[str, int]:
    root = Path(quarantine_root) / ".tx"
    stats = {
        "removed_entry_namespaces": 0,
        "removed_directories": 0,
        "skipped_namespaces": 0,
    }
    try:
        children = list(root.iterdir())
    except FileNotFoundError:
        return stats
    except OSError:
        stats["skipped_namespaces"] += 1
        return stats

    if not _is_plain_dir(root):
        stats["skipped_namespaces"] += 1
        return stats

    for child in children:
        match = _ENTRY_RE.fullmatch(child.name)
        if not match:
            stats["skipped_namespaces"] += 1
            continue
        entry_id = int(match.group(1))
        if not _entry_namespace_is_retired(session_factory, entry_id):
            continue

        directories = _directory_only_tree(child)
        if directories is None:
            stats["skipped_namespaces"] += 1
            continue

        # Pattern-A fence immediately before the filesystem mutation batch.
        renew_and_assert_worker_lease(session_factory, worker_id)
        removed = 0
        try:
            for directory in directories:
                os.rmdir(directory)
                removed += 1
        except FileNotFoundError:
            # Another already-completed cleanup is harmless.
            pass
        except OSError:
            stats["skipped_namespaces"] += 1
            continue

        stats["removed_entry_namespaces"] += 1
        stats["removed_directories"] += removed

    try:
        renew_and_assert_worker_lease(session_factory, worker_id)
        root.rmdir()
    except (FileNotFoundError, OSError):
        pass
    return stats


def _read_completed_transplant_state(state_file: Path) -> dict[str, Any] | None:
    try:
        st = os.lstat(state_file)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return None

    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("phase") != "transplanted":
        return None

    source = raw.get("source")
    target = raw.get("target")
    created_dirs = raw.get("created_dirs")
    if (
        not isinstance(source, str)
        or not source
        or not isinstance(target, str)
        or not target
        or not isinstance(created_dirs, dict)
    ):
        return None

    root_identity = created_dirs.get("")
    if (
        not isinstance(root_identity, list)
        or len(root_identity) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in root_identity)
    ):
        return None

    # A completed directory transplant is only disposable once the source
    # pathname is gone and the exact target directory identity still matches.
    if os.path.lexists(source):
        return None
    try:
        target_stat = os.lstat(target)
    except OSError:
        return None
    if (
        not stat.S_ISDIR(target_stat.st_mode)
        or stat.S_ISLNK(target_stat.st_mode)
        or [int(target_stat.st_dev), int(target_stat.st_ino)]
        != [int(root_identity[0]), int(root_identity[1])]
    ):
        return None

    return raw


def cleanup_completed_utility_move_residue(
    session_factory: sessionmaker,
    quarantine_root: Path | str,
    *,
    worker_id: str,
) -> dict[str, int]:
    root = Path(quarantine_root) / ".utility-move-tx"
    stats = {
        "removed_transactions": 0,
        "removed_state_files": 0,
        "removed_directories": 0,
        "skipped_transactions": 0,
    }

    try:
        plan_dirs = list(root.iterdir())
    except FileNotFoundError:
        return stats
    except OSError:
        stats["skipped_transactions"] += 1
        return stats

    if not _is_plain_dir(root):
        stats["skipped_transactions"] += 1
        return stats

    for plan_dir in plan_dirs:
        if not _is_plain_dir(plan_dir):
            stats["skipped_transactions"] += 1
            continue
        try:
            item_dirs = list(plan_dir.iterdir())
        except OSError:
            stats["skipped_transactions"] += 1
            continue

        for item_dir in item_dirs:
            if not _is_plain_dir(item_dir):
                stats["skipped_transactions"] += 1
                continue
            try:
                members = list(item_dir.iterdir())
            except OSError:
                stats["skipped_transactions"] += 1
                continue

            if len(members) != 1 or members[0].name != "state.json":
                stats["skipped_transactions"] += 1
                continue

            state_file = members[0]
            if _read_completed_transplant_state(state_file) is None:
                stats["skipped_transactions"] += 1
                continue

            renew_and_assert_worker_lease(session_factory, worker_id)
            try:
                state_file.unlink()
                item_dir.rmdir()
            except (FileNotFoundError, OSError):
                stats["skipped_transactions"] += 1
                continue

            stats["removed_transactions"] += 1
            stats["removed_state_files"] += 1
            stats["removed_directories"] += 1

        try:
            renew_and_assert_worker_lease(session_factory, worker_id)
            plan_dir.rmdir()
            stats["removed_directories"] += 1
        except (FileNotFoundError, OSError):
            pass

    try:
        renew_and_assert_worker_lease(session_factory, worker_id)
        root.rmdir()
        stats["removed_directories"] += 1
    except (FileNotFoundError, OSError):
        pass
    return stats


def cleanup_transaction_residue(
    session_factory: sessionmaker,
    *,
    quarantine_root: Path | str,
    worker_id: str,
) -> dict[str, dict[str, int]]:
    """Best-effort, fail-closed cleanup of NFC-owned terminal transaction residue."""
    return {
        "quarantine_tx": cleanup_empty_quarantine_tx_residue(
            session_factory,
            quarantine_root,
            worker_id=worker_id,
        ),
        "utility_move_tx": cleanup_completed_utility_move_residue(
            session_factory,
            quarantine_root,
            worker_id=worker_id,
        ),
    }
