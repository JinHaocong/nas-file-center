from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from app.exceptions import StateConflictError
from app.models import QuarantineEntry
from app.path_safety import validate_mutation_destination
from app.quarantine.paths import safe_quarantine_hash


def validate_quarantine_for_restore(
    entry: QuarantineEntry,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
    custom_target: str | None = None,
    conflict_policy: str = "skip",
) -> tuple[Path, Path]:
    """
    Validate that a QuarantineEntry is eligible for restore.
    Checks:
    - entry.state == "active"
    - quarantined file exists
    - quarantined file is not a symlink
    - content hash matches (if entry.content_hash is set)
    - file size matches (if entry.size is set)
    - destination path is valid under allowed_roots and not in quarantine_root

    Mutates entry.state and entry.last_error on inconsistency before raising.
    Returns (quarantine_target_path, destination_path).
    """
    if entry.state != "active":
        raise StateConflictError(f"Cannot restore quarantine entry in state '{entry.state}'")

    target = Path(entry.quarantine_path)
    if not target.exists():
        entry.state = "inconsistent"
        entry.last_error = f"Quarantined target file does not exist: {target}"
        raise StateConflictError(f"Quarantined target file does not exist: {target}")

    if target.is_symlink() or os.path.islink(target):
        entry.state = "inconsistent"
        entry.last_error = "Quarantined target file is a symlink"
        raise ValueError("Quarantined target is a symlink, restore aborted")

    if entry.size is not None and entry.size > 0:
        try:
            st = target.stat(follow_symlinks=False)
            if st.st_size != entry.size:
                entry.state = "inconsistent"
                entry.last_error = f"Size verification failed: expected {entry.size}, got {st.st_size}"
                raise ValueError(f"Quarantined file size mismatch (expected {entry.size}, got {st.st_size})")
        except OSError as exc:
            entry.state = "inconsistent"
            entry.last_error = f"Stat failed on quarantined file: {exc}"
            raise ValueError(f"Stat failed on quarantined file: {exc}")

    if entry.content_hash:
        current_hash = safe_quarantine_hash(target)
        if current_hash != entry.content_hash:
            entry.state = "inconsistent"
            entry.last_error = f"Hash verification failed: expected {entry.content_hash}, got {current_hash}"
            raise ValueError(f"Quarantined file hash mismatch (expected {entry.content_hash}, got {current_hash})")

    # Determine destination path
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
