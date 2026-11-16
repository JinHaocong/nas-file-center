"""MediaPackage per-package execution engine: frozen manifest + fail-closed no-replace moves.

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
from app.batch.media_package_naming import allocate_names
from app.batch.media_package_organizer import (
    MAX_FILES_PER_GROUP, _input_fingerprint, _package_path, _walk_package,
    preview_media_package_package,
)
from app.fs_ops import rename_directory_noreplace_compat, rename_noreplace_at


class MediaPackageExecutionConflict(ValueError):
    """A package cannot be safely executed without an operator reviewing it."""


MANIFEST_VERSION = 2


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
        raise MediaPackageExecutionConflict(f"File changed or missing: {path}")


def _check_directory(st, path: Path, dev: int | None = None) -> None:
    if (st is None or not stat.S_ISDIR(st.st_mode)
            or (dev is not None and st.st_dev != dev)):
        raise MediaPackageExecutionConflict(f"Unsafe destination directory: {path}")


def prepare_media_package_manifest(package: Path, *, media_package_root: Path,
                            allowed_roots: list[Path], quarantine_root: Path | None,
                            preview_record: dict, job_id: int) -> dict:
    """Freeze one ready package with full source identities and exact targets."""
    source = _package_path(package, media_package_root, allowed_roots, quarantine_root)
    if preview_record.get("package") != str(source) or preview_record.get("status") != "ready":
        raise MediaPackageExecutionConflict("Selected package was not ready in the preview")
    fresh = preview_media_package_package(
        source, media_package_root=media_package_root, allowed_roots=allowed_roots,
        quarantine_root=quarantine_root, include_items=True,
    )
    if (fresh.get("status") != "ready"
            or not isinstance(preview_record.get("input_fingerprint"), str)
            or fresh["input_fingerprint"] != preview_record["input_fingerprint"]
            or fresh.get("needed_moves") != preview_record.get("needed_moves")
            or fresh.get("groups") != preview_record.get("groups")
            or fresh.get("operation") != preview_record.get("operation")):
        raise MediaPackageExecutionConflict(f"Package changed since preview: {source}")

    items = fresh.pop("_snapshot_items")
    if _input_fingerprint(items, source) != fresh["input_fingerprint"]:
        raise MediaPackageExecutionConflict("Package snapshot changed during its frozen preflight")
    package_stat = os.stat(source, follow_symlinks=False)
    _check_directory(package_stat, source)
    dev = int(package_stat.st_dev)
    for item in items:
        if item["dev"] != dev:
            raise MediaPackageExecutionConflict("Cross-filesystem package cannot be moved safely")

    directories: dict[str, list[int]] = {}
    for item in items:
        parent = Path(item["path"]).parent
        while parent != source:
            if not parent.is_relative_to(source):
                raise MediaPackageExecutionConflict("Source escaped protected package")
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
    root_stage = f".nfc-media_package-stage-{job_id}-root" if is_flat else None
    if is_flat:
        ordered = sorted(items, key=lambda row: (
            os.path.relpath(row["path"], source).casefold(),
            os.path.relpath(row["path"], source),
        ))
        names, _ = allocate_names(ordered, kind="flat")
        for item, target_name in zip(ordered, names):
            # Even a root file that is already numbered must be staged:
            # it could occupy another source file's desired final name.
            target = source / root_stage / target_name
            final = source / target_name
            moves.append({
                "source": item["path"], "target": str(target),
                "final": str(final), "identity": [
                    item["dev"], item["ino"], item["bytes"], item["mtime_ns"],
                ], "group": None, "target_name": target_name,
                "original_name": item["name"],
                "original_relative_path": os.path.relpath(item["path"], source),
                "final_relative_path": target_name,
            })
    else:
        items.sort(key=lambda row: (
            row["kind"], os.path.relpath(row["path"], source).casefold(),
            os.path.relpath(row["path"], source),
        ))
        by_kind = {kind: [item for item in items if item["kind"] == kind]
                   for kind in ("P", "V", "Other")}
        offsets = {"P": 0, "V": 0, "Other": 0}
        for idx, group in enumerate(fresh["groups"]):
            kind = group["kind"]
            start = offsets[kind]
            segment = by_kind[kind][start:start + int(group["count"])]
            offsets[kind] = start + len(segment)
            if not segment or len(segment) != group["count"] or sum(
                item["bytes"] for item in segment
            ) != group["bytes"]:
                raise MediaPackageExecutionConflict("Proposed grouping changed during freeze")
            stage = f".nfc-media_package-stage-{job_id}-{idx}"
            final = source / group["name"]
            groups.append({
                "stage": stage, "final": group["name"], "count": len(segment),
                "bytes": group["bytes"], "kind": kind, "move_start": len(moves),
            })
            assigned, _ = allocate_names(segment, kind=kind)
            for item, target_name in zip(segment, assigned):
                target = source / stage / target_name
                if item["path"] == str(final / target_name):
                    # Existing destination buckets may not be silently replaced.
                    raise MediaPackageExecutionConflict("Unexpected source inside a final bucket")
                moves.append({
                    "source": item["path"], "target": str(target),
                    "final": str(final / target_name),
                    "identity": [item["dev"], item["ino"], item["bytes"], item["mtime_ns"]],
                    "group": idx, "target_name": target_name,
                    "original_name": item["name"],
                    "original_relative_path": os.path.relpath(item["path"], source),
                    "final_relative_path": os.path.relpath(final / target_name, source),
                })

    if len(moves) != int(fresh["needed_moves"]):
        raise MediaPackageExecutionConflict("Frozen move count differs from reviewed preview")
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "job_id": job_id, "package": str(source), "media_package_root": str(media_package_root),
        "package_dev": dev, "package_ino": int(package_stat.st_ino),
        "input_fingerprint": fresh["input_fingerprint"],
        "operation": fresh["operation"], "root_stage": root_stage,
        "groups": groups, "moves": moves, "origin_directories": directories,
    }
    return manifest


def _manifest_checksum(manifest: dict) -> str:
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_frozen_manifest(path: Path, manifest: dict) -> None:
    """Exclusive, crash-safe publication on CONFIG_DIR; never overwrite."""
    if path.exists() or path.is_symlink():
        raise MediaPackageExecutionConflict("Frozen manifest path already exists")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = path.with_name(path.name + ".tmp")
    if os.path.lexists(staging):
        raise MediaPackageExecutionConflict("Untrusted partial manifest artifact exists")
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
        raise MediaPackageExecutionConflict("Frozen manifest is missing or unsafe")
    with path.open("r", encoding="utf-8") as stream:
        body = json.load(stream)
    manifest = body.get("manifest")
    if (not isinstance(manifest, dict)
            or body.get("checksum") != _manifest_checksum(manifest)
            or manifest.get("schema_version") != MANIFEST_VERSION
            or manifest.get("job_id") != job_id
            or manifest.get("package") != str(package)):
        raise MediaPackageExecutionConflict("Frozen manifest integrity mismatch")
    return manifest


def _entry(folder: Path, name: str):
    try:
        return _stat_entry(folder, name)
    except FileNotFoundError:
        return None


def _move_one(move: dict, *, lease_fence: Callable[[], None],
              ignore_final: bool = False, compat_hardlink: bool = False) -> str:
    """Reconcile crashed no-clobber moves and perform at most one filesystem move."""
    src = Path(move["source"])
    stage = Path(move["target"])
    final = Path(move["final"])
    expected = move["identity"]
    # Published group may already have renamed staging -> final on crash.
    stage_stat = _entry(stage.parent, stage.name) if stage.parent.is_dir() else None
    final_stat = (_entry(final.parent, final.name)
                  if not ignore_final and final != stage and final.parent.is_dir()
                  else None)
    if stage_stat is not None and final_stat is not None:
        if not compat_hardlink:
            raise MediaPackageExecutionConflict("Both staged and published file bindings exist")
        _check_file(stage_stat, expected, stage)
        _check_file(final_stat, expected, final)
        # This combination is only allowed after the authenticated group
        # witness has been verified by execute_frozen_manifest.
        if src.parent.is_dir() and _entry(src.parent, src.name) is not None:
            raise MediaPackageExecutionConflict("Source still exists alongside published links")
        return "resumed"
    existing = final_stat if final_stat is not None else stage_stat
    if existing is not None:
        _check_file(existing, expected, final if final_stat else stage)
        src_stat = _entry(src.parent, src.name) if src.parent.is_dir() else None
        if src_stat is None:
            return "resumed"
        _check_file(src_stat, expected, src)
        # A source and target with identical inode can be an interrupted
        # COMPAT hardlink operation, but it can also be a pre-existing alias.
        # Without an independently committed per-file publication intent,
        # NEVER unlink a source in this ambiguous state. Require review.
        raise MediaPackageExecutionConflict(
            f"Both source and destination exist; manual review: {src}"
        )

    src_fd = _open_folder(src.parent)
    try:
        source_stat = os.stat(src.name, dir_fd=src_fd, follow_symlinks=False)
        _check_file(source_stat, expected, src)
        dst_fd = _open_folder(stage.parent)
        try:
            if os.fstat(dst_fd).st_dev != source_stat.st_dev:
                raise MediaPackageExecutionConflict("Cross-filesystem move rejected")
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
    group = manifest["groups"][group_index]
    start = group["move_start"]
    return manifest["moves"][start:start + group["count"]]


def _verify_group_contents(manifest: dict, group_index: int, directory: Path) -> None:
    group = manifest["groups"][group_index]
    expected = {Path(row["final"]).name.casefold(): row["identity"]
                for row in _group_files(manifest, group_index)}
    if len(expected) != group["count"]:
        raise MediaPackageExecutionConflict("Group filename collision in frozen manifest")
    fd = _open_folder(directory)
    try:
        seen = set()
        size = 0
        with os.scandir(fd) as entries:
            for entry in entries:
                folded = entry.name.casefold()
                if folded in seen or folded not in expected:
                    raise MediaPackageExecutionConflict("Unrecognized file inside MediaPackage stage/group")
                seen.add(folded)
                st = entry.stat(follow_symlinks=False)
                _check_file(st, expected[folded], directory / entry.name)
                size += int(st.st_size)
        if len(seen) != group["count"] or size != group["bytes"]:
            raise MediaPackageExecutionConflict("Group count/size is incomplete")
    finally:
        os.close(fd)


def _ensure_staging(manifest: dict, group_index: int, lease_fence: Callable[[], None]) -> None:
    package = Path(manifest["package"])
    group = manifest["groups"][group_index]
    stage = package / group["stage"]
    final = package / group["final"]
    if final.exists() or final.is_symlink():
        if _compat_inspect_group(manifest, group_index) is not None:
            return
        if stage.exists() or stage.is_symlink():
            raise MediaPackageExecutionConflict("Both staging and foreign published directories exist")
        _verify_group_contents(manifest, group_index, final)
        return
    if stage.exists() or stage.is_symlink():
        fd = _open_folder(stage)
        try:
            _check_directory(os.fstat(fd), stage, manifest["package_dev"])
            # A pre-existing staging name cannot be trusted just because it
            # looks like a prior Worker run. Validate every existing entry.
            expected = {Path(row["target"]).name.casefold(): row["identity"]
                        for row in _group_files(manifest, group_index)}
            seen = set()
            with os.scandir(fd) as entries:
                for entry in entries:
                    folded = entry.name.casefold()
                    if folded in seen or folded not in expected:
                        raise MediaPackageExecutionConflict("Foreign entry in existing stage")
                    seen.add(folded)
                    _check_file(entry.stat(follow_symlinks=False), expected[folded],
                                stage / entry.name)
        finally:
            os.close(fd)
        return
    lease_fence()
    fd = _open_folder(package)
    try:
        os.mkdir(group["stage"], mode=0o755, dir_fd=fd)
    finally:
        os.close(fd)


_COMPAT_OWNER_MARKER = ".nfc-media-publish-owner"
_COMPAT_COMPLETE_MARKER = ".nfc-media-publish-complete"


def _compat_marker_bytes(manifest: dict, group_index: int) -> bytes:
    """Manifest-bound recovery witness, never a substitute for file identities."""
    group = manifest["groups"][group_index]
    return json.dumps({
        "version": 1,
        "job_id": manifest["job_id"],
        "group_index": group_index,
        "manifest_checksum": _manifest_checksum(manifest),
        "stage": group["stage"],
        "final": group["final"],
        "count": group["count"],
        "bytes": group["bytes"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _compat_marker_matches(dir_fd: int, name: str, expected: bytes) -> bool:
    """Require exact regular marker bytes; never follow a substituted symlink."""
    try:
        fd = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd,
        )
    except FileNotFoundError:
        return False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size != len(expected):
            raise MediaPackageExecutionConflict("Invalid frozen publication witness")
        if os.read(fd, len(expected) + 1) != expected:
            raise MediaPackageExecutionConflict("Frozen publication witness changed")
        return True
    finally:
        os.close(fd)


def _compat_create_marker(dir_fd: int, name: str, data: bytes) -> None:
    fd = os.open(
        name,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        0o600, dir_fd=dir_fd,
    )
    try:
        if os.write(fd, data) != len(data):
            raise MediaPackageExecutionConflict("Incomplete frozen publication witness")
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)


def _compat_inspect_group(manifest: dict, group_index: int) -> dict | None:
    """Read-only validation of a partially published, job-owned group.

    The marker alone grants NO authority. Every existing source-stage and
    public binding must match its frozen file identity; all rows must still
    have at least one matching binding. A foreign directory or unknown file
    causes a hard failure without touching it.
    """
    group = manifest["groups"][group_index]
    package = Path(manifest["package"])
    stage = package / group["stage"]
    final = package / group["final"]
    if not os.path.lexists(final):
        return None
    dst_fd = _open_folder(final)
    data = _compat_marker_bytes(manifest, group_index)
    try:
        _check_directory(os.fstat(dst_fd), final, manifest["package_dev"])
        if not _compat_marker_matches(dst_fd, _COMPAT_OWNER_MARKER, data):
            return None
        done = _compat_marker_matches(dst_fd, _COMPAT_COMPLETE_MARKER, data)
        expected = {
            Path(row["final"]).name.casefold(): row["identity"]
            for row in _group_files(manifest, group_index)
        }
        if len(expected) != len(_group_files(manifest, group_index)):
            raise MediaPackageExecutionConflict("Frozen publication duplicate names")
        public_names: set[str] = set()
        with os.scandir(dst_fd) as entries:
            for entry in entries:
                if entry.name in (_COMPAT_OWNER_MARKER, _COMPAT_COMPLETE_MARKER):
                    continue
                key = entry.name.casefold()
                if key not in expected or key in public_names:
                    raise MediaPackageExecutionConflict("Foreign entry in owned publication")
                public_names.add(key)
                _check_file(entry.stat(follow_symlinks=False),
                            expected[key], final / entry.name)
    finally:
        os.close(dst_fd)

    stage_names: set[str] = set()
    has_stage = os.path.lexists(stage)
    if has_stage:
        src_fd = _open_folder(stage)
        try:
            _check_directory(os.fstat(src_fd), stage, manifest["package_dev"])
            with os.scandir(src_fd) as entries:
                for entry in entries:
                    key = entry.name.casefold()
                    if key not in expected or key in stage_names:
                        raise MediaPackageExecutionConflict("Foreign entry in owned staging")
                    stage_names.add(key)
                    _check_file(entry.stat(follow_symlinks=False),
                                expected[key], stage / entry.name)
        finally:
            os.close(src_fd)

    if public_names | stage_names != set(expected):
        raise MediaPackageExecutionConflict("Frozen publication is incomplete")
    if done and public_names != set(expected):
        raise MediaPackageExecutionConflict("Completed publication has missing files")
    if not has_stage and public_names != set(expected):
        raise MediaPackageExecutionConflict("Missing stage before publication completed")
    return {
        "stage_exists": has_stage,
        "public_names": public_names,
        "stage_names": stage_names,
        "complete": done,
        "all_public": public_names == set(expected),
    }


def _publish_group_compat(manifest: dict, group_index: int,
                          lease_fence: Callable[[], None]) -> str:
    """FUSE-safe publication: exclusive mkdir, hardlinks, durable witness.

    NO plain directory rename, NO adopted foreign final, NO copy/delete.
    Files remain reachable from original stage until ALL final links have
    been individually verified. A crash at any point retains the original
    frozen manifest and can be reconciled without re-numbering.
    """
    package = Path(manifest["package"])
    group = manifest["groups"][group_index]
    stage = package / group["stage"]
    final = package / group["final"]
    marker = _compat_marker_bytes(manifest, group_index)
    evidence = _compat_inspect_group(manifest, group_index)
    if evidence is None:
        # This is the only path permitted to allocate the final name. An
        # unexpected existing directory without our witness cannot be used.
        if os.path.lexists(final):
            raise MediaPackageExecutionConflict("Foreign target directory cannot be adopted")
        _verify_group_contents(manifest, group_index, stage)
        package_fd = _open_verified_package(manifest)
        try:
            # On filesystems without directory fsync we cannot guarantee the
            # metadata journal survives a crash; refuse BEFORE mkdir.
            os.fsync(package_fd)
            lease_fence()
            os.mkdir(group["final"], mode=0o755, dir_fd=package_fd)
            os.fsync(package_fd)
        finally:
            os.close(package_fd)
        # A crash between mkdir and this write leaves an unmarked target,
        # which is intentionally held for MANUAL review, never adopted.
        final_fd = _open_folder(final)
        try:
            _compat_create_marker(final_fd, _COMPAT_OWNER_MARKER, marker)
        finally:
            os.close(final_fd)
        evidence = _compat_inspect_group(manifest, group_index)
        if evidence is None:
            raise MediaPackageExecutionConflict("Publication ownership marker missing")

    if evidence["stage_exists"]:
        src_fd = _open_folder(stage)
    else:
        src_fd = None
    dst_fd = _open_folder(final)
    try:
        if src_fd is not None:
            _check_directory(os.fstat(src_fd), stage, manifest["package_dev"])
        _check_directory(os.fstat(dst_fd), final, manifest["package_dev"])
        if not _compat_marker_matches(dst_fd, _COMPAT_OWNER_MARKER, marker):
            raise MediaPackageExecutionConflict("Publication owner witness disappeared")
        # Never resume pending writes when the mount has lost durability
        # support, even if a marker happened to survive a prior crash.
        os.fsync(dst_fd)
        if src_fd is not None:
            os.fsync(src_fd)
        # Phase I: create ALL final file links with exclusive link(2).
        for row in _group_files(manifest, group_index):
            name = row["target_name"]
            expected = row["identity"]
            target_st = _entry(final, name)
            if target_st is not None:
                _check_file(target_st, expected, final / name)
                continue
            if src_fd is None:
                raise MediaPackageExecutionConflict("Frozen stage missing during publication")
            source_st = os.stat(name, dir_fd=src_fd, follow_symlinks=False)
            _check_file(source_st, expected, stage / name)
            lease_fence()
            os.link(name, name, src_dir_fd=src_fd, dst_dir_fd=dst_fd,
                    follow_symlinks=False)
            _check_file(os.stat(name, dir_fd=dst_fd, follow_symlinks=False),
                        expected, final / name)
        # The completeness check ignores only the two exact owned witnesses.
        evidence = _compat_inspect_group(manifest, group_index)
        if evidence is None or not evidence["all_public"]:
            raise MediaPackageExecutionConflict("Publication not yet complete")
        if not evidence["complete"]:
            lease_fence()
            _compat_create_marker(dst_fd, _COMPAT_COMPLETE_MARKER, marker)

        # Phase II: retire only proven duplicate stage links, never payloads.
        # A power loss here still leaves every final link present with the
        # original inode and a durable committed publication witness.
        if src_fd is not None:
            for row in _group_files(manifest, group_index):
                name = row["target_name"]
                before = _entry(stage, name)
                if before is None:
                    continue
                _check_file(before, row["identity"], stage / name)
                _check_file(os.stat(name, dir_fd=dst_fd, follow_symlinks=False),
                            row["identity"], final / name)
                lease_fence()
                os.unlink(name, dir_fd=src_fd)
                _check_file(os.stat(name, dir_fd=dst_fd, follow_symlinks=False),
                            row["identity"], final / name)
            os.fsync(dst_fd)
    finally:
        os.close(dst_fd)
        if src_fd is not None:
            os.close(src_fd)

    # Stage is now provably empty and no longer needed. Do NOT remove the
    # public owner marker until the former stage name has been retired.
    _compat_inspect_group(manifest, group_index)
    if os.path.lexists(stage):
        package_fd = _open_verified_package(manifest)
        try:
            lease_fence()
            os.rmdir(group["stage"], dir_fd=package_fd)
            os.fsync(package_fd)
        finally:
            os.close(package_fd)

    final_fd = _open_folder(final)
    try:
        if not _compat_marker_matches(final_fd, _COMPAT_OWNER_MARKER, marker):
            raise MediaPackageExecutionConflict("Publication witness lost before completion")
        for name in (_COMPAT_COMPLETE_MARKER, _COMPAT_OWNER_MARKER):
            if _compat_marker_matches(final_fd, name, marker):
                lease_fence()
                os.unlink(name, dir_fd=final_fd)
                os.fsync(final_fd)
    finally:
        os.close(final_fd)
    _verify_group_contents(manifest, group_index, final)
    return "published"


def _frozen_artifact_proves_package(manifest: dict) -> bool:
    """Permit directory inode drift only when an existing frozen file proves custody.

    Some NAS/FUSE mounts report a different directory inode after adding
    children. A replacement directory is *not* accepted just because the path
    still exists: require an intact staged or published file matching the
    checksum-validated original manifest's device/inode/size/mtime tuple.
    Unknown staging entries, symlinks, or an incomplete published group fail
    closed. This never creates, deletes or renames any file.
    """
    package = Path(manifest["package"])
    if manifest.get("root_stage") is not None:
        stage = package / manifest["root_stage"]
        if os.path.lexists(stage):
            _flat_stage_inspect(manifest, stage)
            fd = _open_folder(stage)
            try:
                with os.scandir(fd) as entries:
                    if any(e.name != _ROOT_READY_MARKER for e in entries):
                        return True
            finally:
                os.close(fd)
        return _root_finals_complete(manifest)

    confirmed = False
    for index, group in enumerate(manifest["groups"]):
        staged = package / group["stage"]
        published = package / group["final"]
        has_stage = os.path.lexists(staged)
        has_final = os.path.lexists(published)
        if has_final:
            compat = _compat_inspect_group(manifest, index)
            if compat is not None:
                confirmed |= bool(compat["public_names"] or compat["stage_names"])
                continue
            if has_stage:
                raise MediaPackageExecutionConflict(
                    "Both frozen stage and foreign final directory exist"
                )
        if not has_stage and not has_final:
            continue
        target = published if has_final else staged
        expected_rows = _group_files(manifest, index)
        expected = {
            Path(row["final" if has_final else "target"]).name.casefold(): row["identity"]
            for row in expected_rows
        }
        if len(expected) != len(expected_rows):
            raise MediaPackageExecutionConflict("Frozen destination names are not unique")
        fd = _open_folder(target)
        seen = set()
        try:
            _check_directory(os.fstat(fd), target, manifest["package_dev"])
            with os.scandir(fd) as entries:
                for entry in entries:
                    folded = entry.name.casefold()
                    if folded not in expected or folded in seen:
                        raise MediaPackageExecutionConflict(
                            "Unknown or repeated file in frozen recovery directory"
                        )
                    seen.add(folded)
                    _check_file(entry.stat(follow_symlinks=False),
                                expected[folded], target / entry.name)
            if has_final and len(seen) != len(expected_rows):
                raise MediaPackageExecutionConflict(
                    "Published folder is incomplete during recovery"
                )
            confirmed |= bool(seen)
        finally:
            os.close(fd)
    return confirmed


def _open_verified_package(manifest: dict) -> int:
    """Open the literal package path without following symlinks.

    Check the parent-to-package binding at the time of use. The frozen
    directory inode remains authoritative until trusted staged/published file
    evidence proves this is the original frozen job despite NAS inode drift.
    Device changes are never tolerated.
    """
    package = Path(manifest["package"])
    fd = _open_folder(package)
    try:
        current = os.fstat(fd)
        _check_directory(current, package, manifest["package_dev"])
        parent_fd = _open_folder(package.parent)
        try:
            parent_entry = os.stat(package.name, dir_fd=parent_fd,
                                   follow_symlinks=False)
            _check_directory(parent_entry, package, manifest["package_dev"])
            if (int(parent_entry.st_dev), int(parent_entry.st_ino)) != (
                int(current.st_dev), int(current.st_ino)
            ):
                raise MediaPackageExecutionConflict(
                    "Package directory binding changed between verification and use"
                )
        finally:
            os.close(parent_fd)

        if int(current.st_ino) != manifest["package_ino"]:
            if not _frozen_artifact_proves_package(manifest):
                raise MediaPackageExecutionConflict(
                    "Package directory identity changed without trusted frozen files"
                )
        return fd
    except BaseException:
        os.close(fd)
        raise


def _publish_group(manifest: dict, group_index: int,
                   lease_fence: Callable[[], None], *,
                   allow_fuse_compat: bool = False) -> str:
    package = Path(manifest["package"])
    group = manifest["groups"][group_index]
    stage = package / group["stage"]
    final = package / group["final"]
    if final.exists() or final.is_symlink():
        if _compat_inspect_group(manifest, group_index) is not None:
            if not allow_fuse_compat:
                raise MediaPackageExecutionConflict(
                    "FUSE compatible publication is disabled until same-mount capability testing"
                )
            return _publish_group_compat(manifest, group_index, lease_fence)
        if stage.exists() or stage.is_symlink():
            raise MediaPackageExecutionConflict("Published name and foreign staging both exist")
        _verify_group_contents(manifest, group_index, final)
        return "already_published"
    _verify_group_contents(manifest, group_index, stage)
    lease_fence()
    fd = _open_verified_package(manifest)
    try:
        live_stage = os.stat(group["stage"], dir_fd=fd, follow_symlinks=False)
        _check_directory(live_stage, stage, manifest["package_dev"])
        stage_fd = _open_folder(stage)
        try:
            opened_stage = os.fstat(stage_fd)
            if (opened_stage.st_ino != live_stage.st_ino
                    or opened_stage.st_dev != live_stage.st_dev):
                raise MediaPackageExecutionConflict("Staging directory replaced before publish")
        finally:
            os.close(stage_fd)
        try:
            rename_noreplace_at(fd, group["stage"], fd, group["final"])
        except OSError as exc:
            if exc.errno != errno.EOPNOTSUPP:
                raise
            # Prefer a positive-probed plain directory rename, but ZOS FUSE
            # may not prove no-clobber. Never weaken that proof requirement.
            try:
                rename_directory_noreplace_compat(stage, final)
            except OSError as compat_exc:
                if compat_exc.errno != errno.EOPNOTSUPP:
                    raise
                if not allow_fuse_compat:
                    raise MediaPackageExecutionConflict(
                        "FUSE grouped publication disabled: run the isolated NAS probe "
                        "and explicitly enable MEDIA_PACKAGE_FUSE_COMPAT_ENABLED"
                    ) from compat_exc
                return _publish_group_compat(manifest, group_index, lease_fence)
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
            raise MediaPackageExecutionConflict("Unsafe original directory cleanup scope")
        if not folder.exists():
            continue
        if folder.is_symlink():
            raise MediaPackageExecutionConflict("Original directory became a symlink")
        fd = _open_folder(folder)
        try:
            st = os.fstat(fd)
            if [int(st.st_dev), int(st.st_ino)] != identity:
                raise MediaPackageExecutionConflict("Original directory replaced during cleanup")
        finally:
            os.close(fd)
        lease_fence()
        parent_fd = _open_folder(folder.parent)
        try:
            live = os.stat(folder.name, dir_fd=parent_fd, follow_symlinks=False)
            if (not stat.S_ISDIR(live.st_mode) or
                    [int(live.st_dev), int(live.st_ino)] != identity):
                raise MediaPackageExecutionConflict("Original directory changed before rmdir")
            try:
                os.rmdir(folder.name, dir_fd=parent_fd)
                removed += 1
            except OSError as exc:
                if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise
        finally:
            os.close(parent_fd)
    return removed


_ROOT_READY_MARKER = ".nfc-publish-ready"


def _flat_rows(manifest: dict) -> list[dict]:
    return manifest["moves"]


def _root_finals_complete(manifest: dict) -> bool:
    """Recognize a previously published flat package only by EVERY frozen inode.

    During normal preflight some original root filenames may already be
    numbered, but the full expected final set cannot match a ready-to-rename
    package without all of its other source bindings having retired.
    """
    package = Path(manifest["package"])
    manifest_final_targets = {
        row["final"]: row["identity"] for row in _flat_rows(manifest)
    }
    if len(manifest_final_targets) != len(manifest["moves"]):
        raise MediaPackageExecutionConflict("Duplicate flat final targets")
    for row in _flat_rows(manifest):
        target = Path(row["final"])
        st = _entry(package, target.name)
        if st is None or not stat.S_ISREG(st.st_mode) or _identity(st) != row["identity"]:
            return False
        src = Path(row["source"])
        if src != target and src.parent.is_dir():
            prior_binding = _entry(src.parent, src.name)
            if prior_binding is not None:
                # The old basename can now be another row's new final name.
                # Only treat it as an unretired source if its inode is still
                # this row's original identity; never confuse a harmless
                # final-name permutation with a partial pending move.
                if _identity(prior_binding) == row["identity"]:
                    return False
                # A foreign name that is not part of the frozen final map
                # must also prevent automatic publication/cleanup.
                if str(src) not in manifest_final_targets:
                    return False
                expected_other = manifest_final_targets[str(src)]
                if _identity(prior_binding) != expected_other:
                    return False
    return True


def _flat_stage_inspect(manifest: dict, stage: Path) -> bool:
    """Validate all existing stage entries; return whether publish marker exists."""
    expected = {Path(row["target"]).name.casefold(): row["identity"]
                for row in _flat_rows(manifest)}
    if len(expected) != len(manifest["moves"]):
        raise MediaPackageExecutionConflict("Flat numbered destination collision")
    folder = _open_folder(stage)
    has_marker = False
    try:
        st = os.fstat(folder)
        if int(st.st_dev) != manifest["package_dev"]:
            raise MediaPackageExecutionConflict("Flat staging device changed")
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name == _ROOT_READY_MARKER:
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        raise MediaPackageExecutionConflict("Invalid publish marker type")
                    has_marker = True
                    continue
                key = entry.name.casefold()
                if key not in expected:
                    raise MediaPackageExecutionConflict("Foreign file in flat staging directory")
                _check_file(entry.stat(follow_symlinks=False),
                            expected[key], stage / entry.name)
        if has_marker:
            marker_fd = os.open(
                _ROOT_READY_MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder,
            )
            try:
                contents = os.read(marker_fd, 128)
            finally:
                os.close(marker_fd)
            if contents != _manifest_checksum(manifest).encode("ascii"):
                raise MediaPackageExecutionConflict("Frozen flat publish marker mismatched")
    finally:
        os.close(folder)
    return has_marker


def _flat_stage_complete(manifest: dict, stage: Path) -> None:
    expected = {Path(row["target"]).name.casefold(): row["identity"]
                for row in _flat_rows(manifest)}
    seen = set()
    fd = _open_folder(stage)
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                key = entry.name.casefold()
                if key not in expected or key in seen:
                    raise MediaPackageExecutionConflict("Unexpected entry in complete flat stage")
                seen.add(key)
                _check_file(entry.stat(follow_symlinks=False),
                            expected[key], stage / entry.name)
        if seen != set(expected):
            raise MediaPackageExecutionConflict("Flat media package has incomplete staging")
    finally:
        os.close(fd)


def _mark_flat_ready(manifest: dict, stage: Path,
                     lease_fence: Callable[[], None]) -> None:
    lease_fence()
    fd = _open_folder(stage)
    try:
        marker = os.open(
            _ROOT_READY_MARKER,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600, dir_fd=fd,
        )
        try:
            os.write(marker, _manifest_checksum(manifest).encode("ascii"))
            os.fsync(marker)
        finally:
            os.close(marker)
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_flat_file(row: dict, stage: Path, package: Path,
                       lease_fence: Callable[[], None]) -> str:
    name = Path(row["target"]).name
    before = _entry(stage, name)
    published = _entry(package, name)
    if before is None:
        _check_file(published, row["identity"], package / name)
        return "resumed"
    _check_file(before, row["identity"], stage / name)
    if published is not None:
        raise MediaPackageExecutionConflict(
            f"Root destination occupied; refuse overwrite: {package / name}"
        )
    stage_fd = _open_folder(stage)
    package_fd = _open_folder(package)
    try:
        lease_fence()
        _check_file(os.stat(name, dir_fd=stage_fd, follow_symlinks=False),
                    row["identity"], stage / name)
        try:
            rename_noreplace_at(stage_fd, name, package_fd, name)
        except OSError as exc:
            if exc.errno != errno.EOPNOTSUPP:
                raise
            # Atomic link publication never clobbers an existing name.
            # A crash between link and unlink leaves two names: block and
            # require human reconciliation rather than risking data loss.
            os.link(name, name, src_dir_fd=stage_fd,
                    dst_dir_fd=package_fd, follow_symlinks=False)
            _check_file(os.stat(name, dir_fd=package_fd, follow_symlinks=False),
                        row["identity"], package / name)
            lease_fence()
            os.unlink(name, dir_fd=stage_fd)
        _check_file(os.stat(name, dir_fd=package_fd, follow_symlinks=False),
                    row["identity"], package / name)
    finally:
        os.close(package_fd)
        os.close(stage_fd)
    return "published"


def _remove_flat_stage(manifest: dict, stage: Path,
                       lease_fence: Callable[[], None]) -> None:
    if not _root_finals_complete(manifest):
        raise MediaPackageExecutionConflict("Flat result is incomplete; refusing cleanup")
    if not stage.exists():
        return
    if stage.is_symlink():
        raise MediaPackageExecutionConflict("Unsafe flat staging symlink")
    fd = _open_folder(stage)
    try:
        try:
            st = os.stat(_ROOT_READY_MARKER, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            st = None
        if st is not None:
            if not stat.S_ISREG(st.st_mode):
                raise MediaPackageExecutionConflict("Unsafe flat publish marker")
            lease_fence()
            os.unlink(_ROOT_READY_MARKER, dir_fd=fd)
    finally:
        os.close(fd)
    lease_fence()
    parent_fd = _open_folder(stage.parent)
    try:
        os.rmdir(stage.name, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def _execute_flat_manifest(manifest: dict, lease_fence: Callable[[], None],
                           progress: Callable[[int, int], None] | None) -> dict:
    package = Path(manifest["package"])
    stage = package / manifest["root_stage"]
    total = len(_flat_rows(manifest))
    if _root_finals_complete(manifest):
        _remove_flat_stage(manifest, stage, lease_fence)
        return {"files_moved": 0, "files_reconciled": total,
                "groups_published": 0}

    if stage.is_symlink():
        raise MediaPackageExecutionConflict("Unsafe flat staging symlink")
    if not stage.exists():
        lease_fence()
        fd = _open_folder(package)
        try:
            os.mkdir(stage.name, 0o700, dir_fd=fd)
        finally:
            os.close(fd)
    marked = _flat_stage_inspect(manifest, stage)
    completed = 0
    recovered = 0
    if not marked:
        for i, row in enumerate(_flat_rows(manifest), 1):
            outcome = _move_one(row, lease_fence=lease_fence, ignore_final=True)
            completed += outcome == "moved"
            recovered += outcome != "moved"
            if progress and (i % 25 == 0 or i == total):
                progress(i, total)
        _flat_stage_complete(manifest, stage)
        _mark_flat_ready(manifest, stage, lease_fence)
    else:
        # The durable marker is recorded before ANY final name publication.
        # After a crash, do not re-stage a file whose final name is already
        # published, including an item whose original source name is identical.
        recovered = total

    for row in _flat_rows(manifest):
        _publish_flat_file(row, stage, package, lease_fence)
    _remove_flat_stage(manifest, stage, lease_fence)
    return {"files_moved": completed, "files_reconciled": recovered,
            "groups_published": 0}


def _validate_frozen_paths(manifest: dict) -> None:
    """Reject any corrupt/artifact-rewritten path outside the resource package."""
    package = Path(manifest["package"])
    if (not package.is_absolute() or
            not isinstance(manifest.get("job_id"), int) or manifest["job_id"] < 1):
        raise MediaPackageExecutionConflict("Invalid protected package / job identity")
    dev = manifest.get("package_dev")
    if not isinstance(dev, int) or dev <= 0:
        raise MediaPackageExecutionConflict("Invalid frozen filesystem identity")
    root_stage = manifest.get("root_stage")
    if root_stage is not None:
        if (manifest.get("operation") != "flatten_pure_media"
                or root_stage != f".nfc-media_package-stage-{manifest['job_id']}-root"
                or manifest.get("groups")):
            raise MediaPackageExecutionConflict("Invalid frozen flat staging scope")
    elif manifest.get("operation") == "flatten_pure_media":
        raise MediaPackageExecutionConflict("Missing flat staging authority")
    for index, group in enumerate(manifest.get("groups", [])):
        stage = f".nfc-media_package-stage-{manifest['job_id']}-{index}"
        if group.get("stage") != stage:
            raise MediaPackageExecutionConflict("Untrusted MediaPackage staging directory name")
        final = Path(group.get("final", ""))
        if (not final.name or final.is_absolute() or len(final.parts) != 1
                or final.name in (".", "..") or
                not isinstance(group.get("count"), int) or
                group["count"] < 1 or group["count"] > 300_000 or
                group.get("move_start", -1) < 0 or
                group.get("kind") not in ("P", "V", "Other")):
            raise MediaPackageExecutionConflict("Invalid frozen MediaPackage group metadata")
        if group["kind"] in ("P", "V") and group["count"] > MAX_FILES_PER_GROUP:
            raise MediaPackageExecutionConflict("200-file MediaPackage capacity exceeded")

    rows = manifest.get("moves")
    if not isinstance(rows, list):
        raise MediaPackageExecutionConflict("Invalid frozen MediaPackage move list")
    for row in rows:
        src, dest, final = (Path(row["source"]), Path(row["target"]),
                            Path(row["final"]))
        if (not src.is_absolute() or not src.is_relative_to(package)
                or ".." in src.relative_to(package).parts
                or src == package or src.name in (".", "..")
                or row.get("identity") is None or
                len(row["identity"]) != 4 or
                row["identity"][0] != dev):
            raise MediaPackageExecutionConflict("Unsafe frozen MediaPackage source")
        target_name = row.get("target_name")
        if (not isinstance(target_name, str) or not target_name
                or Path(target_name).name != target_name
                or target_name in (".", "..")
                or Path(target_name).suffix != src.suffix
                or row.get("original_name") != src.name
                or row.get("original_relative_path") != os.path.relpath(src, package)
                or row.get("final_relative_path") != os.path.relpath(final, package)):
            raise MediaPackageExecutionConflict("Invalid frozen source-to-target filename mapping")
        group_index = row.get("group")
        if group_index is None:
            if root_stage is None:
                raise MediaPackageExecutionConflict("Flat target without frozen staging")
            expected_target = package / root_stage / target_name
            expected_final = package / target_name
        else:
            if not isinstance(group_index, int) or not 0 <= group_index < len(manifest["groups"]):
                raise MediaPackageExecutionConflict("Invalid frozen group association")
            group = manifest["groups"][group_index]
            expected_target = package / group["stage"] / target_name
            expected_final = package / group["final"] / target_name
        if dest != expected_target or final != expected_final or src == dest:
            raise MediaPackageExecutionConflict("Frozen media package move target escaped its package")
    for index, group in enumerate(manifest["groups"]):
        start, count = group["move_start"], group["count"]
        if start + count > len(rows) or any(
            row["group"] != index for row in rows[start:start + count]
        ):
            raise MediaPackageExecutionConflict("Frozen MediaPackage group rows are inconsistent")
    if root_stage is not None:
        if (len(rows) > MAX_FILES_PER_GROUP or any(row["group"] is not None for row in rows)
                or len({row["target_name"].casefold() for row in rows}) != len(rows)):
            raise MediaPackageExecutionConflict("Flat frozen numbering is inconsistent")
    else:
        covered = sum(group["count"] for group in manifest["groups"])
        if covered != len(rows):
            raise MediaPackageExecutionConflict("Frozen grouped move count is inconsistent")
        for index, group in enumerate(manifest["groups"]):
            part = rows[group["move_start"]:group["move_start"] + group["count"]]
            if len({row["target_name"].casefold() for row in part}) != len(part):
                raise MediaPackageExecutionConflict("Frozen group target filename collision")


def execute_frozen_manifest(manifest: dict, *, lease_fence: Callable[[], None],
                            progress: Callable[[int, int], None] | None = None,
                            allow_fuse_compat: bool = False) -> dict:
    """Run one package idempotently; the caller owns lease checkpoints/recovery."""
    package = Path(manifest["package"])
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise MediaPackageExecutionConflict("Unsupported frozen manifest version")
    _validate_frozen_paths(manifest)
    if not allow_fuse_compat:
        for index in range(len(manifest["groups"])):
            if _compat_inspect_group(manifest, index) is not None:
                raise MediaPackageExecutionConflict(
                    "FUSE compatibility recovery requires explicit operator opt-in"
                )
    fd = _open_verified_package(manifest)
    os.close(fd)
    # Before the first mutation of a new package job, reject any source or
    # target drift since Freeze. This catches late-arriving root files before
    # we relocate the first source into staging. Recovery is different:
    # the original snapshot cannot match after intentional partial moves,
    # so only an existing job-owned staging or published final bypasses it.
    root_stage = manifest.get("root_stage")
    recovery_artifact = (
        ((package / root_stage).exists() or _root_finals_complete(manifest))
        if root_stage
        else any(
            os.path.lexists(package / group["stage"]) or
            os.path.lexists(package / group["final"])
            for group in manifest["groups"]
        )
    )
    if not recovery_artifact:
        try:
            live = list(_walk_package(package))
        except (OSError, ValueError) as exc:
            raise MediaPackageExecutionConflict(
                f"Unsafe package changed since frozen preview: {exc}"
            ) from exc
        if _input_fingerprint(live, package) != manifest["input_fingerprint"]:
            raise MediaPackageExecutionConflict(
                "Package changed since frozen preview; refusing file mutation"
            )
    if manifest.get("root_stage"):
        result = _execute_flat_manifest(manifest, lease_fence, progress)
        result["empty_dirs_removed"] = _remove_empty_sources(manifest, lease_fence)
        result["total_files"] = len(manifest["moves"])
        result["package"] = str(package)
        return result
    compat_groups: set[int] = set()
    for i in range(len(manifest["groups"])):
        _ensure_staging(manifest, i, lease_fence)
        if _compat_inspect_group(manifest, i) is not None:
            compat_groups.add(i)
    completed = recovered = 0
    total = len(manifest["moves"])
    for index, row in enumerate(manifest["moves"], start=1):
        result = _move_one(
            row, lease_fence=lease_fence,
            compat_hardlink=row["group"] in compat_groups,
        )
        completed += result == "moved"
        recovered += result != "moved"
        if progress and (index % 25 == 0 or index == total):
            progress(index, total)
    published = 0
    for i in range(len(manifest["groups"])):
        if allow_fuse_compat:
            result = _publish_group(
                manifest, i, lease_fence, allow_fuse_compat=True,
            )
        else:
            result = _publish_group(manifest, i, lease_fence)
        if result == "published":
            published += 1
    cleaned = _remove_empty_sources(manifest, lease_fence)
    return {
        "files_moved": completed, "files_reconciled": recovered,
        "groups_published": published, "empty_dirs_removed": cleaned,
        "total_files": total, "package": str(package),
    }
