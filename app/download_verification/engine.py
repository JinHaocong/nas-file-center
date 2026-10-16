"""Snapshot-bound read-only comparison; never treats same size as verified bytes."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Callable

from app.batch.directory_compare import _open_directory_absolute, _open_directory_relative
from app.path_safety import require_allowed_path, require_unreserved_path
from .webdav import WebDAVError, MAX_ENTRIES, CHUNK


class VerificationError(ValueError):
    pass


def qualified_local_root(raw: str, settings) -> Path:
    root = require_unreserved_path(
        require_allowed_path(raw, settings.allowed_roots), settings.quarantine_root
    )
    # Reject symlink components, including lexical root itself.
    fd = _open_directory_absolute(root)
    os.close(fd)
    return root


def local_manifest(root: Path, checkpoint: Callable[[], None] = lambda: None,\n                   quarantine_root: Path | None = None) -> dict[str, dict]:
    output: dict[str, dict] = {}
    root_fd = _open_directory_absolute(root)
    try:
        stack: list[tuple[str, ...]] = [()]
        while stack:
            parts = stack.pop()
            fd = _open_directory_relative(root_fd, parts)
            try:
                with os.scandir(fd) as entries:
                    for entry in entries:
                        path_parts = parts + (entry.name,)
                        name = "/".join(path_parts)\n                        if quarantine_root and (root.joinpath(*path_parts) == quarantine_root or\n                                root.joinpath(*path_parts).is_relative_to(quarantine_root)):\n                            raise VerificationError("RESERVED_LOCAL_OBJECT")
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode):
                            kind, size = "file", int(info.st_size)
                        elif stat.S_ISDIR(info.st_mode):
                            kind, size = "directory", None
                        else:
                            # No symlink or special object can disappear silently.
                            raise VerificationError("UNSUPPORTED_LOCAL_OBJECT")
                        if len(output) >= MAX_ENTRIES or name in output:
                            raise VerificationError("LOCAL_INVENTORY_LIMIT")
                        output[name] = {"kind": kind, "size": size,
                                        "identity": (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)}
                        if kind == "directory":
                            stack.append(path_parts)
                        if len(output) % 200 == 0:
                            checkpoint()
            finally:
                os.close(fd)
    finally:
        os.close(root_fd)
    return output


def hash_local_file(root: Path, relative: str, expected_size: int,
                    checkpoint: Callable[[], None] = lambda: None) -> str:
    parts = relative.split("/")
    if any(not p or p in (".", "..") for p in parts):
        raise VerificationError("INVALID_LOCAL_RELATIVE_PATH")
    root_fd = _open_directory_absolute(root)
    try:
        parent = _open_directory_relative(root_fd, tuple(parts[:-1]))
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=parent)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
                    raise VerificationError("LOCAL_CHANGED")
                identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                digest = hashlib.sha256()
                seen = 0
                while True:
                    block = os.read(fd, CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    seen += len(block)
                    if seen > expected_size:
                        raise VerificationError("LOCAL_CHANGED")
                    checkpoint()
                after = os.fstat(fd)
                final = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                # zfuse can change ctime on read: it is diagnostic only.
                if (identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    or identity != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
                    or not stat.S_ISREG(final.st_mode) or seen != expected_size):
                    raise VerificationError("LOCAL_CHANGED")
                return digest.hexdigest()
            finally:
                os.close(fd)
        finally:
            os.close(parent)
    finally:
        os.close(root_fd)


def diff_inventory(remote: dict[str, dict], local: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for name in sorted(set(remote) | set(local)):
        a, b = remote.get(name), local.get(name)
        if a is None:
            status = "ONLY_LOCAL"
        elif b is None:
            status = "ONLY_REMOTE"
        elif a["kind"] != b["kind"]:
            status = "TYPE_MISMATCH"
        elif a["kind"] == "file" and a["size"] != b["size"]:
            status = "SIZE_MISMATCH"
        elif a["kind"] == "directory":
            status = "DIRECTORY_MATCH"
        else:
            status = "PENDING_SHA256"
        rows.append({"relative_path": name,
                     "kind": (a or b)["kind"], "status": status,
                     "remote_size": a["size"] if a else None,
                     "local_size": b["size"] if b else None})
    return rows


def remote_fingerprint(manifest: dict[str, dict]) -> dict[str, tuple]:
    return {k: (v["kind"], v["size"], v.get("etag"), v.get("mtime"))
            for k, v in manifest.items()}


def local_fingerprint(manifest: dict[str, dict]) -> dict[str, tuple]:
    return {k: (v["kind"], v["size"], v["identity"])
            for k, v in manifest.items()}
