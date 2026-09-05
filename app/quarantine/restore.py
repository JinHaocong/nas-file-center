from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from app.exceptions import StateConflictError
from app.models import QuarantineEntry
from app.path_safety import validate_mutation_destination
from app.quarantine.paths import safe_quarantine_hash


def validate_restore_destination_intent(
    entry: QuarantineEntry,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
    custom_target: str | None = None,
    conflict_policy: str = "skip",
) -> tuple[Path, Path]:
    """
    Fast validation of DB state and destination path intent without reading or hashing
    quarantine content. Safe to run inside short DB transactions.
    """
    if entry.state != "active":
        raise StateConflictError(f"Cannot restore quarantine entry in state '{entry.state}'")

    target = Path(entry.quarantine_path)
    if not target.exists():
        entry.state = "inconsistent"
        entry.last_error = f"Quarantined target file does not exist: {target}"
        raise StateConflictError(f"Quarantined target file does not exist: {target}")

    if conflict_policy == "manual":
        if not custom_target or not custom_target.strip():
            raise ValueError("custom_target is required when conflict_policy is 'manual'")
        dest = validate_mutation_destination(
            custom_target.strip(),
            allowed_roots,
            quarantine_root=quarantine_root,
        )
    else:
        dest = validate_mutation_destination(
            entry.original_path,
            allowed_roots,
            quarantine_root=quarantine_root,
        )

    return target, dest


def verify_quarantine_source_integrity(
    target: Path,
    expected_size: int | None = None,
    expected_hash: str | None = None,
) -> dict:
    """
    Verify quarantine source file existence, symlink-safety, size and content hash.
    MUST run outside SQLite write transactions.
    Returns verified stat dictionary snapshot.
    """
    target = Path(target)
    if not target.exists():
        raise StateConflictError(f"Quarantined target file does not exist: {target}")

    if target.is_symlink() or os.path.islink(target):
        raise ValueError("Quarantined target is a symlink, restore aborted")

    try:
        st = target.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"Stat failed on quarantined file: {exc}")

    if expected_size is not None and expected_size > 0:
        if st.st_size != expected_size:
            raise ValueError(f"Quarantined file size mismatch (expected {expected_size}, got {st.st_size})")

    if expected_hash:
        current_hash = safe_quarantine_hash(target)
        if current_hash != expected_hash:
            raise ValueError(f"Hash verification failed: Quarantined file hash mismatch (expected {expected_hash}, got {current_hash})")

    return {
        "object_type": "file",
        "size": st.st_size,
        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        "device": getattr(st, "st_dev", 0),
        "inode": getattr(st, "st_ino", 0),
    }


def assert_source_unmodified(target: Path, verified_stat: dict) -> None:
    """
    Immediate pre-mutation fence check: verify that device, inode, size, and mtime
    have not changed since the source integrity was verified.
    """
    target = Path(target)
    try:
        st = target.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"Stat failed on quarantined source before mutation: {exc}")

    if verified_stat.get("device") is not None and getattr(st, "st_dev", 0) != verified_stat["device"]:
        raise ValueError("Quarantined source device modified before mutation")
    if verified_stat.get("inode") is not None and getattr(st, "st_ino", 0) != verified_stat["inode"]:
        raise ValueError("Quarantined source inode modified before mutation")
    if verified_stat.get("size") is not None and st.st_size != verified_stat["size"]:
        raise ValueError(f"Quarantined source size modified before mutation (expected {verified_stat['size']}, got {st.st_size})")
    if verified_stat.get("mtime_ns") is not None and getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)) != verified_stat["mtime_ns"]:
        raise ValueError("Quarantined source mtime modified before mutation")


def validate_quarantine_for_restore(
    entry: QuarantineEntry,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
    custom_target: str | None = None,
    conflict_policy: str = "skip",
) -> tuple[Path, Path]:
    """
    Composite validation that checks both intent and content integrity.
    Mutates entry.state and entry.last_error on inconsistency before raising.
    Returns (quarantine_target_path, destination_path).
    """
    try:
        target, dest = validate_restore_destination_intent(
            entry,
            allowed_roots=allowed_roots,
            quarantine_root=quarantine_root,
            custom_target=custom_target,
            conflict_policy=conflict_policy,
        )
        verify_quarantine_source_integrity(target, entry.size, entry.content_hash)
        return target, dest
    except (StateConflictError, ValueError) as exc:
        entry.state = "inconsistent"
        entry.last_error = str(exc)
        raise
