from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable, Sequence

from app.path_safety import (
    UnsafePathError,
    is_reserved_quarantine_path,
    require_unreserved_path,
)

__all__ = [
    "get_containing_root_slot",
    "build_quarantine_target_path",
    "build_restore_rename_path",
    "is_reserved_quarantine_path",
    "require_unreserved_path",
    "safe_quarantine_hash",
]


def get_containing_root_slot(
    file_path: Path | str,
    allowed_roots: Sequence[Path | str],
) -> tuple[int, Path]:
    """
    Find the matching root slot for a given file_path.
    Applies Rule 22: if multiple allowed_roots contain the path,
    the most specific root (longest prefix match / longest parts) is selected.
    Returns (slot_index, resolved_root).
    Raises UnsafePathError if path is outside all allowed_roots.
    """
    path_obj = Path(file_path).resolve(strict=False)
    matches: list[tuple[int, Path, int]] = []

    for idx, r in enumerate(allowed_roots):
        resolved_root = Path(r).resolve(strict=False)
        try:
            path_obj.relative_to(resolved_root)
            matches.append((idx, resolved_root, len(resolved_root.parts)))
        except ValueError:
            continue

    if not matches:
        raise UnsafePathError(f"Path '{file_path}' is outside allowed roots")

    # Sort primarily by root prefix length descending (longest first),
    # secondarily by slot index ascending
    matches.sort(key=lambda m: (-m[2], m[0]))
    best_slot, best_root, _ = matches[0]
    return best_slot, best_root


def build_quarantine_target_path(
    source: Path | str,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
    plan_id: str | int,
    entry_id: int,
    check_symlink: bool = False,
) -> Path:
    """
    Construct the pre-allocated quarantine target path:
    <QUARANTINE_ROOT>/plan-<plan_id>/root-<slot>/<relative_parent>/<stem>.q-<entry_id><suffix>
    """
    source_p = Path(source)
    quarantine_raw = Path(quarantine_root)

    if check_symlink:
        if source_p.is_symlink() or os.path.islink(source_p):
            raise ValueError(f"Symlinks are not permitted in quarantine: {source}")
        if quarantine_raw.is_symlink() or os.path.islink(quarantine_raw):
            raise ValueError(f"Quarantine root is a symlink: {quarantine_root}")

    quarantine_p = quarantine_raw.resolve(strict=False)

    slot, root = get_containing_root_slot(source_p, allowed_roots)
    resolved_source = source_p.resolve(strict=False)

    try:
        rel_parent = resolved_source.parent.relative_to(root)
    except ValueError:
        rel_parent = Path("")

    stem = source_p.stem
    suffix = source_p.suffix
    target_name = f"{stem}.q-{entry_id}{suffix}"

    target_rel = Path(f"plan-{plan_id}") / f"root-{slot}" / rel_parent / target_name
    return (quarantine_p / target_rel).resolve(strict=False)


def build_restore_rename_path(
    original_path: Path | str,
    entry_id: int,
    existing_check: Callable[[Path], bool] | None = None,
    max_attempts: int = 100,
) -> Path:
    """
    Construct a non-colliding destination path for restore rename:
    1st choice: <parent>/<stem>.restored-<entry_id><suffix>
    nth choice: <parent>/<stem>.restored-<entry_id>-<n><suffix>
    """
    orig_p = Path(original_path)
    parent = orig_p.parent
    stem = orig_p.stem
    suffix = orig_p.suffix

    check = existing_check or (lambda p: p.exists() or os.path.islink(p))

    candidate = parent / f"{stem}.restored-{entry_id}{suffix}"
    if not check(candidate):
        return candidate

    for i in range(1, max_attempts + 1):
        candidate = parent / f"{stem}.restored-{entry_id}-{i}{suffix}"
        if not check(candidate):
            return candidate

    raise RuntimeError(
        f"Could not find an unused restore rename path for {original_path} after {max_attempts} attempts"
    )


def safe_quarantine_hash(file_path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    """
    Calculate SHA256 hash using streaming chunks (default 1MiB)
    to avoid high memory consumption for large files.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
