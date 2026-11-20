"""Frozen-file staging with exclusive custody and fail-closed reconciliation.

The guarded execution Worker calls this module only after immutable freeze.
In deferred V1.6 jobs the stage is an exclusive inode-bound hardlink; the
original source pathname is never renamed or unlinked. Legacy synthetic code
paths retain historical behavior, but are never called by the V1.6 Worker.
"""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from typing import Callable

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_execution import MediaPackageExecutionConflict
from app.fs_ops import rename_noreplace_at
from app.batch.media_organizer_fd_link import link_pinned_inode_noreplace
from app.batch.media_organizer_execution import (
    _absolute_literal, validate_execution_preflight,
    ExecutionPreflightError,
)
from app.batch.media_organizer_manifest import (
    _checksum, load_frozen_preview_manifest, FrozenPreviewError,
)
from app.batch.media_organizer_planner import _check_scope

_OWNER = ".nfc-stage-authority"
_COMPLETE = ".nfc-stage-complete"
_MAX_MARKER = 256


class StagingConflict(ValueError):
    """Cannot prove exclusive custody of the frozen stage or a source file."""


def _authority(manifest: dict) -> bytes:
    return f"{manifest['job_id']}\n{_checksum(manifest)}\n".encode("ascii")


def _entry(folder_fd: int, name: str):
    try:
        return os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _check_identity(info, identity: list[int], path: Path) -> None:
    if (info is None or not stat.S_ISREG(info.st_mode)
            or [int(info.st_dev), int(info.st_ino), int(info.st_size),
                int(info.st_mtime_ns)] != identity):
        raise StagingConflict(f"frozen source or stage identity changed: {path}")


def _assert_private_stage_fd(stage_fd: int) -> os.stat_result:
    """Require a private, Worker-owned staging directory at each entry point.

    This is necessary but NEVER sufficient evidence of exclusive namespace
    custody: another same-UID process, root or an NAS-mapped service may still
    modify the stage. SEC-12 grouped publication remains blocked regardless.
    """
    st = os.fstat(stage_fd)
    if (not stat.S_ISDIR(st.st_mode)
            or int(st.st_uid) != os.geteuid()
            or (stat.S_IMODE(st.st_mode) & 0o077) != 0):
        raise StagingConflict(
            "private stage directory owner or permissions are unsafe"
        )
    return st


def _write_marker(stage_fd: int, name: str, expected: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(name, flags, 0o600, dir_fd=stage_fd)
    with os.fdopen(fd, "wb") as out:
        out.write(expected)
        out.flush()
        os.fsync(out.fileno())
    os.fsync(stage_fd)


def _read_marker(stage_fd: int, name: str, expected: bytes) -> bool:
    try:
        # A replaced witness may be a FIFO; reject its type without waiting.
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=stage_fd)
    except FileNotFoundError:
        return False
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_MARKER:
            raise StagingConflict(f"untrusted stage marker: {name}")
        value = stream.read(_MAX_MARKER + 1)
    if value != expected:
        raise StagingConflict(f"stage owner marker mismatch: {name}")
    return True


def _move_one(move: dict, *, lease_fence: Callable[[], None],
              ignore_final: bool, stage_binding: tuple[int, int],
              stage_witness: bytes, preserve_source: bool = False) -> str:
    """Use a PINNED verified private directory FD for the actual mutation.

    The existing generic file mover reopens its destination pathname inside
    the operation, which would allow a name swap after preflight. This
    specialized mover keeps the verified stage FD through rename/link and
    never writes into a similarly named foreign directory.
    """
    if not ignore_final:
        raise StagingConflict("staging mover cannot publish final paths")
    src = Path(move["source"])
    target = Path(move["target"])
    identity = move["identity"]
    src_fd = _open_directory_nofollow(src.parent)
    try:
        stage_fd = _open_directory_nofollow(target.parent)
        try:
            unit_fd = _open_directory_nofollow(target.parent.parent)
            try:
                def check_stage_binding() -> None:
                    live = _assert_private_stage_fd(stage_fd)
                    binding = _entry(unit_fd, target.parent.name)
                    if (binding is None or not stat.S_ISDIR(binding.st_mode)
                            or (int(live.st_dev), int(live.st_ino)) != stage_binding
                            or (int(binding.st_dev), int(binding.st_ino)) != stage_binding):
                        raise StagingConflict("private stage directory binding changed")
                    if not _read_marker(stage_fd, _OWNER, stage_witness):
                        raise StagingConflict("private staging owner witness is missing")

                source_file_fd = None
                try:
                    check_stage_binding()
                    _check_identity(_entry(src_fd, src.name), identity, src)
                    if _entry(stage_fd, target.name) is not None:
                        raise StagingConflict("private stage target unexpectedly occupied")
                    if int(os.fstat(stage_fd).st_dev) != identity[0]:
                        raise StagingConflict("cross-filesystem stage refused")
                    if preserve_source:
                        # The FD is pinned BEFORE the last name check. A writer
                        # replacing src.name cannot redirect the following link.
                        # A raced FIFO must not block before fstat rejects it.
                        source_file_fd = os.open(
                            src.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                            getattr(os, "O_CLOEXEC", 0), dir_fd=src_fd,
                        )
                        opened = os.fstat(source_file_fd)
                        if (not stat.S_ISREG(opened.st_mode) or
                                [int(opened.st_dev), int(opened.st_ino),
                                 int(opened.st_size), int(opened.st_mtime_ns)] != identity):
                            raise StagingConflict("opened source inode changed since freeze")
                    lease_fence()
                    check_stage_binding()
                    _check_identity(_entry(src_fd, src.name), identity, src)
                    if preserve_source:
                        # No source rename and NO source unlink. Retain the
                        # original name until independently audited cleanup.
                        link_pinned_inode_noreplace(
                            source_file_fd, stage_fd, target.name,
                        )
                    else:
                        # Historical synthetic legacy path only. The production
                        # Worker MUST stamp cleanup_policy=deferred.
                        try:
                            rename_noreplace_at(src_fd, src.name, stage_fd, target.name)
                        except OSError as exc:
                            if exc.errno != errno.EOPNOTSUPP:
                                raise
                            os.link(src.name, target.name, src_dir_fd=src_fd,
                                    dst_dir_fd=stage_fd, follow_symlinks=False)
                            _check_identity(_entry(stage_fd, target.name), identity, target)
                            _check_identity(_entry(src_fd, src.name), identity, src)
                            lease_fence()
                            check_stage_binding()
                            os.unlink(src.name, dir_fd=src_fd)
                    _check_identity(_entry(stage_fd, target.name), identity, target)
                    if preserve_source:
                        # Postcheck diagnoses an adversarial swap; the new
                        # staged hardlink still points to our pinned inode.
                        _check_identity(_entry(src_fd, src.name), identity, src)
                    check_stage_binding()
                    os.fsync(stage_fd)
                    os.fsync(src_fd)
                    return "linked" if preserve_source else "moved"
                finally:
                    if source_file_fd is not None:
                        os.close(source_file_fd)
            finally:
                os.close(unit_fd)
        finally:
            os.close(stage_fd)
    finally:
        os.close(src_fd)


def _validate_frozen_rows(manifest: dict, unit: Path) -> list[dict]:
    moves = manifest.get("moves")
    if not isinstance(moves, list) or not moves:
        raise StagingConflict("frozen manifest lacks source rows")
    stage = unit / manifest["stage_directory"]
    unit_dev = manifest.get("unit_dev")
    sources, targets = set(), set()
    for ordinal, row in enumerate(moves, 1):
        if not isinstance(row, dict):
            raise StagingConflict("invalid frozen row")
        source = _absolute_literal(row.get("source"), unit, is_source=True)
        temporary = _absolute_literal(row.get("target"), unit, is_source=False)
        final = _absolute_literal(row.get("final"), unit, is_source=False)
        expected_stage_name = f"{ordinal:06d}{source.suffix}"
        if (temporary != stage / expected_stage_name or
                row.get("target_name") != final.name or
                source.suffix != final.suffix or
                row.get("group") not in ("P", "V", "Other")):
            raise StagingConflict("untrusted frozen stage or final path")
        identity = row.get("identity")
        if (not isinstance(identity, list) or len(identity) != 4 or
                not all(isinstance(x, int) and not isinstance(x, bool) for x in identity) or
                identity[0] != unit_dev):
            raise StagingConflict("untrusted frozen identity")
        if str(source) in sources or str(temporary) in targets:
            raise StagingConflict("duplicate frozen source or stage path")
        sources.add(str(source))
        targets.add(str(temporary))
    return moves


def _inspect_stage(stage_fd: int, stage: Path, moves: list[dict],
                   expected: bytes, *, groups: list[dict] | None = None) -> bool:
    if not _read_marker(stage_fd, _OWNER, expected):
        raise StagingConflict("stage owner marker missing")
    by_name = {Path(row["target"]).name: row for row in moves}
    if len(by_name) != len(moves):
        raise StagingConflict("duplicate staged file names")
    # A publication in progress may have already prepared an owned,
    # witnessed PRIVATE directory that must not be mistaken for a foreign
    # regular file. It is never an authority for a new public destination.
    pending = {f".nfc-publish-pending-{index:06d}"
               for index in range(1, len(groups or []) + 1)}
    permissible = set(by_name) | {_OWNER, _COMPLETE} | pending
    with os.scandir(stage_fd) as entries:
        seen = set()
        for entry in entries:
            if entry.name not in permissible:
                raise StagingConflict(f"untrusted stage workspace entry: {entry.name}")
            seen.add(entry.name)
            if entry.name in by_name:
                info = entry.stat(follow_symlinks=False)
                _check_identity(info, by_name[entry.name]["identity"], stage / entry.name)
            elif entry.name in pending:
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode):
                    raise StagingConflict("unexpected type for pending public group")
                pending_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY |
                                     os.O_NOFOLLOW, dir_fd=stage_fd)
                try:
                    if not _read_marker(pending_fd, ".nfc-publish-owner", expected):
                        raise StagingConflict("pending group lacks frozen owner witness")
                    with os.scandir(pending_fd) as children:
                        names = {child.name for child in children}
                    if names != {".nfc-publish-owner"}:
                        raise StagingConflict("foreign entry in pending public group")
                finally:
                    os.close(pending_fd)
            else:
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise StagingConflict("special file in staging workspace")
    complete = _read_marker(stage_fd, _COMPLETE, expected)
    if complete and not set(by_name).issubset(seen):
        raise StagingConflict("staging completion marker disagrees with files")
    return complete


def stage_frozen_sources(
    manifest: dict, *, frozen_manifest_path: Path, allowed_roots: list[Path],
    lease_fence: Callable[[], None], quarantine_root: Path | None = None,
    resume: bool = False,
) -> dict:
    """Stage all frozen source files or reconcile a verified partial stage.

    The checksum-protected manifest must already be durable in the private
    report area. An unexpected stage, changed source, or unsupported no-replace
    operation fails closed; no foreign entry is deleted or overwritten.
    """
    if not callable(lease_fence):
        raise StagingConflict("active Worker lease fence is required")
    if not isinstance(manifest, dict):
        raise StagingConflict("invalid frozen manifest")
    unit = Path(manifest.get("unit", ""))
    job_id = manifest.get("job_id")
    frozen_path = Path(frozen_manifest_path)
    try:
        if not isinstance(job_id, int) or job_id < 1:
            raise StagingConflict("invalid frozen job identity")
        if not unit.is_absolute() or frozen_path.is_relative_to(unit):
            raise StagingConflict("frozen manifest must be outside the unit")
        authorized = load_frozen_preview_manifest(
            frozen_path, job_id=job_id, unit=unit,
        )
        if authorized != manifest:
            raise StagingConflict("frozen manifest differs from approved snapshot")
        _check_scope(unit, [Path(x) for x in allowed_roots],
                     Path(quarantine_root) if quarantine_root is not None else None)
        if manifest.get("stage_directory") != f".nfc-media-organizer-stage-{job_id}":
            raise StagingConflict("invalid staging workspace label")
        moves = _validate_frozen_rows(manifest, unit)
        unit_fd = _open_directory_nofollow(unit)
        try:
            unit_stat = os.fstat(unit_fd)
            if (int(unit_stat.st_dev) != manifest.get("unit_dev") or
                    int(unit_stat.st_ino) != manifest.get("unit_ino")):
                raise StagingConflict("frozen organizing unit identity changed")
        finally:
            os.close(unit_fd)

        stage = unit / manifest["stage_directory"]
        expected = _authority(manifest)
        if not resume:
            validate_execution_preflight(
                manifest, allowed_roots=[Path(x) for x in allowed_roots],
                quarantine_root=quarantine_root,
            )
            lease_fence()
            parent_fd = _open_directory_nofollow(unit)
            try:
                # O_EXCL-style mkdir: do not adopt a path created by another job.
                os.mkdir(manifest["stage_directory"], mode=0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        elif not os.path.lexists(stage):
            raise StagingConflict("stage workspace missing for requested resume")

        stage_fd = _open_directory_nofollow(stage)
        try:
            stage_stat = _assert_private_stage_fd(stage_fd)
            if int(stage_stat.st_dev) != manifest["unit_dev"]:
                raise StagingConflict("stage filesystem changed")
            if resume:
                _inspect_stage(stage_fd, stage, moves, expected,
                               groups=manifest.get("groups", []))
            else:
                lease_fence()
                _write_marker(stage_fd, _OWNER, expected)
            owned_stat = os.fstat(stage_fd)
            stage_binding = (int(owned_stat.st_dev), int(owned_stat.st_ino))
        finally:
            os.close(stage_fd)

        def guard() -> None:
            fd = _open_directory_nofollow(unit)
            try:
                st = os.fstat(fd)
                if ([int(st.st_dev), int(st.st_ino)] !=
                        [manifest["unit_dev"], manifest["unit_ino"]]):
                    raise StagingConflict("organizing unit changed during staging")
            finally:
                os.close(fd)
            lease_fence()

        preserve_source = manifest.get("cleanup_policy") == "deferred"
        staged = reconciled = 0
        for row in moves:
            guard()
            source = Path(row["source"])
            target = Path(row["target"])
            stage_stat = os.lstat(target) if os.path.lexists(target) else None
            source_stat = os.lstat(source) if os.path.lexists(source) else None
            if stage_stat is not None:
                _check_identity(stage_stat, row["identity"], target)
                if preserve_source:
                    # V1.6 preserves the original on purpose. Both names MUST
                    # still refer to the frozen inode, not two arbitrary files.
                    _check_identity(source_stat, row["identity"], source)
                    if (int(source_stat.st_dev), int(source_stat.st_ino)) != (
                            int(stage_stat.st_dev), int(stage_stat.st_ino)):
                        raise StagingConflict("retained source and stage inode differ")
                elif source_stat is not None:
                    # Historical rename-fallback duplicates need manual review.
                    raise StagingConflict("source and staged file both exist; manual review")
                reconciled += 1
            else:
                _check_identity(source_stat, row["identity"], source)
                outcome = _move_one(
                    row, lease_fence=guard, ignore_final=True,
                    stage_binding=stage_binding, stage_witness=expected,
                    preserve_source=preserve_source,
                )
                if outcome != ("linked" if preserve_source else "moved"):
                    raise StagingConflict("unexpected staging reconciliation state")
                staged += 1

        stage_fd = _open_directory_nofollow(stage)
        try:
            _assert_private_stage_fd(stage_fd)
            complete = _inspect_stage(stage_fd, stage, moves, expected,
                                      groups=manifest.get("groups", []))
            if not complete:
                guard()
                _write_marker(stage_fd, _COMPLETE, expected)
            if not _inspect_stage(stage_fd, stage, moves, expected,
                                  groups=manifest.get("groups", [])):
                raise StagingConflict("staging completion witness missing")
        finally:
            os.close(stage_fd)
        return {
            "ready_to_publish": True,
            "unit": str(unit),
            "staged": staged, "reconciled": reconciled,
            "file_count": len(moves), "stage": str(stage),
        }
    except (FrozenPreviewError, ExecutionPreflightError, MediaPackageExecutionConflict,
            OSError, ValueError) as exc:
        if isinstance(exc, StagingConflict):
            raise
        raise StagingConflict(f"frozen staging changed or unsafe: {exc}") from exc
