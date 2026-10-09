"""One-level, literal-only *regular file* rename preview.

No recursion, symlink traversal, directory renaming, or filesystem mutation.
Only an existing generic Rename Plan may subsequently execute approved rows.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Literal

from app.path_safety import (
    require_allowed_path,
    require_unreserved_path,
    validate_mutation_destination,
)

FileRenameMode = Literal["replace_name", "replace_suffix", "add_prefix", "add_suffix"]
MAX_IMMEDIATE_ENTRIES = 50_000
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_directory_nofollow(directory: Path) -> int:
    """Open the parent by directory descriptors; never follow a symlink."""
    if not directory.is_absolute():
        raise ValueError("Selected parent must be absolute")
    fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        for component in directory.parts[1:]:
            child_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _update_name(name: str, *, mode: FileRenameMode, find: str, value: str,
                 preserve_extension: bool) -> str:
    # The final extension only: '.env' has none; 'archive.tar.gz' preserves '.gz'.
    extension = Path(name).suffix if preserve_extension else ""
    stem = name[:-len(extension)] if extension else name

    if mode == "replace_name":
        changed = stem.replace(find, value)
    elif mode == "replace_suffix":
        changed = stem[:-len(find)] + value if stem.endswith(find) else stem
    elif mode == "add_prefix":
        changed = value + stem
    elif mode == "add_suffix":
        changed = stem + value
    else:
        raise ValueError("Unsupported file rename mode")
    return changed + extension


def preview_immediate_file_renames(
    parent: str | Path, *,
    mode: FileRenameMode,
    find: str = "",
    value: str = "",
    preserve_extension: bool = True,
    allowed_roots: list[str | Path],
    quarantine_root: str | Path | None = None,
) -> list[dict]:
    """Return rename proposals for direct regular files (never their descendants).

    Any already occupied target basename, including a casefold-equivalent name,
    is rejected. Execution still requires Freeze + Validate + Worker safety gates.
    """
    if mode not in {"replace_name", "replace_suffix", "add_prefix", "add_suffix"}:
        raise ValueError("Unsupported file rename mode")
    if mode.startswith("replace") and not find:
        raise ValueError("Literal search text must not be empty")
    if mode.startswith("add") and not value:
        raise ValueError("Content to add must not be empty")
    if not isinstance(preserve_extension, bool):
        raise ValueError("preserve_extension must be a boolean")
    if len(find) > 255 or len(value) > 255:
        raise ValueError("Search and replacement text must be at most 255 characters")

    raw_parent = Path(parent).expanduser()
    if not raw_parent.is_absolute() or raw_parent.is_symlink():
        raise ValueError("Selected parent must be an absolute non-symlink directory")
    safe_parent = require_unreserved_path(
        require_allowed_path(raw_parent, allowed_roots), quarantine_root
    )
    if not safe_parent.is_dir():
        raise ValueError("Selected parent directory does not exist")

    fd = _open_directory_nofollow(safe_parent)
    candidates: list[tuple[str, tuple[int, ...]]] = []
    existing_names: set[str] = set()
    try:
        with os.scandir(fd) as entries:
            seen = 0
            for entry in entries:
                seen += 1
                if seen > MAX_IMMEDIATE_ENTRIES:
                    raise ValueError(
                        f"Too many immediate entries (limit: {MAX_IMMEDIATE_ENTRIES})"
                    )
                existing_names.add(entry.name.casefold())
                st = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    continue
                identity = (int(st.st_dev), int(st.st_ino), int(st.st_size),
                            int(st.st_mtime_ns))
                candidates.append((entry.name, identity))
    finally:
        os.close(fd)

    candidates.sort(key=lambda pair: pair[0])
    results: list[dict] = []
    proposed_names: set[str] = set()
    for name, snapshot in candidates:
        updated_name = _update_name(
            name, mode=mode, find=find, value=value,
            preserve_extension=preserve_extension,
        )
        if updated_name == name:
            continue
        source = safe_parent / name
        target_text = str(safe_parent / updated_name)
        try:
            if updated_name in {"", ".", ".."} or any(c in updated_name for c in "/\\\0"):
                raise ValueError("Invalid file name after replacement")
            target = validate_mutation_destination(
                safe_parent / updated_name, allowed_roots,
                quarantine_root=quarantine_root,
            )
            if target.parent != safe_parent:
                raise ValueError("Rename must stay in the selected directory")
            folded = target.name.casefold()
            if folded in proposed_names or folded in existing_names:
                raise ValueError("Target name already exists or collides (case-insensitive)")
            # Read-only stale check; the Plan executor revalidates at execution.
            latest = os.lstat(source)
            latest_identity = (int(latest.st_dev), int(latest.st_ino),
                               int(latest.st_size), int(latest.st_mtime_ns))
            if not stat.S_ISREG(latest.st_mode) or latest_identity != snapshot:
                raise ValueError("Source file changed during preview")
            proposed_names.add(folded)
            results.append({
                "source": str(source), "target": str(target),
                "conflict": False, "conflict_reason": None,
            })
        except (ValueError, OSError) as exc:
            results.append({
                "source": str(source), "target": target_text,
                "conflict": True, "conflict_reason": str(exc),
            })
    return results
