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
from tempfile import mkstemp
from typing import Callable

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_link_intent import LinkIntent
from app.batch.media_package_naming import organizer_extension
from app.batch.media_package_organizer import (
    APPEND_MEDIA_OPERATIONS, APPEND_MEDIA_WRAPPER, APPEND_SINGLE_VIDEO, APPEND_VIDEO_OPERATIONS,
    LIFT_LUOLCY_BUCKETS, MAX_FILES_PER_GROUP,
    PROMOTE_NUMBERED_PHOTO_GROUPS, _LUOLCY_SHORT_VIDEO_FOLDER,
    _author_media_row, _classify, _input_fingerprint,
    _luolcy_batch_boundary, _luolcy_bucket_slot, _luolcy_classification_kind, _luolcy_leaf_promotion,
    _luolcy_verified_bucket, _open_luolcy_author, _package_path, _size_label, _walk_package,
    preview_media_package_package,
)
from app.fs_ops import rename_directory_noreplace_compat, rename_noreplace_at


class MediaPackageExecutionConflict(ValueError):
    """A package cannot be safely executed without an operator reviewing it."""


MANIFEST_VERSION = 2
_FLAT_OPERATIONS = APPEND_MEDIA_OPERATIONS | {"flatten_pure_media"}


def _is_luolcy_author(manifest: dict) -> bool:
    return manifest.get("organizer_mode") == "luolcy" and manifest.get("whole_author") is True


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
        quarantine_root=quarantine_root, include_items=True, include_mapping=True,
    )
    if (fresh.get("status") != "ready"
            or not isinstance(preview_record.get("input_fingerprint"), str)
            or fresh["input_fingerprint"] != preview_record["input_fingerprint"]
            or fresh.get("needed_moves") != preview_record.get("needed_moves")
            or fresh.get("groups") != preview_record.get("groups")
            or fresh.get("operation") != preview_record.get("operation")):
        raise MediaPackageExecutionConflict(f"Package changed since preview: {source}")

    return _freeze_layout(source, fresh, media_package_root=media_package_root, job_id=job_id)


def prepare_organizer_manifest(
    unit: Path, *, mode: str, media_package_root: Path | None, allowed_roots: list[Path],
    quarantine_root: Path | None, preview_record: dict, job_id: int,
) -> dict:
    """Freeze the exact per-unit layout shown by the recursive preview."""
    from app.batch.media_organizer_planner import preview_organizing_unit

    local_media_kinds = tuple(preview_record.get("local_media_kinds", ()))
    local_scope = preview_record.get("local_scope")
    whole_author = preview_record.get("whole_author", False)
    # Only discover the wider scope again when it was part of the approved preview.
    fresh = preview_organizing_unit(
        unit, mode=mode, allowed_roots=allowed_roots, quarantine_root=quarantine_root,
        media_package_root=media_package_root, include_items=True, include_mapping=True,
        local_media_kinds=local_media_kinds,
        local_scope=local_scope,
        whole_author=None if mode == "semantic" and whole_author else whole_author,
    )
    if (preview_record.get("status") != "ready" or fresh.get("status") != "ready"
            or fresh.get("whole_author", False) != whole_author
            or fresh["actual_moves"] != preview_record.get("needed_moves")
            or fresh.get("luolcy_author_siblings", {}) != preview_record.get("luolcy_author_siblings", {})
            or any(fresh.get(key) != preview_record.get(key)
                   for key in ("unit", "input_fingerprint", "operation", "groups", "renamed_count",
                               "luolcy_root_fingerprint"))):
        raise MediaPackageExecutionConflict(f"Organizing unit changed since preview: {unit}")
    scope = {
        "organizer_mode": mode, "quarantine_root": str(quarantine_root) if quarantine_root else None,
        **({"local_media_kinds": list(local_media_kinds)} if local_media_kinds else {}),
        **({"local_scope": local_scope} if local_scope is not None else {}),
        **({"whole_author": True} if whole_author else {}),
    }
    if fresh.get("luolcy_author_siblings"):
        scope["luolcy_author_siblings"] = fresh["luolcy_author_siblings"]
    if fresh["operation"] == LIFT_LUOLCY_BUCKETS:
        scope["luolcy_root_fingerprint"] = fresh.get("luolcy_root_fingerprint")
    return _freeze_layout(unit, fresh, media_package_root=media_package_root, job_id=job_id,
                          organizer_scope=scope)


def _freeze_layout(source: Path, fresh: dict, *, media_package_root: Path | None, job_id: int,
                   organizer_scope: dict | None = None) -> dict:
    """Use the planner's complete source-to-target mapping in the frozen engine format."""
    items = fresh["_snapshot_items"]
    if _input_fingerprint(items, source) != fresh["input_fingerprint"]:
        raise MediaPackageExecutionConflict("Package snapshot changed during its frozen preflight")
    package_stat = os.stat(source, follow_symlinks=False)
    _check_directory(package_stat, source)
    dev = int(package_stat.st_dev)
    if any(item["dev"] != dev for item in items):
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

    is_flat = fresh["operation"] in _FLAT_OPERATIONS
    root_stage = f".nfc-media_package-stage-{job_id}-root" if is_flat else None
    groups = []
    group_indexes = {}
    offset = 0
    for idx, group in enumerate(fresh["groups"]):
        group_indexes[group["destination"]] = idx
        groups.append({
            "stage": f".nfc-media_package-stage-{job_id}-{idx}",
            "final": group["name"], "count": group["count"], "bytes": group["bytes"],
            "kind": group["kind"], "move_start": offset,
        })
        offset += group["count"]

    moves = []
    source_items = {row["path"]: row for row in items}
    for mapping in fresh["_mapping_items"]:
        item = source_items[mapping["source"]]
        final = Path(mapping["target"])
        target_name = mapping["target_name"]
        group_index = None if is_flat else group_indexes[str(final.parent)]
        stage = root_stage if is_flat else groups[group_index]["stage"]
        moves.append({
            "source": item["path"], "target": str(source / stage / target_name), "final": str(final),
            "identity": [item["dev"], item["ino"], item["bytes"], item["mtime_ns"]],
            "group": group_index, "target_name": target_name, "original_name": item["name"],
            "original_relative_path": os.path.relpath(item["path"], source),
            "final_relative_path": os.path.relpath(final, source),
        })
    manifest = {
        "schema_version": MANIFEST_VERSION, "job_id": job_id, "package": str(source),
        "media_package_root": str(media_package_root) if media_package_root is not None else None,
        "package_dev": dev, "package_ino": int(package_stat.st_ino),
        "input_fingerprint": fresh["input_fingerprint"], "operation": fresh["operation"],
        "root_stage": root_stage, "groups": groups, "moves": moves, "origin_directories": directories,
        **(organizer_scope or {}),
    }
    _validate_frozen_paths(manifest)
    if (len(_flat_rows(manifest)) if is_flat else len(moves)) != fresh["needed_moves"]:
        raise MediaPackageExecutionConflict("Frozen move count differs from reviewed preview")
    if fresh["operation"] in APPEND_MEDIA_OPERATIONS and len(moves) != len(items):
        raise MediaPackageExecutionConflict("Frozen append is missing numbered inputs")
    return manifest


def _manifest_checksum(manifest: dict) -> str:
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_frozen_manifest(path: Path, manifest: dict) -> None:
    """Exclusive, crash-safe publication on CONFIG_DIR; never overwrite."""
    if path.exists() or path.is_symlink():
        raise MediaPackageExecutionConflict("Frozen manifest path already exists")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    body = {"manifest": manifest, "checksum": _manifest_checksum(manifest)}
    if "organizer_mode" in manifest:
        # A killed Worker may leave a partial temporary file. A fresh,
        # exclusive temp file never adopts that content or replaces the final.
        fd, temporary = mkstemp(prefix=f".{path.name}.", dir=path.parent)
        staging = Path(temporary)
    else:
        staging = path.with_name(path.name + ".tmp")
        if os.path.lexists(staging):
            raise MediaPackageExecutionConflict("Untrusted partial manifest artifact exists")
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path, follow_symlinks=False)
        if "organizer_mode" in manifest:
            parent_fd = _open_folder(path.parent)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    finally:
        if os.path.lexists(staging):
            os.unlink(staging)


def load_frozen_manifest(path: Path, *, job_id: int, package: Path) -> dict:
    """Validate stored authority without rewriting, repairing or trusting it."""
    if path.is_symlink() or not path.is_file():
        raise MediaPackageExecutionConflict("Frozen manifest is missing or unsafe")
    try:
        with path.open("r", encoding="utf-8") as stream:
            body = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MediaPackageExecutionConflict(
            "Frozen manifest integrity mismatch: unreadable or invalid JSON"
        ) from exc
    return _validate_frozen_manifest_body(body, job_id=job_id, package=package)


def _validate_frozen_manifest_body(body, *, job_id: int, package: Path) -> dict:
    """Verify a decoded manifest against its expected execution and package."""
    if not isinstance(body, dict) or not isinstance(body.get("manifest"), dict):
        raise MediaPackageExecutionConflict(
            "Frozen manifest integrity mismatch: invalid manifest envelope"
        )
    manifest = body["manifest"]
    if body.get("checksum") != _manifest_checksum(manifest):
        raise MediaPackageExecutionConflict(
            "Frozen manifest integrity mismatch: SHA-256 checksum differs"
        )
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise MediaPackageExecutionConflict(
            "Frozen manifest integrity mismatch: schema version differs"
        )
    if manifest.get("job_id") != job_id:
        raise MediaPackageExecutionConflict(
            "Frozen manifest integrity mismatch: execution job ID differs"
        )
    if manifest.get("package") != str(package):
        raise MediaPackageExecutionConflict(
            "Frozen manifest integrity mismatch: package path differs from preview"
        )
    return manifest


def _entry(folder: Path, name: str):
    try:
        return _stat_entry(folder, name)
    except FileNotFoundError:
        return None


def _retire_link(source: Path, target: Path, source_fd: int, target_fd: int,
                 identity: list[int], fence: Callable[[], None], *, durable: bool = False) -> None:
    if durable:
        os.fsync(target_fd)
    fence()
    _check_file(os.stat(target.name, dir_fd=target_fd, follow_symlinks=False), identity, target)
    _check_file(os.stat(source.name, dir_fd=source_fd, follow_symlinks=False), identity, source)
    os.unlink(source.name, dir_fd=source_fd)


def _resume_link(intent: LinkIntent, source: Path, target: Path, identity: list[int],
                 fence: Callable[[], None]) -> bool:
    source_fd = _open_folder(source.parent)
    try:
        target_fd = _open_folder(target.parent)
        try:
            if not intent.matches(intent.binding(source_fd, source.name, target_fd, target.name, identity)):
                return False
            _retire_link(source, target, source_fd, target_fd, identity, fence, durable=True)
            return True
        finally:
            os.close(target_fd)
    finally:
        os.close(source_fd)


def _has_link_intent(intent: LinkIntent | None, source: str, target: str, identity: list[int]) -> bool:
    """Check whether a duplicate file binding belongs to an interrupted move."""
    if intent is None:
        return False
    before, after = Path(source), Path(target)
    source_fd = _open_folder(before.parent)
    try:
        target_fd = _open_folder(after.parent)
        try:
            return intent.matches(intent.binding(source_fd, before.name, target_fd, after.name, identity))
        finally:
            os.close(target_fd)
    finally:
        os.close(source_fd)


def _move_one(move: dict, *, lease_fence: Callable[[], None],
              ignore_final: bool = False, compat_hardlink: bool = False,
              source_replaced_by: list[int] | None = None,
              link_intent: LinkIntent | None = None) -> str:
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
        if source_replaced_by is not None:
            # An earlier group has safely published a different frozen file
            # at this old source pathname. Its exact manifest identity has
            # already been proved; never move/unlink the new published file.
            _check_file(src_stat, source_replaced_by, src)
            return "resumed"
        _check_file(src_stat, expected, src)
        if (link_intent is not None and stage_stat is not None and final_stat is None
                and _resume_link(link_intent, src, stage, expected, lease_fence)):
            return "resumed"
        # A source and target with identical inode can be an interrupted
        # COMPAT hardlink operation, but it can also be a pre-existing alias.
        # Without an independently committed per-file publication intent,
        # NEVER unlink a source in this ambiguous state. Require review.
        raise MediaPackageExecutionConflict(
            f"Both source and destination exist; manual review: {src}"
        )

    if source_replaced_by is not None:
        # Stage custody cannot be recovered by moving a new published file
        # back out of a prior group's final directory.
        raise MediaPackageExecutionConflict(
            f"Frozen stage is missing after source path reuse: {src}"
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
                if link_intent is not None:
                    link_intent.save(link_intent.binding(src_fd, src.name, dst_fd, stage.name, expected))
                    lease_fence()
                    _check_file(os.stat(src.name, dir_fd=src_fd, follow_symlinks=False), expected, src)
                os.link(src.name, stage.name, src_dir_fd=src_fd,
                        dst_dir_fd=dst_fd, follow_symlinks=False)
                _retire_link(src, stage, src_fd, dst_fd, expected, lease_fence, durable=link_intent is not None)
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


def _verify_group_contents(manifest: dict, group_index: int, directory: Path, *,
                           complete: bool = True) -> set[str]:
    """Verify every entry against the frozen group and return its matched keys."""
    group = manifest["groups"][group_index]
    exact = _is_luolcy_author(manifest)
    expected = {
        row["target_name"] if exact else row["target_name"].casefold(): row["identity"]
        for row in _group_files(manifest, group_index)
    }
    if len(expected) != group["count"]:
        raise MediaPackageExecutionConflict("Group filename collision in frozen manifest")
    fd = _open_folder(directory)
    try:
        _check_directory(os.fstat(fd), directory, manifest["package_dev"])
        seen = set()
        size = 0
        with os.scandir(fd) as entries:
            for entry in entries:
                key = entry.name if exact else entry.name.casefold()
                if key in seen or key not in expected:
                    message = ("Unrecognized file inside MediaPackage stage/group" if complete
                               else "Foreign entry in existing stage")
                    raise MediaPackageExecutionConflict(message)
                seen.add(key)
                st = entry.stat(follow_symlinks=False)
                _check_file(st, expected[key], directory / entry.name)
                size += int(st.st_size)
        if complete and (len(seen) != group["count"] or size != group["bytes"]):
            raise MediaPackageExecutionConflict("Group count/size is incomplete")
        return seen
    finally:
        os.close(fd)


def _frozen_original_directory(manifest: dict, path: Path) -> bool:
    """Prove a pre-existing target is an original, identity-bound input."""
    identity = manifest["origin_directories"].get(str(path))
    if identity is None:
        return False
    fd = _open_folder(path)
    try:
        st = os.fstat(fd)
        if [int(st.st_dev), int(st.st_ino)] != identity:
            raise MediaPackageExecutionConflict(
                "Previously scanned MediaPackage bucket directory was replaced"
            )
    finally:
        os.close(fd)
    return True


def _stage_repeated_work_bucket(manifest: dict, group_index: int,
                                lease_fence: Callable[[], None]) -> bool:
    """Stage an unchanged bucket as a directory, using the normal recovery path."""
    if manifest.get("organizer_mode") != "semantic":
        return False
    package = Path(manifest["package"])
    wrapper = package / package.name
    group = manifest["groups"][group_index]
    source = wrapper / group["final"]
    origins = manifest["origin_directories"]
    if str(source) not in origins or str(wrapper) not in origins or not all(
        Path(row["source"]) == source / row["target_name"]
        for row in _group_files(manifest, group_index)
    ):
        return False

    package_fd = _open_verified_package(manifest)
    try:
        wrapper_fd = _open_folder(wrapper)
        try:
            _verify_group_contents(manifest, group_index, source)
            lease_fence()
            opened = os.fstat(wrapper_fd)
            current = os.stat(wrapper.name, dir_fd=package_fd, follow_symlinks=False)
            bucket = os.stat(source.name, dir_fd=wrapper_fd, follow_symlinks=False)
            if ([opened.st_dev, opened.st_ino] != origins[str(wrapper)]
                    or [current.st_dev, current.st_ino] != origins[str(wrapper)]
                    or not stat.S_ISDIR(bucket.st_mode)
                    or [bucket.st_dev, bucket.st_ino] != origins[str(source)]):
                raise MediaPackageExecutionConflict("Original repeated work changed before staging")
            try:
                rename_noreplace_at(wrapper_fd, source.name, package_fd, group["stage"])
            except OSError as exc:
                if exc.errno != errno.EOPNOTSUPP:
                    raise
                # Use the existing file-by-file engine on mounts without directory rename.
                return False
        finally:
            os.close(wrapper_fd)
    finally:
        os.close(package_fd)
    return True


def _ensure_staging(manifest: dict, group_index: int,
                    lease_fence: Callable[[], None]) -> str:
    """Distinguish an old scanned bucket from an already-published output."""
    package = Path(manifest["package"])
    group = manifest["groups"][group_index]
    stage = package / group["stage"]
    final = package / group["final"]
    has_stage = os.path.lexists(stage)
    if os.path.lexists(final):
        if _compat_inspect_group(manifest, group_index) is not None:
            return "compat"
        if not has_stage:
            # A fully matching output is safe to reuse; all other occupants
            # must be independently proven original scanned input folders.
            try:
                _verify_group_contents(manifest, group_index, final)
            except MediaPackageExecutionConflict:
                if not _frozen_original_directory(manifest, final):
                    raise
            else:
                return "published"
        elif not _frozen_original_directory(manifest, final):
            raise MediaPackageExecutionConflict(
                "Both staging and foreign published directories exist"
            )
    if has_stage:
        _verify_group_contents(manifest, group_index, stage, complete=False)
        return "staging"
    if _stage_repeated_work_bucket(manifest, group_index, lease_fence):
        return "staging"
    lease_fence()
    fd = _open_folder(package)
    try:
        os.mkdir(group["stage"], mode=0o755, dir_fd=fd)
    finally:
        os.close(fd)
    return "staging"

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
    rows = _group_files(manifest, group_index)
    exact = {row["target_name"] for row in rows} if _is_luolcy_author(manifest) else None
    try:
        _check_directory(os.fstat(dst_fd), final, manifest["package_dev"])
        if not _compat_marker_matches(dst_fd, _COMPAT_OWNER_MARKER, data):
            return None
        done = _compat_marker_matches(dst_fd, _COMPAT_COMPLETE_MARKER, data)
        expected = {
            Path(row["final"]).name.casefold(): row["identity"]
            for row in rows
        }
        if len(expected) != len(rows):
            raise MediaPackageExecutionConflict("Frozen publication duplicate names")
        public_names: set[str] = set()
        with os.scandir(dst_fd) as entries:
            for entry in entries:
                if entry.name in (_COMPAT_OWNER_MARKER, _COMPAT_COMPLETE_MARKER):
                    continue
                key = entry.name.casefold()
                if key not in expected or key in public_names or (exact is not None and entry.name not in exact):
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
                    if key not in expected or key in stage_names or (exact is not None and entry.name not in exact):
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
            _, staged_names = _flat_stage_inspect(manifest, stage)
            if staged_names:
                return True
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
                if not _frozen_original_directory(manifest, published):
                    raise MediaPackageExecutionConflict(
                        "Both frozen stage and foreign final directory exist"
                    )
                # An untouched old bucket is still a frozen *source*, not a
                # partial publication. Only job-owned staged files prove custody.
                has_final = False
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


def _remove_empty_sources(manifest: dict, lease_fence: Callable[[], None], *,
                          only_under: set[Path] | None = None,
                          skip_finals: bool = False) -> int:
    """Remove only original, identity-matched and actually empty directories.

    'only_under' is used before publication solely for old destination
    buckets whose frozen contents have ALL been staged. After publication,
    output final paths are excluded so an old source name cannot cause the
    newly published folder to be mistaken for a disposable directory.
    """
    package = Path(manifest["package"])
    finals = ({package / group["final"] for group in manifest["groups"]}
              if skip_finals else set())
    removed = 0
    for name, identity in sorted(manifest["origin_directories"].items(),
                                 key=lambda entry: (-len(Path(entry[0]).parts), entry[0])):
        folder = Path(name)
        if not folder.is_relative_to(package) or folder == package:
            raise MediaPackageExecutionConflict("Unsafe original directory cleanup scope")
        if folder in finals:
            continue
        if only_under is not None and not any(
            folder == root or folder.is_relative_to(root) for root in only_under
        ):
            continue
        if folder.is_symlink():
            raise MediaPackageExecutionConflict("Original directory became a symlink")
        if not folder.exists():
            continue
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


def _retire_staged_destination_sources(
    manifest: dict, modes: list[str], lease_fence: Callable[[], None],
) -> int:
    """Free labels occupied exclusively by frozen, now-staged source folders.

    Never force-remove a foreign occupant, rename over another directory or
    delete a directory containing files. The published group owns the name
    only after a no-replace operation succeeds.
    """
    package = Path(manifest["package"])
    retired = {
        package / group["final"]
        for index, group in enumerate(manifest["groups"])
        if modes[index] == "staging"
        and str(package / group["final"]) in manifest["origin_directories"]
    }
    if not retired:
        return 0
    removed = _remove_empty_sources(
        manifest, lease_fence, only_under=retired,
    )
    for target in retired:
        if os.path.lexists(target):
            raise MediaPackageExecutionConflict(
                f"Original grouped destination is not safely empty: {target}"
            )
    return removed

_ROOT_READY_MARKER = ".nfc-publish-ready"


def _flat_rows(manifest: dict) -> list[dict]:
    if manifest["operation"] in APPEND_MEDIA_OPERATIONS:
        return [row for row in manifest["moves"] if row["source"] != row["final"]]
    return manifest["moves"]


def _root_finals_complete(manifest: dict) -> bool:
    """Recognize a previously published flat package only by EVERY frozen inode.

    During normal preflight some original root filenames may already be
    numbered, but the full expected final set cannot match a ready-to-rename
    package without all of its other source bindings having retired.
    """
    package = Path(manifest["package"])
    manifest_final_targets = {
        row["final"]: row["identity"] for row in manifest["moves"]
    }
    if len(manifest_final_targets) != len(manifest["moves"]):
        raise MediaPackageExecutionConflict("Duplicate flat final targets")
    for row in manifest["moves"]:
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


def _flat_stage_inspect(manifest: dict, stage: Path) -> tuple[bool, set[str]]:
    """Validate the flat stage and return its publish state and observed filenames."""
    rows = _flat_rows(manifest)
    exact = _is_luolcy_author(manifest)
    expected = {row["target_name"] if exact else row["target_name"].casefold(): row["identity"]
                for row in rows}
    if len(expected) != len(rows):
        raise MediaPackageExecutionConflict("Flat numbered destination collision")
    folder = _open_folder(stage)
    has_marker = False
    seen = set()
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
                key = entry.name if exact else entry.name.casefold()
                if key not in expected:
                    raise MediaPackageExecutionConflict("Foreign file in flat staging directory")
                _check_file(entry.stat(follow_symlinks=False),
                            expected[key], stage / entry.name)
                seen.add(entry.name)
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
    return has_marker, seen


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
                       lease_fence: Callable[[], None], link_intent: LinkIntent | None = None) -> str:
    name = Path(row["target"]).name
    before = _entry(stage, name)
    published = _entry(package, name)
    if before is None:
        _check_file(published, row["identity"], package / name)
        return "resumed"
    _check_file(before, row["identity"], stage / name)
    if published is not None:
        if (link_intent is not None
                and _resume_link(link_intent, stage / name, package / name, row["identity"], lease_fence)):
            return "resumed"
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
            if link_intent is not None:
                link_intent.save(link_intent.binding(stage_fd, name, package_fd, name, row["identity"]))
                lease_fence()
                _check_file(os.stat(name, dir_fd=stage_fd, follow_symlinks=False), row["identity"], stage / name)
            os.link(name, name, src_dir_fd=stage_fd,
                    dst_dir_fd=package_fd, follow_symlinks=False)
            _retire_link(stage / name, package / name, stage_fd, package_fd,
                         row["identity"], lease_fence, durable=link_intent is not None)
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


def _verify_append_scope(manifest: dict, package: Path) -> None:
    """Check the approved numbered files before staging or resuming publication."""
    if manifest["operation"] not in APPEND_MEDIA_OPERATIONS:
        return
    incoming = _flat_rows(manifest)
    source_folder = Path(incoming[0]["source"]).parent
    source_files = {Path(row["source"]).name: row["identity"] for row in incoming}
    expected = {row["target_name"]: row for row in manifest["moves"]}
    allowed = {*expected, source_folder.name, manifest["root_stage"]}
    package_fd = _open_verified_package(manifest)
    try:
        with os.scandir(package_fd) as entries:
            live = {entry.name: entry.stat(follow_symlinks=False) for entry in entries}
    finally:
        os.close(package_fd)
    siblings = live.keys() - allowed
    if manifest["operation"] == APPEND_MEDIA_WRAPPER and manifest.get("local_scope") is not None:
        # A local classification append can coexist with independent named works.
        occupied = {name.casefold() for name in allowed}
        siblings = {name for name in siblings if name.casefold() in occupied or name.casefold().startswith(".nfc-")
                    or not stat.S_ISDIR(live[name].st_mode) or live[name].st_dev != manifest["package_dev"]}
    if siblings:
        raise MediaPackageExecutionConflict("Media append has unreviewed entries in its root")
    for name, row in expected.items():
        if row["source"] == row["final"] or name in live:
            _check_file(live.get(name), row["identity"], package / name)
    if source_folder.name not in live:
        return
    fd = _open_folder(source_folder)
    try:
        info = os.fstat(fd)
        if [info.st_dev, info.st_ino] != manifest["origin_directories"].get(str(source_folder)):
            raise MediaPackageExecutionConflict("Video append source folder changed")
        with os.scandir(fd) as entries:
            for entry in entries:
                if entry.name not in source_files:
                    raise MediaPackageExecutionConflict("Video append source folder has unreviewed entries")
                _check_file(entry.stat(follow_symlinks=False), source_files[entry.name], source_folder / entry.name)
    finally:
        os.close(fd)


def _verify_append_file_bindings(manifest: dict, *, publishing: bool) -> None:
    """Check every incoming video before proceeding with the current phase."""
    if manifest["operation"] not in APPEND_MEDIA_OPERATIONS:
        return
    for row in _flat_rows(manifest):
        staged = Path(row["target"])
        staged_info = _entry(staged.parent, staged.name)
        if staged_info is not None:
            _check_file(staged_info, row["identity"], staged)
        else:
            other = Path(row["final"] if publishing else row["source"])
            _check_file(_entry(other.parent, other.name), row["identity"], other)


def _execute_flat_manifest(manifest: dict, lease_fence: Callable[[], None],
                           progress: Callable[[int, int], None] | None,
                           link_intent: LinkIntent | None = None) -> dict:
    package = Path(manifest["package"])
    stage = package / manifest["root_stage"]
    total = len(_flat_rows(manifest))
    _verify_append_scope(manifest, package)
    if _root_finals_complete(manifest):
        if link_intent is not None and stage.exists() and _flat_stage_inspect(manifest, stage)[0]:
            for row in _flat_rows(manifest):
                _publish_flat_file(row, stage, package, lease_fence, link_intent)
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
    marked, _ = _flat_stage_inspect(manifest, stage)
    completed = 0
    recovered = 0
    if not marked:
        _verify_append_file_bindings(manifest, publishing=False)
        for i, row in enumerate(_flat_rows(manifest), 1):
            outcome = _move_one(row, lease_fence=lease_fence, ignore_final=True, link_intent=link_intent)
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

    _verify_append_scope(manifest, package)
    _verify_append_file_bindings(manifest, publishing=True)
    if _is_luolcy_author(manifest):
        _verify_luolcy_author_scope(manifest, package, link_intent=link_intent)
    for row in _flat_rows(manifest):
        _publish_flat_file(row, stage, package, lease_fence, link_intent)
    _remove_flat_stage(manifest, stage, lease_fence)
    return {"files_moved": completed, "files_reconciled": recovered,
            "groups_published": 0}


def _validate_luolcy_lift_groups(manifest: dict) -> set[tuple[str, str]]:
    """Validate exact group names, one complete numbered source and unique bucket ordinals."""
    slots: set[tuple[str, str]] = set()
    for index, group in enumerate(manifest["groups"]):
        name, kind = group["final"], group["kind"]
        slot = _luolcy_bucket_slot(name)
        if slot is None:
            raise MediaPackageExecutionConflict("Invalid frozen Luolcy bucket name")
        ordinal = slot[1]
        stem = kind if ordinal == "0" else f"{kind}_{ordinal}"
        rows = _group_files(manifest, index)
        paths = [Path(row["source"]) for row in rows]
        expected_numbers = {f"{number:03d}" for number in range(1, group["count"] + 1)}
        if (name != f"{stem} [{group['count']} {_size_label(group['bytes'])}]"
                or slot in slots or len({path.parent for path in paths}) != 1
                or {path.stem for path in paths} != expected_numbers
                or sum(row["identity"][2] for row in rows) != group["bytes"]):
            raise MediaPackageExecutionConflict("Invalid frozen Luolcy bucket contents")
        slots.add(slot)
    return slots


def _validate_luolcy_sources(manifest: dict, package: Path) -> None:
    """Constrain frozen inputs to reviewed classifications or a complete set of media leaves."""
    origins = manifest.get("origin_directories")
    siblings = manifest.get("luolcy_author_siblings", {})
    if not isinstance(origins, dict) or not isinstance(siblings, dict):
        raise MediaPackageExecutionConflict("Invalid frozen Luolcy directory inventory")

    expected_origins = set()
    direct_kinds: set[str] = set()
    child_kinds: dict[str, set[str]] = {}
    leaf_origins: set[Path] = set()
    nested_buckets: dict[Path, list[dict]] = {}
    has_unlabelled_origin = False
    has_short_video_origin = False
    moving_names = {group["final"].casefold() for group in manifest["groups"]}
    lifting = manifest["operation"] == LIFT_LUOLCY_BUCKETS
    lift_slots = _validate_luolcy_lift_groups(manifest) if lifting else set()
    for row in manifest["moves"]:
        source = Path(row["source"])
        top, *children = source.relative_to(package).parts
        moving_names.add(top.casefold())
        kind = _classify(source.name)
        if kind not in {"P", "V"} or source.name.casefold().startswith(".nfc-"):
            raise MediaPackageExecutionConflict("Frozen Luolcy input must be a media file")
        group_index = row["group"]
        if group_index is None:
            moving_names.add(row["target_name"].casefold())
        elif manifest["groups"][group_index]["kind"] != kind:
            raise MediaPackageExecutionConflict("Frozen Luolcy input is in the wrong group")
        if lifting:
            if (len(children) != 2 or group_index is None or row["target_name"] != source.name
                    or children[0] != manifest["groups"][group_index]["final"]
                    or _luolcy_classification_kind(top) != kind or _luolcy_bucket_slot(top)):
                raise MediaPackageExecutionConflict("Invalid frozen Luolcy bucket lift path")
            expected_origins.update((str(package / top), str(source.parent)))
            continue
        if not children:
            direct_kinds.add(kind)
            continue
        classification = _luolcy_classification_kind(top)
        # Short videos are an explicit flat V input. Legacy manifests with
        # other contents still have to pass the existing unlabelled-leaf check.
        if top == _LUOLCY_SHORT_VIDEO_FOLDER and kind == "V" and len(children) == 1:
            classification = "V"
            has_short_video_origin = True
        if (classification not in {None, kind, "PV"} or len(children) > 2
                or top.casefold().startswith(".nfc-") or "\x00" in top):
            raise MediaPackageExecutionConflict("Invalid frozen Luolcy classification path")
        if classification is None:
            has_unlabelled_origin = True
        child_kinds.setdefault(top, set()).add(kind)
        expected_origins.add(str(package / top))
        if len(children) == 1:
            leaf_origins.add(source.parent)
            continue
        if classification == kind and not _luolcy_bucket_slot(top):
            size = row["identity"][2]
            if type(size) is not int or size < 0:
                raise MediaPackageExecutionConflict("Invalid frozen Luolcy bucket file size")
            nested_buckets.setdefault(source.parent, []).append({"name": source.name, "kind": kind, "bytes": size})
        elif classification != "PV" or _luolcy_classification_kind(children[0]) != kind:
            raise MediaPackageExecutionConflict("Invalid frozen Luolcy classification path")
        expected_origins.add(str(source.parent))

    # Verify the original shell from the frozen rows, even after its files have been staged.
    if any(path.parent in leaf_origins or not _luolcy_verified_bucket(path.name, rows)
           for path, rows in nested_buckets.items()):
        raise MediaPackageExecutionConflict("Invalid frozen Luolcy nested bucket contents")
    if origins.keys() != expected_origins:
        raise MediaPackageExecutionConflict("Frozen Luolcy origins differ from its media sources")
    if has_short_video_origin and not direct_kinds:
        raise MediaPackageExecutionConflict("Frozen Luolcy short-video folder requires direct author media")
    # Promotion requires every author child to be an immediate media leaf.
    if has_unlabelled_origin and (siblings or len(expected_origins) != len(child_kinds)
                                  or not _luolcy_leaf_promotion(direct_kinds, child_kinds)):
        raise MediaPackageExecutionConflict("Invalid frozen Luolcy author media leaves")
    for name in siblings:
        if not isinstance(name, str):
            raise MediaPackageExecutionConflict("Invalid frozen Luolcy named work")
        folded = name.casefold()
        if (not name or Path(name).name != name or name in {".", ".."} or "\x00" in name
                or folded.startswith(".nfc-") or folded in moving_names
                or (expected_origins and _luolcy_batch_boundary(name))):
            raise MediaPackageExecutionConflict("Invalid frozen Luolcy named work")
        if lifting and _luolcy_bucket_slot(name) in lift_slots:
            raise MediaPackageExecutionConflict("Frozen Luolcy bucket ordinal is already occupied")
        moving_names.add(folded)
    if any(not isinstance(identity, list) or len(identity) != 2
           or identity[0] != manifest["package_dev"]
           or type(identity[1]) is not int or identity[1] <= 0
           for inventory in (origins, siblings) for identity in inventory.values()):
        raise MediaPackageExecutionConflict("Invalid frozen Luolcy directory identity")


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
    luolcy_author = _is_luolcy_author(manifest)
    local_scope = manifest.get("local_scope")
    if local_scope is not None:
        from app.batch.media_organizer_planner import DIRECT_MEDIA_SCOPE

        kinds = manifest.get("local_media_kinds")
        if (local_scope != DIRECT_MEDIA_SCOPE or manifest.get("organizer_mode") != "semantic"
                or manifest.get("whole_author") or not isinstance(kinds, list)
                or not 1 <= len(kinds) <= 2 or any(kind not in ("P", "V") for kind in kinds)
                or kinds != sorted(set(kinds))):
            raise MediaPackageExecutionConflict("Invalid frozen direct media scope")
    lifting = manifest.get("operation") == LIFT_LUOLCY_BUCKETS
    if lifting and (not luolcy_author or not manifest.get("groups")
                    or not isinstance(manifest.get("luolcy_root_fingerprint"), str)):
        raise MediaPackageExecutionConflict("Invalid frozen Luolcy bucket lift scope")
    if luolcy_author and (
        not manifest.get("media_package_root")
        or manifest.get("local_media_kinds")
        or manifest.get("operation") not in {
            "flatten_pure_media", "bucket_pure_media", "sort_mixed_media", LIFT_LUOLCY_BUCKETS,
        }
    ):
        raise MediaPackageExecutionConflict("Invalid frozen Luolcy author scope")
    if root_stage is not None:
        if (manifest.get("operation") not in _FLAT_OPERATIONS
                or root_stage != f".nfc-media_package-stage-{manifest['job_id']}-root"
                or manifest.get("groups")):
            raise MediaPackageExecutionConflict("Invalid frozen flat staging scope")
    elif manifest.get("operation") in _FLAT_OPERATIONS:
        raise MediaPackageExecutionConflict("Missing flat staging authority")
    kind_indexes = {"P": 0, "V": 0}
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
        if luolcy_author:
            ordinal = kind_indexes.get(group["kind"])
            if ordinal is None or not isinstance(group.get("bytes"), int) or group["bytes"] < 0:
                raise MediaPackageExecutionConflict("Invalid frozen Luolcy author group")
            if not lifting:
                stem = group["kind"] if ordinal == 0 else f"{group['kind']}_{ordinal}"
                if group["final"] != f"{stem} [{group['count']} {_size_label(group['bytes'])}]":
                    raise MediaPackageExecutionConflict("Invalid frozen Luolcy author bucket name")
                kind_indexes[group["kind"]] += 1

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
                or organizer_extension(target_name) != organizer_extension(src.name)
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
        if manifest["operation"] in APPEND_MEDIA_OPERATIONS:
            moving = _flat_rows(manifest)
            source_folders = {Path(row["source"]).parent for row in moving}
            invalid_count = (manifest["operation"] in APPEND_VIDEO_OPERATIONS
                             and (manifest["operation"] == APPEND_SINGLE_VIDEO) != (len(moving) == 1))
            if (not moving or len(moving) == len(rows) or len(source_folders) != 1
                    or any(folder.parent != package for folder in source_folders)
                    or invalid_count):
                raise MediaPackageExecutionConflict("Invalid frozen media append")
            if (manifest["operation"] == APPEND_MEDIA_WRAPPER
                    and (manifest.get("organizer_mode") != "semantic" or manifest.get("whole_author"))):
                raise MediaPackageExecutionConflict("Invalid frozen wrapper append scope")
    else:
        covered = sum(group["count"] for group in manifest["groups"])
        if covered != len(rows):
            raise MediaPackageExecutionConflict("Frozen grouped move count is inconsistent")
        for index, group in enumerate(manifest["groups"]):
            part = rows[group["move_start"]:group["move_start"] + group["count"]]
            if len({row["target_name"].casefold() for row in part}) != len(part):
                raise MediaPackageExecutionConflict("Frozen group target filename collision")
    if luolcy_author:
        _validate_luolcy_sources(manifest, package)


def _exact_published_snapshot(manifest: dict, live: list[dict]) -> bool:
    """Only a complete verified final layout can bypass the original snapshot."""
    if not manifest["groups"] or len(live) != len(manifest["moves"]):
        return False
    expected = {
        row["final"]: tuple(row["identity"]) for row in manifest["moves"]
    }
    if len(expected) != len(manifest["moves"]):
        return False
    for row in live:
        if expected.get(row["path"]) != (
            row["dev"], row["ino"], row["bytes"], row["mtime_ns"],
        ):
            return False
    try:
        for index, group in enumerate(manifest["groups"]):
            _verify_group_contents(manifest, index,
                                   Path(manifest["package"]) / group["final"])
    except (MediaPackageExecutionConflict, OSError, ValueError):
        return False
    return True


def _live_organizer_snapshot(manifest: dict, package: Path, mode: str) -> list[dict]:
    """Recheck whole-author eligibility and destination occupancy before the first write."""
    from app.batch.media_organizer_planner import preview_organizing_unit, walk_organizing_unit

    options = {
        "mode": mode,
        "media_package_root": Path(manifest["media_package_root"]) if manifest.get("media_package_root") else None,
        "quarantine_root": Path(manifest["quarantine_root"]) if manifest.get("quarantine_root") else None,
        "local_media_kinds": tuple(manifest.get("local_media_kinds", ())),
        "local_scope": manifest.get("local_scope"),
    }
    whole_author = manifest.get("whole_author", False)
    numbered_photos = manifest.get("operation") == PROMOTE_NUMBERED_PHOTO_GROUPS
    if whole_author or numbered_photos:
        preview = preview_organizing_unit(package, allowed_roots=[package], include_items=True, **options)
        same_operation = preview.get("operation") == manifest.get("operation")
        if same_operation and (
            (whole_author and preview.get("whole_author") and preview["status"] == "ready")
            or (numbered_photos and preview["status"] in {"ready", "already_organized"})
        ):
            return preview["_snapshot_items"]
    live = list(walk_organizing_unit(package, whole_author=whole_author or numbered_photos, **options))
    # A grouped plan can have published every output before its final cleanup ran.
    if (whole_author or numbered_photos) and not _exact_published_snapshot(manifest, live):
        raise MediaPackageExecutionConflict("Organizing scope or destination changed since preview")
    return live


def _verify_recovery_protection(manifest: dict, package: Path) -> None:
    """Keep approved staging recoverable without crossing a retargeted protection boundary."""
    from app.batch.media_organizer_planner import _resolved_protected_roots

    mode = manifest.get("organizer_mode")
    if mode is None:
        return
    media_root = manifest.get("media_package_root") if mode == "semantic" else None
    quarantine = manifest.get("quarantine_root")
    roots = _resolved_protected_roots(
        Path(media_root) if media_root else None, Path(quarantine) if quarantine else None,
    )
    for root in roots:
        protected_inside = root.is_relative_to(package) and (
            _is_luolcy_author(manifest) or any(
                Path(row[key]).is_relative_to(root) for row in manifest["moves"]
                for key in ("source", "target", "final")
            )
        )
        if package.is_relative_to(root) or protected_inside:
            raise MediaPackageExecutionConflict(f"Protected organizer scope changed since preview: {root}")


def _scan_luolcy_origin(directory: Path, origins: dict[str, list[int]],
                        sources: dict[str, list[int]], live_sources: set[str]) -> None:
    """Verify every live entry in a frozen Luolcy source directory."""
    fd = _open_folder(directory)
    try:
        info = os.fstat(fd)
        if [info.st_dev, info.st_ino] != origins[str(directory)]:
            raise MediaPackageExecutionConflict(f"Luolcy source directory changed: {directory}")
        with os.scandir(fd) as entries:
            for entry in entries:
                path = directory / entry.name
                if str(path) in origins:
                    _scan_luolcy_origin(path, origins, sources, live_sources)
                else:
                    expected = sources.get(str(path))
                    if expected is None:
                        raise MediaPackageExecutionConflict(f"Unreviewed entry in Luolcy source directory: {path}")
                    _check_file(entry.stat(follow_symlinks=False), expected, path)
                    live_sources.add(str(path))
    finally:
        os.close(fd)


def _verify_luolcy_file_bindings(rows: list[dict], sources: set[str], targets: set[str],
                                 finals: set[str], *, flat_ready: bool,
                                 link_intent: LinkIntent | None) -> None:
    """Require every frozen file to have an original or verified recovery binding."""
    for row in rows:
        source, target, final = row["source"], row["target"], row["final"]
        original = source in sources
        staged = target in targets
        public = final in finals
        if not (original or staged or public):
            raise MediaPackageExecutionConflict(f"Frozen Luolcy input is missing: {source}")
        if original and (public or flat_ready):
            raise MediaPackageExecutionConflict(f"Original Luolcy input still exists: {source}")
        if staged and original and not _has_link_intent(link_intent, source, target, row["identity"]):
            raise MediaPackageExecutionConflict(f"Unowned Luolcy source and staging link: {source}")
        if staged and public and flat_ready and not _has_link_intent(link_intent, target, final, row["identity"]):
            raise MediaPackageExecutionConflict(f"Unowned Luolcy staging and publication link: {final}")


def _verify_luolcy_author_scope(manifest: dict, package: Path, *, completed: bool = False,
                               link_intent: LinkIntent | None = None) -> None:
    """Verify the author root and account for every file in source, stage or output."""
    _verify_recovery_protection(manifest, package)
    sources = {row["source"]: row["identity"] for row in manifest["moves"]}
    flat_finals = {row["final"]: row["identity"] for row in manifest["moves"]
                   if row["group"] is None}
    origins = manifest["origin_directories"]
    siblings = manifest.get("luolcy_author_siblings", {})
    groups = {group["final"]: index for index, group in enumerate(manifest["groups"])}
    stages = {group["stage"] for group in manifest["groups"]}
    root_stage = manifest["root_stage"]
    if root_stage is not None:
        stages.add(root_stage)

    lifting = manifest["operation"] == LIFT_LUOLCY_BUCKETS
    preserved_media = []
    root_files = {}
    possible_groups = {}
    live_stages = set()
    live_siblings = set()
    live_origins = set()
    live_sources = set()
    fd = _open_luolcy_author(package, Path(manifest["media_package_root"]))
    try:
        _check_directory(os.fstat(fd), package, manifest["package_dev"])
        with os.scandir(fd) as entries:
            for entry in entries:
                name = entry.name
                path = package / name
                info = entry.stat(follow_symlinks=False)
                if name in stages:
                    _check_directory(info, path, manifest["package_dev"])
                    live_stages.add(name)
                elif name in groups:
                    _check_directory(info, path, manifest["package_dev"])
                    possible_groups[name] = [info.st_dev, info.st_ino]
                elif name in siblings:
                    _check_directory(info, path, manifest["package_dev"])
                    if [info.st_dev, info.st_ino] != siblings[name]:
                        raise MediaPackageExecutionConflict(f"Luolcy named work changed: {path}")
                    live_siblings.add(name)
                elif str(path) in origins:
                    _scan_luolcy_origin(path, origins, sources, live_sources)
                    live_origins.add(name)
                elif (lifting and stat.S_ISREG(info.st_mode) and info.st_dev == manifest["package_dev"]
                      and not name.casefold().startswith(".nfc-") and (kind := _classify(name)) in {"P", "V"}):
                    preserved_media.append(_author_media_row(path, info, kind))
                elif not lifting and stat.S_ISREG(info.st_mode):
                    root_files[str(path)] = _identity(info)
                else:
                    raise MediaPackageExecutionConflict(f"Unreviewed entry in Luolcy author root: {path}")
    finally:
        os.close(fd)
    if live_siblings != siblings.keys():
        raise MediaPackageExecutionConflict("A reviewed Luolcy named work is missing")
    if lifting and _input_fingerprint(preserved_media, package) != manifest["luolcy_root_fingerprint"]:
        raise MediaPackageExecutionConflict("Reviewed Luolcy author root files changed")

    live_targets = set()
    live_finals = set()
    published_groups = set()
    compatible_publication = False
    for name, index in groups.items():
        stage_name = manifest["groups"][index]["stage"]
        stage = package / stage_name
        final = package / name
        has_stage = stage_name in live_stages
        if has_stage:
            filenames = _verify_group_contents(manifest, index, stage, complete=False)
            live_targets.update(str(stage / filename) for filename in filenames)
        if name not in possible_groups:
            continue
        evidence = _compat_inspect_group(manifest, index) if not completed else None
        if evidence is not None:
            live_finals.update(row["final"] for row in _group_files(manifest, index)
                               if row["target_name"].casefold() in evidence["public_names"])
            compatible_publication = True
            continue
        is_origin = possible_groups[name] == origins.get(str(final))
        if not has_stage:
            try:
                filenames = _verify_group_contents(manifest, index, final)
            except MediaPackageExecutionConflict:
                if not is_origin:
                    raise
            else:
                live_finals.update(str(final / filename) for filename in filenames)
                published_groups.add(name)
                continue
        if not is_origin:
            raise MediaPackageExecutionConflict("Frozen stage and independent Luolcy bucket both exist")
        _scan_luolcy_origin(final, origins, sources, live_sources)
        live_origins.add(name)

    flat_ready = False
    if root_stage in live_stages:
        stage = package / root_stage
        flat_ready, filenames = _flat_stage_inspect(manifest, stage)
        live_targets.update(str(stage / filename) for filename in filenames)

    # Without a ready marker, flat root entries still belong to the original
    # inventory. A complete final layout can also be verified after stage cleanup.
    published = (not live_stages and not compatible_publication
                 and published_groups == groups.keys() and root_files == flat_finals)
    for path, identity in root_files.items():
        if flat_ready or published:
            expected = flat_finals.get(path)
            live_finals.add(path)
        else:
            expected = sources.get(path)
            live_sources.add(path)
        if identity != expected:
            raise MediaPackageExecutionConflict(f"Unreviewed entry in Luolcy author root: {path}")

    # A group with the complete frozen output may have been left in place,
    # but a new published directory needs either recovery evidence or a full result.
    if not (published or live_stages or compatible_publication) and any(
        possible_groups[name] != origins.get(str(package / name)) for name in published_groups
    ):
        raise MediaPackageExecutionConflict("Luolcy author inputs changed since the frozen preview")
    _verify_luolcy_file_bindings(manifest["moves"], live_sources, live_targets, live_finals,
                                flat_ready=flat_ready, link_intent=link_intent)
    if completed and (not published or live_origins):
        raise MediaPackageExecutionConflict("Luolcy author result differs from the frozen layout")


def _verify_package_snapshot(manifest: dict, package: Path) -> None:
    """Verify the original file inventory or existing recovery evidence."""
    # An old P/V directory is not recovery evidence merely because its
    # pathname equals a proposed final. Trust only owned stage names, verified
    # compatible-publication witnesses, or an exact complete final snapshot.
    root_stage = manifest.get("root_stage")
    if root_stage:
        recovery_artifact = (
            (package / root_stage).exists() or _root_finals_complete(manifest)
        )
    else:
        recovery_artifact = any(
            os.path.lexists(package / group["stage"])
            or _compat_inspect_group(manifest, index) is not None
            for index, group in enumerate(manifest["groups"])
        )
    if recovery_artifact:
        _verify_recovery_protection(manifest, package)
        return
    try:
        mode = manifest.get("organizer_mode")
        live = (list(_walk_package(package)) if mode is None
                else _live_organizer_snapshot(manifest, package, mode))
    except (OSError, ValueError) as exc:
        raise MediaPackageExecutionConflict(
            f"Unsafe package changed since frozen preview: {exc}"
        ) from exc
    if (_input_fingerprint(live, package) != manifest["input_fingerprint"]
            and not _exact_published_snapshot(manifest, live)):
        raise MediaPackageExecutionConflict(
            "Package changed since frozen preview; refusing file mutation"
        )


def execute_frozen_manifest(manifest: dict, *, lease_fence: Callable[[], None],
                            progress: Callable[[int, int], None] | None = None,
                            allow_fuse_compat: bool = False,
                            link_intent: LinkIntent | None = None) -> dict:
    """Run one package idempotently; the caller owns lease checkpoints/recovery."""
    package = Path(manifest["package"])
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise MediaPackageExecutionConflict("Unsupported frozen manifest version")
    _validate_frozen_paths(manifest)
    luolcy_author = _is_luolcy_author(manifest)
    if luolcy_author:
        try:
            _verify_luolcy_author_scope(manifest, package, link_intent=link_intent)
        except OSError as exc:
            raise MediaPackageExecutionConflict(f"Unsafe Luolcy author directory: {exc}") from exc
    if not allow_fuse_compat:
        for index in range(len(manifest["groups"])):
            if _compat_inspect_group(manifest, index) is not None:
                raise MediaPackageExecutionConflict(
                    "FUSE compatibility recovery requires explicit operator opt-in"
                )
    os.close(_open_verified_package(manifest))
    if not luolcy_author:
        _verify_package_snapshot(manifest, package)
    if manifest.get("root_stage"):
        result = _execute_flat_manifest(manifest, lease_fence, progress, link_intent)
        result["empty_dirs_removed"] = _remove_empty_sources(manifest, lease_fence)
        if luolcy_author:
            _verify_luolcy_author_scope(manifest, package, completed=True)
        result["total_files"] = len(manifest["moves"])
        result["package"] = str(package)
        return result
    group_modes = [
        _ensure_staging(manifest, index, lease_fence)
        for index in range(len(manifest["groups"]))
    ]
    # Previously published buckets can reuse original source pathnames
    # from rows still in staging. The reoccupied paths are authorized only
    # by the exact frozen output identity, never by a basename alone.
    published_identities = {
        row["final"]: row["identity"]
        for row in manifest["moves"]
        if group_modes[row["group"]] == "published"
    }
    for group_index, mode in enumerate(group_modes):
        if mode == "compat":
            evidence = _compat_inspect_group(manifest, group_index)
            if evidence is None:
                raise MediaPackageExecutionConflict(
                    "Authenticated grouped publication witness disappeared"
                )
            for row in _group_files(manifest, group_index):
                if row["target_name"].casefold() in evidence["public_names"]:
                    published_identities[row["final"]] = row["identity"]
    completed = recovered = 0
    total = len(manifest["moves"])
    for index, row in enumerate(manifest["moves"], start=1):
        mode = group_modes[row["group"]]
        if mode in ("published", "compat"):
            # Every frozen file identity was already checked in the verified
            # output or authenticated compatible-publication witness.
            recovered += 1
        else:
            # The public label may still contain original inputs. During
            # staging it is NEVER authority for a file's final destination.
            result = _move_one(
                row, lease_fence=lease_fence, ignore_final=True,
                source_replaced_by=published_identities.get(row["source"]),
                link_intent=link_intent,
            )
            completed += result == "moved"
            recovered += result != "moved"
        if progress and (index % 25 == 0 or index == total):
            progress(index, total)
    if luolcy_author:
        _verify_luolcy_author_scope(manifest, package)
    retired = _retire_staged_destination_sources(
        manifest, group_modes, lease_fence,
    )
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
    cleaned = _remove_empty_sources(manifest, lease_fence, skip_finals=True)
    if luolcy_author:
        _verify_luolcy_author_scope(manifest, package, completed=True)
    return {
        "files_moved": completed, "files_reconciled": recovered,
        "groups_published": published, "empty_dirs_removed": retired + cleaned,
        "total_files": total, "package": str(package),
    }
