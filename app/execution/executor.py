from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Iterable

from app.batch.plans import OperationItem
from app.execution.verifier import verify_duplicate_pair
from app.path_safety import UnsafePathError, require_allowed_path


@dataclass(frozen=True)
class ItemResult:
    state: str
    reason: str
    result_path: Path | None = None


def _skip(reason: str) -> ItemResult:
    return ItemResult("skipped", reason)


def _count_regular_files(root: Path) -> int:
    count = 0
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames[:] = [d for d in dirnames if not (current_path / d).is_symlink()]
        for name in filenames:
            p = current_path / name
            if not p.is_symlink() and p.is_file():
                count += 1
    return count


def _containing_root(path: Path, roots: Iterable[Path | str]) -> tuple[int, Path] | None:
    resolved_roots = [Path(r).expanduser().resolve(strict=False) for r in roots]
    matches = [(i, r) for i, r in enumerate(resolved_roots) if path == r or path.is_relative_to(r)]
    if not matches:
        return None
    return max(matches, key=lambda pair: len(pair[1].parts))


def _safe_plan_id(plan_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", plan_id) or "plan"


def _quarantine_target(source: Path, *, allowed_roots: Iterable[Path | str], quarantine_root: Path, plan_id: str) -> Path:
    match = _containing_root(source, allowed_roots)
    if match is None:
        raise UnsafePathError(f"Path is outside configured roots: {source}")
    index, root = match
    relative = source.relative_to(root)
    return quarantine_root / _safe_plan_id(plan_id) / f"root-{index}" / relative


def execute_item(
    item: OperationItem,
    *,
    allowed_roots: Iterable[Path | str],
    allow_mutation: bool,
    allow_delete: bool,
    quarantine_root: Path | str,
    plan_id: str,
) -> ItemResult:
    if item.state == "completed":
        return ItemResult("completed", "already completed")
    if not allow_mutation:
        return _skip("filesystem mutation is disabled")
    if item.operation == "unlink" and not allow_delete:
        return _skip("permanent deletion is disabled")
    if item.operation not in {"rename", "move", "touch", "quarantine", "unlink"}:
        return _skip(f"unsupported operation: {item.operation}")

    source_raw = Path(item.source)
    if source_raw.is_symlink():
        return _skip("symlink is not allowed")
    try:
        source = require_allowed_path(source_raw, allowed_roots)
    except UnsafePathError as exc:
        return _skip(str(exc))
    if not source.exists():
        return _skip("source does not exist")

    if item.expected_size and source.is_file():
        try:
            if source.stat(follow_symlinks=False).st_size != item.expected_size:
                return _skip("source size changed")
        except OSError as exc:
            return _skip(f"stat failed: {exc}")

    if item.protected_dir is not None and item.operation in {"quarantine", "unlink"}:
        protected = Path(item.protected_dir)
        try:
            protected = require_allowed_path(protected, allowed_roots)
        except UnsafePathError as exc:
            return _skip(str(exc))
        if source.is_relative_to(protected) and _count_regular_files(protected) <= 1:
            return _skip("protected directory last file")

    if item.keep is not None and item.operation in {"quarantine", "unlink"}:
        verified = verify_duplicate_pair(
            item.keep,
            source,
            allowed_roots=allowed_roots,
            expected_size=item.expected_size,
            expected_hash=item.expected_hash,
        )
        if not verified.ok:
            return _skip(verified.reason)

    try:
        if item.operation in {"rename", "move"}:
            if item.target is None:
                return _skip("target is required")
            target_raw = Path(item.target)
            if target_raw.is_symlink():
                return _skip("target symlink is not allowed")
            target = require_allowed_path(target_raw, allowed_roots)
            if target.exists():
                return _skip("target already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            return ItemResult("completed", "moved", target)

        if item.operation == "touch":
            os.utime(source, None, follow_symlinks=False)
            return ItemResult("completed", "mtime refreshed", source)

        if item.operation == "quarantine":
            quarantine = require_allowed_path(quarantine_root, allowed_roots)
            target = _quarantine_target(source, allowed_roots=allowed_roots, quarantine_root=quarantine, plan_id=plan_id)
            require_allowed_path(target, allowed_roots)
            if target.exists():
                return _skip("quarantine target already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            return ItemResult("completed", "quarantined", target)

        os.unlink(source)
        return ItemResult("completed", "unlinked")
    except (OSError, UnsafePathError) as exc:
        return ItemResult("failed", str(exc))
