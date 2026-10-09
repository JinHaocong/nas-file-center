"""Bounded, read-only comparison of two directory trees.

This module never creates mutation Plans or follows symlinks. File size equality
is NOT content equality; exact SHA256 is an explicit, size-capped second action.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Iterable

from app.path_safety import require_allowed_path, require_unreserved_path


MAX_ENTRIES_PER_ROOT = 10_000
MAX_VERIFY_FILE_BYTES = 256 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_directory_absolute(path: Path) -> int:
    """Open every component without following symlinks, anchored at /."""
    if not path.is_absolute():
        raise ValueError("Comparison roots must be absolute directories")
    fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_directory_relative(root_fd: int, parts: tuple[str, ...]) -> int:
    fd = os.dup(root_fd)
    try:
        for part in parts:
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _validated_root(raw: str, allowed_roots: Iterable[Path | str], quarantine_root: Path | str | None) -> Path:
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        raise ValueError("Both comparison roots must be absolute paths")
    root = require_allowed_path(raw, allowed_roots)
    require_unreserved_path(root, quarantine_root)
    if not root.is_dir():
        raise ValueError(f"Comparison root does not exist or is not a directory: {root}")
    return root


def _is_reserved(path: Path, quarantine: Path | None) -> bool:
    return bool(quarantine and (path == quarantine or path.is_relative_to(quarantine)))


def _scan(root: Path, quarantine: Path | None) -> tuple[dict[str, dict[str, Any]], int]:
    """Descriptor-based DFS, bounded by total eligible entries per tree."""
    rows: dict[str, dict[str, Any]] = {}
    skipped_links = 0
    visited = 0
    root_fd = _open_directory_absolute(root)
    try:
        stack: list[tuple[str, ...]] = [()]
        while stack:
            components = stack.pop()
            fd = _open_directory_relative(root_fd, components)
            try:
                with os.scandir(fd) as entries:
                    for entry in entries:
                        visited += 1
                        if visited > MAX_ENTRIES_PER_ROOT:
                            raise ValueError(
                                f"Directory contains more than {MAX_ENTRIES_PER_ROOT} entries; "
                                "narrow the comparison roots"
                            )
                        rel_parts = components + (entry.name,)
                        rel = "/".join(rel_parts)
                        if _is_reserved(root.joinpath(*rel_parts), quarantine):
                            continue
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):
                            skipped_links += 1
                            continue
                        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                            continue
                        kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
                        rows[rel] = {
                            "kind": kind,
                            "size": int(info.st_size) if kind == "file" else None,
                        }
                        if kind == "directory":
                            stack.append(rel_parts)
            finally:
                os.close(fd)
    finally:
        os.close(root_fd)
    return rows, skipped_links


def compare_directories(
    root_a: str, root_b: str, *, allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None = None,
) -> dict[str, Any]:
    a = _validated_root(root_a, allowed_roots, quarantine_root)
    b = _validated_root(root_b, allowed_roots, quarantine_root)
    if a == b or a.is_relative_to(b) or b.is_relative_to(a):
        raise ValueError("Comparison roots must be distinct and non-overlapping")
    quarantine = Path(quarantine_root).resolve(strict=False) if quarantine_root else None
    a_items, a_links = _scan(a, quarantine)
    b_items, b_links = _scan(b, quarantine)

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for relative in sorted(a_items.keys() | b_items.keys()):
        left, right = a_items.get(relative), b_items.get(relative)
        if left is None:
            status = "only_b"
        elif right is None:
            status = "only_a"
        elif left["kind"] != right["kind"]:
            status = "type_mismatch"
        elif left["kind"] == "directory":
            status = "both_directories"
        elif left["size"] != right["size"]:
            status = "size_different"
        else:
            status = "same_size_unverified"
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            "relative_path": relative,
            "kind_a": left["kind"] if left else None,
            "kind_b": right["kind"] if right else None,
            "size_a": left["size"] if left else None,
            "size_b": right["size"] if right else None,
            "status": status,
        })
    return {
        "root_a": str(a), "root_b": str(b),
        "entries_a": len(a_items), "entries_b": len(b_items),
        "skipped_symlinks_a": a_links, "skipped_symlinks_b": b_links,
        "counts": counts, "items": rows, "total": len(rows),
    }


def _hash_regular(root: Path, relative: str) -> str:
    parts = relative.split("/")
    if not parts or any(p in {"", ".", ".."} or "\0" in p for p in parts):
        raise ValueError("Invalid relative file path")
    root_fd = _open_directory_absolute(root)
    try:
        parent_fd = _open_directory_relative(root_fd, tuple(parts[:-1]))
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("Exact verification only supports regular files")
                if before.st_size > MAX_VERIFY_FILE_BYTES:
                    raise ValueError(
                        f"File exceeds the on-demand SHA256 limit of {MAX_VERIFY_FILE_BYTES // (1024 * 1024)} MiB"
                    )
                digest = hashlib.sha256()
                while chunk := os.read(fd, _CHUNK_BYTES):
                    digest.update(chunk)
                after = os.fstat(fd)
                current = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                def identity(st: os.stat_result) -> tuple[int, ...]:
                    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
                if identity(before) != identity(after) or identity(after) != identity(current):
                    raise ValueError("File changed during SHA256 verification; please refresh")
                return digest.hexdigest()
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)
    finally:
        os.close(root_fd)


def verify_directory_pair(
    root_a: str, root_b: str, relative_path: str, *,
    allowed_roots: Iterable[Path | str], quarantine_root: Path | str | None = None,
) -> dict[str, Any]:
    a = _validated_root(root_a, allowed_roots, quarantine_root)
    b = _validated_root(root_b, allowed_roots, quarantine_root)
    if a == b or a.is_relative_to(b) or b.is_relative_to(a):
        raise ValueError("Comparison roots must be distinct and non-overlapping")
    if not isinstance(relative_path, str) or len(relative_path) > 4096:
        raise ValueError("Invalid relative path")
    parts = relative_path.split("/")
    if any(p in {"", ".", ".."} or "\0" in p for p in parts):
        raise ValueError("Invalid relative path")
    quarantine = Path(quarantine_root).resolve(strict=False) if quarantine_root else None
    if _is_reserved(a.joinpath(*parts), quarantine) or _is_reserved(b.joinpath(*parts), quarantine):
        raise ValueError("Quarantine content cannot be compared")
    sha_a = _hash_regular(a, relative_path)
    sha_b = _hash_regular(b, relative_path)
    return {
        "relative_path": relative_path, "sha256_a": sha_a, "sha256_b": sha_b,
        "same_content": sha_a == sha_b,
    }
