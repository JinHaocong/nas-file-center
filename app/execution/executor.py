from __future__ import annotations

import contextlib
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re
import stat
from typing import Iterable

from app.batch.plans import OperationItem
from app.execution.verifier import verify_duplicate_pair
from app.path_safety import UnsafePathError, is_reserved_quarantine_path, require_allowed_path


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
    if item.operation in {"unlink", "rmdir_empty"} and not allow_delete:
        return _skip("permanent deletion is disabled")
    if item.operation not in {"rename", "move", "touch", "quarantine", "unlink", "restore", "rmdir_empty", "mkdir_empty"}:
        return _skip(f"unsupported operation: {item.operation}")

    source_raw = Path(item.source)
    if source_raw.is_symlink():
        return _skip("symlink is not allowed")
    try:
        valid_roots = list(allowed_roots)
        if item.operation == "restore" and quarantine_root:
            valid_roots.append(Path(quarantine_root).resolve())
        source = require_allowed_path(source_raw, valid_roots)
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
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                from app.fs_ops import rename_noreplace
                rename_noreplace(source, target)
            except FileExistsError:
                return _skip("target already exists")
            except OSError as exc:
                return ItemResult("failed", str(exc))
            return ItemResult("completed", "moved", target)

        if item.operation == "restore":
            if item.target is None:
                return _skip("target is required for restore")
            target_raw = Path(item.target)
            if target_raw.is_symlink():
                return _skip("target symlink is not allowed")
            target = require_allowed_path(target_raw, allowed_roots)
            if is_reserved_quarantine_path(target, quarantine_root):
                return _skip("restore target cannot be within quarantine root")

            # Final pre-mutation integrity checks
            if item.expected_hash:
                from app.quarantine.paths import safe_quarantine_hash
                current_h = safe_quarantine_hash(source)
                if current_h != item.expected_hash:
                    return ItemResult("failed", f"Hash verification failed: Quarantined file hash mismatch (expected {item.expected_hash}, got {current_h})")
            if item.expected_size is not None and item.expected_size > 0:
                try:
                    st = source.stat(follow_symlinks=False)
                    if st.st_size != item.expected_size:
                        return ItemResult("failed", f"Quarantined file size mismatch (expected {item.expected_size}, got {st.st_size})")
                except OSError as exc:
                    return ItemResult("failed", f"Stat failed on quarantined source: {exc}")

            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                from app.fs_ops import rename_noreplace
                rename_noreplace(source, target)
            except FileExistsError:
                return _skip("target already exists")
            except OSError as exc:
                if exc.errno == errno.EXDEV:
                    return ItemResult("failed", "cross-filesystem restore is not supported")
                return ItemResult("failed", str(exc))
            return ItemResult("completed", "restored", target)

        if item.operation == "touch":
            target_mtime_ns = getattr(item, "target_mtime_ns", None) or getattr(item, "expected_mtime_ns", None)
            if target_mtime_ns and target_mtime_ns > 0:
                try:
                    st = source.stat(follow_symlinks=False)
                    atime_ns = getattr(st, "st_atime_ns", int(st.st_atime * 1e9))
                except OSError:
                    atime_ns = target_mtime_ns
                os.utime(source, ns=(atime_ns, target_mtime_ns), follow_symlinks=False)
            else:
                os.utime(source, None, follow_symlinks=False)
            return ItemResult("completed", "mtime refreshed", source)

        if item.operation == "quarantine":
            if item.target is not None:
                target_raw = Path(item.target)
                if target_raw.is_symlink():
                    return _skip("target symlink is not allowed")
                target = target_raw.resolve(strict=False)
                require_allowed_path(target, allowed_roots)
                if not is_reserved_quarantine_path(target, quarantine_root):
                    return _skip("quarantine target must be within quarantine root")
            else:
                quarantine = require_allowed_path(quarantine_root, allowed_roots)
                target = _quarantine_target(source, allowed_roots=allowed_roots, quarantine_root=quarantine, plan_id=plan_id)
                require_allowed_path(target, allowed_roots)

            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                from app.fs_ops import rename_noreplace
                rename_noreplace(source, target)
            except FileExistsError:
                return _skip("quarantine target already exists")
            except OSError as exc:
                if exc.errno == errno.EXDEV:
                    return ItemResult("failed", "cross-filesystem quarantine is not supported")
                return ItemResult("failed", str(exc))
            return ItemResult("completed", "quarantined", target)

        if item.operation == "rmdir_empty":
            if quarantine_root and is_reserved_quarantine_path(source, quarantine_root):
                return _skip("source is in reserved quarantine storage")
            if source.is_symlink() or os.path.islink(source) or not source.is_dir():
                return _skip("source is not a directory")
            if item.expected_device or item.expected_inode:
                try:
                    st = os.lstat(source)
                    if (item.expected_device and st.st_dev != item.expected_device) or (item.expected_inode and st.st_ino != item.expected_inode):
                        return _skip("source identity changed")
                except OSError as exc:
                    return _skip(f"stat failed: {exc}")

            match = _containing_root(source, allowed_roots)
            if match is None:
                return _skip("source is outside configured roots")
            _, base_root = match
            rel_to_root = source.relative_to(base_root)
            if len(rel_to_root.parts) == 0:
                return _skip("cannot remove allowed root directory")

            leaf_name = rel_to_root.parts[-1]
            parent_parts = rel_to_root.parts[:-1]

            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW

            with contextlib.ExitStack() as stack:
                try:
                    curr_fd = os.open(str(base_root), flags)
                    stack.callback(os.close, curr_fd)
                    for comp in parent_parts:
                        next_fd = os.open(comp, flags, dir_fd=curr_fd)
                        stack.callback(os.close, next_fd)
                        curr_fd = next_fd
                except OSError as exc:
                    return _skip(f"failed to safely access directory path: {exc}")

                try:
                    st_leaf = os.stat(leaf_name, dir_fd=curr_fd, follow_symlinks=False)
                except OSError as exc:
                    return _skip(f"stat failed: {exc}")

                if stat.S_ISLNK(st_leaf.st_mode) or not stat.S_ISDIR(st_leaf.st_mode):
                    return _skip("source is not a directory")

                if (item.expected_device and st_leaf.st_dev != item.expected_device) or (
                    item.expected_inode and st_leaf.st_ino != item.expected_inode
                ):
                    return _skip("source identity changed")

                try:
                    os.rmdir(leaf_name, dir_fd=curr_fd)
                except OSError as exc:
                    return ItemResult("failed", str(exc))
                return ItemResult("completed", "empty directory removed", source)

        if item.operation == "mkdir_empty":
            if item.target is None:
                return _skip("target is required for mkdir_empty")
            target_raw = Path(item.target)
            if target_raw.is_symlink() or os.path.lexists(target_raw):
                return _skip("target already exists")
            try:
                rel = target_raw.relative_to(source)
                if str(rel) in ("", "."):
                    return _skip("target must be strict descendant of anchor")
            except Exception:
                return _skip("target is not descendant of anchor")
            parent = target_raw.parent
            if parent.is_symlink() or not parent.exists() or not parent.is_dir():
                return _skip("target parent is missing or not a directory")
            target = require_allowed_path(target_raw, allowed_roots)
            if quarantine_root and (
                is_reserved_quarantine_path(target, quarantine_root)
                or is_reserved_quarantine_path(source, quarantine_root)
                or is_reserved_quarantine_path(parent, quarantine_root)
            ):
                return _skip("path is in reserved quarantine storage")
            if item.expected_device or item.expected_inode:
                try:
                    st = os.lstat(source)
                    if (item.expected_device and st.st_dev != item.expected_device) or (item.expected_inode and st.st_ino != item.expected_inode):
                        return _skip("anchor identity changed")
                except OSError as exc:
                    return _skip(f"stat failed: {exc}")

            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW

            with contextlib.ExitStack() as stack:
                try:
                    anchor_fd = os.open(str(source), flags)
                    stack.callback(os.close, anchor_fd)
                except OSError as exc:
                    return _skip(f"failed to open anchor directory: {exc}")

                try:
                    st_anchor = os.fstat(anchor_fd)
                except OSError as exc:
                    return _skip(f"stat failed on anchor: {exc}")

                if not stat.S_ISDIR(st_anchor.st_mode):
                    return _skip("anchor is not a directory")
                if (item.expected_device and st_anchor.st_dev != item.expected_device) or (
                    item.expected_inode and st_anchor.st_ino != item.expected_inode
                ):
                    return _skip("anchor identity changed")

                rel_to_anchor = target_raw.relative_to(source)
                parent_parts = rel_to_anchor.parts[:-1]
                leaf_name = rel_to_anchor.parts[-1]

                curr_fd = anchor_fd
                for comp in parent_parts:
                    try:
                        next_fd = os.open(comp, flags, dir_fd=curr_fd)
                        stack.callback(os.close, next_fd)
                        curr_fd = next_fd
                    except OSError:
                        return _skip("target parent is missing or not a directory")

                try:
                    os.stat(leaf_name, dir_fd=curr_fd, follow_symlinks=False)
                    return _skip("target already exists")
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    if exc.errno == errno.ENOENT:
                        pass
                    else:
                        return ItemResult("failed", str(exc))

                try:
                    os.mkdir(leaf_name, dir_fd=curr_fd)
                except OSError as exc:
                    return ItemResult("failed", str(exc))

                return ItemResult("completed", "empty directory created", target)

        if item.operation == "unlink":
            os.unlink(source)
            return ItemResult("completed", "unlinked")

        return _skip(f"unsupported operation: {item.operation}")
    except (OSError, UnsafePathError) as exc:
        return ItemResult("failed", str(exc))
