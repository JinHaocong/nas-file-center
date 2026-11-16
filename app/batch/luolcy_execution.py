"""Luolcy per-package execution engine: frozen manifest + fail-closed no-replace moves.

This module has no HTTP mutation API. Only a future Worker with a live lease
may call execute_manifest. A report snapshot is revalidated against a live
package before the manifest is written, and each individual file identity is
checked again at mutation time. Manifest persistence precedes every syscall.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Callable

from app.batch.file_rename import _open_directory_nofollow
from app.batch.luolcy_organizer import (
    MAX_FILES_PER_GROUP, _input_fingerprint, _package_path, _walk_package,
    preview_luolcy_package,
)
from app.fs_ops import rename_directory_noreplace_compat, rename_noreplace_at


class LuolcyExecutionConflict(ValueError):
    """A package cannot be safely executed without an operator reviewing it."""


MANIFEST_VERSION = 1


def _identity(st) -> list[int]:
    return [int(st.st_dev), int(st.st_ino), int(st.st_size), int(st.st_mtime_ns)]


def _open_folder(path: Path) -> int:
    return _open_directory_nofollow(path)


def _stat_entry(folder: Path, name: str):
    fd = _open_folder(folder)
    try:
        try:
            return os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
    finally:
        os.close(fd)


def _check_file(st, expected: list[int], path: Path) -> None:
    if (st is None or not stat.S_ISREG(st.st_mode)
            or _identity(st) != expected):
        raise LuolcyExecutionConflict(f"File changed or missing: {path}")


def _check_directory(st, path: Path, dev: int | None = None) -> None:
    if (st is None or not stat.S_ISDIR(st.st_mode)
            or (dev is not None and st.st_dev != dev)):
        raise LuolcyExecutionConflict(f"Unsafe destination directory: {path}")


def prepare_luolcy_manifest(package: Path, *, luolcy_root: Path,
                            allowed_roots: list[Path], quarantine_root: Path | None,
                            preview_record: dict, job_id: int) -> dict:
    """Freeze one ready package with full source identities and exact targets."""
    source = _package_path(package, luolcy_root, allowed_roots, quarantine_root)
    if preview_record.get("package") != str(source) or preview_record.get("status") != "ready":
        raise LuolcyExecutionConflict("Selected package was not ready in the preview")
    fresh = preview_luolcy_package(
        source, luolcy_root=luolcy_root, allowed_roots=allowed_roots,
        quarantine_root=quarantine_root,
    )
    if (fresh.get("status") != "ready"
            or not isinstance(preview_record.get("input_fingerprint"), str)
            or fresh["input_fingerprint"] != preview_record["input_fingerprint"]
            or fresh.get("needed_moves") != preview_record.get("needed_moves")
            or fresh.get("groups") != preview_record.get("groups")
            or fresh.get("operation") != preview_record.get("operation")):
        raise LuolcyExecutionConflict(f"Package changed since preview: {source}")

    items = list(_walk_package(source))
    if _input_fingerprint(items, source) != fresh["input_fingerprint"]:
        raise LuolcyExecutionConflict("Package changed while freezing its file manifest")
    package_stat = os.stat(source, follow_symlinks=False)
    _check_directory(package_stat, source)
    dev = int(package_stat.st_dev)
    for item in items:
        if item["dev"] != dev:
            raise LuolcyExecutionConflict("Cross-filesystem package cannot be moved safely")

    directories: dict[str, list[int]] = {}
    for item in items:
        parent = Path(item["path"]).parent
        while parent != source:
            if not parent.is_relative_to(source):
                raise LuolcyExecutionConflict("Source escaped protected package")
            key = str(parent)
            if key not in directories:
                fd = _open_folder(parent)
                try:
                    st = os.fstat(fd)
                finally:
                    os.close(fd)
                _check_directory(st, parent, dev)
                directories[key] = [int(st.st_dev), int(st.st_ino)]
            parent = parent.parent

    moves = []
    groups = []
    is_flat = fresh["operation"] == "flatten_pure_media"
    if is_flat:
        ordered = sorted(items, key=lambda row: (
            os.path.relpath(row["path"], source).casefold(),
            os.path.relpath(row["path"], source),
        ))
        for item in ordered:
            target = source / item["name"]
            if item["path"] != str(target):
                moves.append({
                    "source": item["path"], "target": str(target),
                    "final": str(target), "identity": [
                        item["dev"], item["ino"], item["bytes"], item["mtime_ns"],
                    ], "group": None,
                })
    else:
        items.sort(key=lambda row: (
            row["kind"], os.path.relpath(row["path"], source).casefold(),
            os.path.relpath(row["path"], source),
        ))
        for idx, group in enumerate(fresh["groups"]):
            kind = group["kind"]
            relevant = [item for item in items if item["kind"] == kind]
            group_number = len([prev for prev in fresh["groups"][:idx]
                                if prev["kind"] == kind])
            segment = (relevant[group_number * MAX_FILES_PER_GROUP:
                                (group_number + 1) * MAX_FILES_PER_GROUP]
                       if kind != "Other" else relevant)
            if not segment or len(segment) != group["count"] or sum(
                item["bytes"] for item in segment
            ) != group["bytes"]:
                raise LuolcyExecutionConflict("Proposed grouping changed during freeze")
            stage = f".nfc-luolcy-stage-{job_id}-{idx}"
            final = source / group["name"]
            groups.append({
                "stage": stage, "final": group["name"], "count": len(segment),
                "bytes": group["bytes"], "kind": kind,
            })
            for item in segment:
                target = source / stage / item["name"]
                if item["path"] == str(final / item["name"]):
                    # A ready package cannot rely on a preexisting ambiguous
                    # destination; only a fully organized package may be no-op.
                    raise LuolcyExecutionConflict("Unexpected source inside a final bucket")
                moves.append({
                    "source": item["path"], "target": str(target),
                    "final": str(final / item["name"]),
                    "identity": [item["dev"], item["ino"], item["bytes"], item["mtime_ns"]],
                    "group": idx,
                })

    if len(moves) != int(fresh["needed_moves"]):
        raise LuolcyExecutionConflict("Frozen move count differs from reviewed preview")
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "job_id": job_id, "package": str(source), "luolcy_root": str(luolcy_root),
        "package_dev": dev, "package_ino": int(package_stat.st_ino),
        "input_fingerprint": fresh["input_fingerprint"],
        "operation": fresh["operation"],
        "groups": groups, "moves": moves, "origin_directories": directories,
    }
    return manifest


def _manifest_checksum(manifest: dict) -> str:
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_frozen_manifest(path: Path, manifest: dict) -> None:
    """Exclusive, crash-safe publication on CONFIG_DIR; never overwrite."""
    if path.exists() or path.is_symlink():
        raise LuolcyExecutionConflict("Frozen manifest path already exists")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = path.with_name(path.name + ".tmp")
    if os.path.lexists(staging):
        raise LuolcyExecutionConflict("Untrusted partial manifest artifact exists")
    body = {"manifest": manifest, "checksum": _manifest_checksum(manifest)}
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path, follow_symlinks=False)
    finally:
        if os.path.lexists(staging):
            os.unlink(staging)


def load_frozen_manifest(path: Path, *, job_id: int, package: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise LuolcyExecutionConflict("Frozen manifest is missing or unsafe")
    with path.open("r", encoding="utf-8") as stream:
        body = json.load(stream)
    manifest = body.get("manifest")
    if (not isinstance(manifest, dict)
            or body.get("checksum") != _manifest_checksum(manifest)
            or manifest.get("schema_version") != MANIFEST_VERSION
            or manifest.get("job_id") != job_id
            or manifest.get("package") != str(package)):
        raise LuolcyExecutionConflict("Frozen manifest integrity mismatch")
    return manifest


def _entry(folder: Path, name: str):
    try:
        return _stat_entry(folder, name)
    except FileNotFoundError:
        return None


def _move_one(move: dict, *, lease_fence: Callable[[], None]) -> str:
    """Reconcile crashed no-clobber moves and perform at most one filesystem move."""
    src = Path(move["source"])
    stage = Path(move["target"])
    final = Path(move["final"])
    expected = move["identity"]
    # Published group may already have renamed staging -> final on crash.
    stage_stat = _entry(stage.parent, stage.name) if stage.parent.is_dir() else None
    final_stat = (_entry(final.parent, final.name)
                  if final != stage and final.parent.is_dir() else None)
    if stage_stat is not None and final_stat is not None:
        raise LuolcyExecutionConflict("Both staged and published file bindings exist")
    existing = final_stat if final_stat is not None else stage_stat
    if existing is not None:
        _check_file(existing, expected, final if final_stat else stage)
        src_stat = _entry(src.parent, src.name) if src.parent.is_dir() else None
        if src_stat is None:
            return "resumed"
        _check_file(src_stat, expected, src)
        # A COMPAT hardlink+unlink may have been interrupted after publication.
        lease_fence()
        fd = _open_folder(src.parent)
        try:
            live = os.stat(src.name, dir_fd=fd, follow_symlinks=False)
            _check_file(live, expected, src)
            os.unlink(src.name, dir_fd=fd)
        finally:
            os.close(fd)
        return "recovered_link"

    src_fd = _open_folder(src.parent)
    try:
        source_stat = os.stat(src.name, dir_fd=src_fd, follow_symlinks=False)
        _check_file(source_stat, expected, src)
        dst_fd = _open_folder(stage.parent)
        try:
            if os.fstat(dst_fd).st_dev != source_stat.st_dev:
                raise LuolcyExecutionConflict("Cross-filesystem move rejected")
            lease_fence()
            # Recheck immediately before mutation and rely on kernel NOREPLACE.
            _check_file(os.stat(src.name, dir_fd=src_fd, follow_symlinks=False),
                        expected, src)
            try:
                rename_noreplace_at(src_fd, src.name, dst_fd, stage.name)
            except OSError as exc:
                if exc.errno != errno.EOPNOTSUPP:
                    raise
                # Safe COMPAT fallback: hardlink publication with O_EXCL-like
                # semantics, then unlink the source only after checking inode.
                # A restart reconciles an interrupted two-name hardlink state.
                os.link(src.name, stage.name, src_dir_fd=src_fd,
                        dst_dir_fd=dst_fd, follow_symlinks=False)
                created = os.stat(stage.name, dir_fd=dst_fd, follow_symlinks=False)
                _check_file(created, expected, stage)
                _check_file(os.stat(src.name, dir_fd=src_fd, follow_symlinks=False),
                            expected, src)
                lease_fence()
                os.unlink(src.name, dir_fd=src_fd)
            _check_file(os.stat(stage.name, dir_fd=dst_fd, follow_symlinks=False),
                        expected, stage)
        finally:
            os.close(dst_fd)
    finally:
        os.close(src_fd)
    return "moved"


def _group_files(manifest: dict, group_index: int) -> list[dict]:
    return [item for item in manifest["moves"] if item["group"] == group_index]


def _verify_group_contents(manifest: dict, group_index: int, directory: Path) -> None:
    group = manifest["groups"][group_index]
    expected = {Path(row["final"]).name.casefold(): row["identity"]
                for row in _group_files(manifest, group_index)}
    if len(expected) != group["count"]:
        raise LuolcyExecutionConflict("Group filename collision in frozen manifest")
    fd = _open_folder(directory)
    try:
        seen = set()
        size = 0
        with os.scandir(fd) as entries:
            for entry in entries:
                folded = entry.name.casefold()
                if folded in seen or folded not in expected:
                    raise LuolcyExecutionConflict("Unrecognized file inside Luolcy stage/group")
                seen.add(folded)
                st = entry.stat(follow_symlinks=False)
                _check_file(st, expected[folded], directory / entry.name)
                size += int(st.st_size)
        if len(seen) != group["count"] or size != group["bytes"]:
            raise LuolcyExecutionConflict("Group count/size is incomplete")
    finally:
        os.close(fd)


def _ensure_staging(manifest: dict, group_index: int, lease_fence: Callable[[], None]) -> None:
    package = Path(manifest["package"])
    group = manifest["groups"][group_index]
    stage = package / group["stage"]
    final = package / group["final"]
    if final.exists() or final.is_symlink():
        if stage.exists() or stage.is_symlink():
            raise LuolcyExecutionConflict("Both staging and published directories exist")
        _verify_group_contents(manifest, group_index, final)
        return
    if stage.exists() or stage.is_symlink():
        fd = _open_folder(stage)
        try:
            _check_directory(os.fstat(fd), stage, manifest["package_dev"])
        finally:
            os.close(fd)
        return
    lease_fence()
    fd = _open_folder(package)
    try:
        os.mkdir(group["stage"], mode=0o755, dir_fd=fd)
    finally:
        os.close(fd)


def _publish_group(manifest: dict, group_index: int,
                   lease_fence: Callable[[], None]) -> str:
    package = Path(manifest["package"])
    group = manifest["groups"][group_index]
    stage = package / group["stage"]
    final = package / group["final"]
    if final.exists() or final.is_symlink():
        if stage.exists() or stage.is_symlink():
            raise LuolcyExecutionConflict("Published name and staging both exist")
        _verify_group_contents(manifest, group_index, final)
        return "already_published"
    _verify_group_contents(manifest, group_index, stage)
    lease_fence()
    fd = _open_folder(package)
    try:
        if os.fstat(fd).st_ino != manifest["package_ino"]:
            raise LuolcyExecutionConflict("Package directory changed before publish")
        try:
            rename_noreplace_at(fd, group["stage"], fd, group["final"])
        except OSError as exc:
            if exc.errno != errno.EOPNOTSUPP:
                raise
            # The project already supports a positively-probed directory-only
            # no-clobber fallback for NAS/FUSE filesystems.
            rename_directory_noreplace_compat(stage, final)
    finally:
        os.close(fd)
    _verify_group_contents(manifest, group_index, final)
    return "published"


def _remove_empty_sources(manifest: dict, lease_fence: Callable[[], None]) -> int:
    package = Path(manifest["package"])
    removed = 0
    for name, identity in sorted(manifest["origin_directories"].items(),
                                 key=lambda entry: (-len(Path(entry[0]).parts), entry[0])):
        folder = Path(name)
        if not folder.is_relative_to(package) or folder == package:
            raise LuolcyExecutionConflict("Unsafe original directory cleanup scope")
        if not folder.exists():
            continue
        if folder.is_symlink():
            raise LuolcyExecutionConflict("Original directory became a symlink")
        fd = _open_folder(folder)
        try:
            st = os.fstat(fd)
            if [int(st.st_dev), int(st.st_ino)] != identity:
                raise LuolcyExecutionConflict("Original directory replaced during cleanup")
        finally:
            os.close(fd)
        lease_fence()
        parent_fd = _open_folder(folder.parent)
        try:
            try:
                os.rmdir(folder.name, dir_fd=parent_fd)
                removed += 1
            except OSError as exc:
                if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise
        finally:
            os.close(parent_fd)
    return removed


def execute_frozen_manifest(manifest: dict, *, lease_fence: Callable[[], None],
                            progress: Callable[[int, int], None] | None = None) -> dict:
    """Run one package idempotently; the caller owns lease checkpoints/recovery."""
    package = Path(manifest["package"])
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise LuolcyExecutionConflict("Unsupported frozen manifest version")
    fd = _open_folder(package)
    try:
        st = os.fstat(fd)
        if st.st_dev != manifest["package_dev"] or st.st_ino != manifest["package_ino"]:
            raise LuolcyExecutionConflict("Protected resource package identity changed")
    finally:
        os.close(fd)
    for i in range(len(manifest["groups"])):
        _ensure_staging(manifest, i, lease_fence)
    completed = recovered = 0
    total = len(manifest["moves"])
    for index, row in enumerate(manifest["moves"], start=1):
        result = _move_one(row, lease_fence=lease_fence)
        completed += result == "moved"
        recovered += result != "moved"
        if progress and (index % 25 == 0 or index == total):
            progress(index, total)
    published = 0
    for i in range(len(manifest["groups"])):
        if _publish_group(manifest, i, lease_fence) == "published":
            published += 1
    cleaned = _remove_empty_sources(manifest, lease_fence)
    return {
        "files_moved": completed, "files_reconciled": recovered,
        "groups_published": published, "empty_dirs_removed": cleaned,
        "total_files": total, "package": str(package),
    }
