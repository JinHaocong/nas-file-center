"""Non-recursive, literal-only batch directory rename preview.

Preview performs no mutations. Execution uses the existing generic rename Plan
and WorkJob lifecycle rather than a second filesystem mutation pathway.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from app.path_safety import (
    is_reserved_quarantine_path,
    require_allowed_path,
    require_unreserved_path,
    validate_mutation_destination,
)

DirectoryRenameMode = Literal[
    "replace_name", "replace_suffix", "add_prefix", "add_suffix"
]

MAX_IMMEDIATE_DIRECTORIES = 50_000


def _rename_basename(name: str, *, mode: DirectoryRenameMode, find: str, value: str) -> str:
    if mode == "replace_name":
        if not find:
            raise ValueError("Literal search text is required")
        return name.replace(find, value)
    if mode == "replace_suffix":
        if not find:
            raise ValueError("Literal suffix to replace is required")
        return f"{name[:-len(find)]}{value}" if name.endswith(find) else name
    if mode == "add_prefix":
        if not value:
            raise ValueError("Prefix must not be empty")
        return f"{value}{name}"
    if mode == "add_suffix":
        if not value:
            raise ValueError("Suffix must not be empty")
        return f"{name}{value}"
    raise ValueError(f"Unsupported directory rename mode: {mode}")


def preview_immediate_directory_renames(
    parent: str | Path,
    *,
    mode: DirectoryRenameMode,
    find: str = "",
    value: str = "",
    allowed_roots: list[str | Path],
    quarantine_root: str | Path | None = None,
) -> list[dict]:
    """Preview renames of immediate real subdirectories only (no os.walk).

    The named parent itself is never renamed. Regular files, symlinks,
    descendants and reserved quarantine paths are ignored. Existing target
    names are always conflicts even if another candidate would move away.
    """
    if mode not in {"replace_name", "replace_suffix", "add_prefix", "add_suffix"}:
        raise ValueError("Unsupported directory rename mode")
    if mode.startswith("replace") and not find:
        raise ValueError("Literal search text must not be empty")
    if mode.startswith("add") and not value:
        raise ValueError("Content to add must not be empty")
    if len(find) > 255 or len(value) > 255:
        raise ValueError("Search and replacement text must be at most 255 characters")

    raw_parent = Path(parent).expanduser()
    if raw_parent.is_symlink():
        raise ValueError("Symlink directory cannot be used as the parent")
    safe_parent = require_unreserved_path(
        require_allowed_path(raw_parent, allowed_roots), quarantine_root
    )
    if not safe_parent.is_dir():
        raise ValueError("Selected parent directory does not exist")

    # scandir is intentionally a single-level, bounded enumeration.
    candidates: list[Path] = []
    with os.scandir(safe_parent) as entries:
        for entry in entries:
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            child = safe_parent / entry.name
            if is_reserved_quarantine_path(child, quarantine_root):
                continue
            if len(candidates) >= MAX_IMMEDIATE_DIRECTORIES:
                raise ValueError(
                    f"Too many immediate subdirectories (limit: {MAX_IMMEDIATE_DIRECTORIES})"
                )
            candidates.append(child)

    candidates.sort(key=lambda p: p.name)
    results: list[dict] = []
    targets: set[Path] = set()
    for source in candidates:
        updated_name = _rename_basename(source.name, mode=mode, find=find, value=value)
        if updated_name == source.name:
            continue

        try:
            if updated_name in {"", ".", ".."} or any(c in updated_name for c in "/\\\0"):
                raise ValueError("Invalid directory name after replacement")
            target = validate_mutation_destination(
                source.with_name(updated_name),
                allowed_roots,
                quarantine_root=quarantine_root,
            )
            if target.parent != safe_parent:
                raise ValueError("Rename must stay in the selected directory")
            if target in targets:
                raise ValueError("Multiple directories would receive the same name")
            if target.exists() or target.is_symlink():
                raise ValueError("Target already exists")
            if not source.is_dir() or source.is_symlink():
                raise ValueError("Source directory has changed")
            targets.add(target)
            results.append({
                "source": str(source), "target": str(target),
                "conflict": False, "conflict_reason": None,
            })
        except (ValueError, OSError) as exc:
            # An invalid proposed basename is still visible in the preview
            # but can never be promoted to a Plan from the UI.
            results.append({
                "source": str(source),
                "target": str(safe_parent / updated_name),
                "conflict": True,
                "conflict_reason": str(exc),
            })
    return results
