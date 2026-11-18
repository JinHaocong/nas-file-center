"""Crash-resumable V1.6 *real* cleanup engine, NOT YET A PRODUCTION ENDPOINT.

Unlike the read-only audit and cleanup plan this module actually unlinks
frozen original/stage hardlinks and rmdirs emptied classification wrappers.
It therefore REQUIRES an externally enforced exclusive namespace-custody
provider. None is issued by the production application: an admin checkbox,
a WorkJob lease or an ordinary inode recheck is NOT such a provider.

The injected provider is used only in disposable synthetic acceptance until
the NAS filesystem/ACL and concurrent writer threat model has independently
proven enforceable custody. No API/Worker route calls this function.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Callable, Protocol

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_cleanup_audit import audit_deferred_cleanup_inventory
from app.batch.media_organizer_cleanup_plan import (
    _read_existing, cleanup_plan_path,
)
from app.batch.media_organizer_manifest import (
    _checksum, load_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import _check_scope, preview_semantic_unit
from app.batch.media_organizer_publish import _group_receipts
from app.batch.media_organizer_stage import _authority

_MAX_JOURNAL_BYTES = 16 * 1024 * 1024
_OWNER = ".nfc-stage-authority"
_COMPLETE = ".nfc-stage-complete"
_GROUP_OWNER = ".nfc-publish-owner"
_GROUP_COMPLETE = ".nfc-publish-complete"


class CleanupExecutionBlocked(ValueError):
    """No cleanup action may be performed without frozen, exclusive custody."""


class ExclusiveNamespaceCustody(Protocol):
    def assert_exclusive(self, parent: Path) -> None:
        """Provide externally verified EXCLUSIVE write custody of this namespace."""


def cleanup_confirmation(job_id: int, unit: str, plan_sha256: str) -> str:
    """Distinct per-job/per-unit/plan human confirmation, not a custody proof."""
    if (not isinstance(job_id, int) or job_id < 1
            or not isinstance(unit, str) or not Path(unit).is_absolute()
            or not isinstance(plan_sha256, str) or len(plan_sha256) != 64):
        raise CleanupExecutionBlocked("invalid separate cleanup confirmation identity")
    unit_tag = hashlib.sha256(unit.encode("utf-8")).hexdigest()[:16].upper()
    return f"CLEANUP_FROZEN_JOB_{job_id}_UNIT_{unit_tag}_PLAN_{plan_sha256[:16].upper()}"


def _canonical(value: dict | list) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _journal_path(frozen: Path) -> Path:
    return frozen.with_name(frozen.name + ".cleanup-progress.jsonl")


def _operations(manifest: dict, plan: dict) -> list[dict]:
    unit = Path(manifest["unit"])
    rows = manifest["moves"]
    stages = plan["staged_links"]
    originals = plan["original_links"]
    if (len(rows) != len(originals) or len(rows) != len(stages)
            or plan.get("job_id") != manifest["job_id"]
            or plan.get("unit") != str(unit)
            or plan.get("manifest_checksum") != _checksum(manifest)
            or plan.get("cleanup_authorized") is not False
            or plan.get("plan_kind") != "review_only"):
        raise CleanupExecutionBlocked("cleanup plan is not tied to the frozen unit")
    ops = []
    for row, source, staged in zip(rows, originals, stages):
        if (source.get("path") != row["source"]
                or source.get("published_path") != row["final"]
                or source.get("identity") != row["identity"]
                or staged.get("path") != row["target"]
                or staged.get("published_path") != row["final"]
                or staged.get("identity") != row["identity"]):
            raise CleanupExecutionBlocked("cleanup plan source identity changed")
        ops.append({"kind": "original", "path": row["source"],
                    "identity": row["identity"], "published": row["final"]})
    expected_wrappers = [
        {"path": path, "identity": list(identity)}
        for path, identity in sorted(
            manifest["wrapper_identities"].items(),
            key=lambda p: (-len(Path(p[0]).parts), p[0]),
        )
    ]
    if plan.get("wrapper_directories") != expected_wrappers:
        raise CleanupExecutionBlocked("cleanup plan wrapper inventory changed")
    for wrapper in expected_wrappers:
        ops.append({"kind": "wrapper", **wrapper})
    for staged in stages:
        ops.append({"kind": "stage-link", "path": staged["path"],
                    "identity": staged["identity"],
                    "published": staged["published_path"]})
    # Group witness markers must be removed: the canonical planner deliberately
    # blocks EVERY '.nfc-*' file in public groups during the second scan.
    for group in manifest["groups"]:
        path = str(unit / group["name"])
        ops.append({"kind": "group-marker", "path": str(Path(path) / _GROUP_COMPLETE),
                    "group_name": group["name"]})
        ops.append({"kind": "group-marker", "path": str(Path(path) / _GROUP_OWNER),
                    "group_name": group["name"]})
    stage = unit / manifest["stage_directory"]
    if plan.get("stage", {}).get("path") != str(stage):
        raise CleanupExecutionBlocked("cleanup stage binding differs from frozen unit")
    ops.append({"kind": "stage-marker", "path": str(stage / _COMPLETE)})
    ops.append({"kind": "stage-marker", "path": str(stage / _OWNER)})
    ops.append({"kind": "stage-directory", "path": str(stage),
                "identity": plan["stage"]["identity"]})
    return ops


def _line(previous: str, event: dict) -> tuple[bytes, str]:
    signature = hashlib.sha256(
        previous.encode("ascii") + b"\0" + _canonical(event)
    ).hexdigest()
    return _canonical({**event, "chain_sha256": signature}) + b"\n", signature


def _load_journal(path: Path, header: dict, operation_count: int) -> tuple[str, int, int | None, bool]:
    """Return (chain,last_finished,pending,finalized); check chained sequence."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    parent_fd = _open_directory_nofollow(path.parent)
    try:
        fd = os.open(path.name, flags, dir_fd=parent_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not 1 <= info.st_size <= _MAX_JOURNAL_BYTES
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise CleanupExecutionBlocked("private cleanup progress journal is untrusted")
            lines = stream.readlines()
    finally:
        os.close(parent_fd)
    previous = "0" * 64
    completed = 0
    pending = None
    finished = False
    if not lines:
        raise CleanupExecutionBlocked("empty cleanup progress journal")
    for index, raw in enumerate(lines):
        if len(raw) > 4096 or not raw.endswith(b"\n"):
            raise CleanupExecutionBlocked("partial or oversized cleanup journal entry")
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise CleanupExecutionBlocked("cleanup progress journal corrupted") from exc
        if not isinstance(record, dict):
            raise CleanupExecutionBlocked("invalid cleanup progress record")
        digest = record.pop("chain_sha256", None)
        _, expected = _line(previous, record)
        if digest != expected:
            raise CleanupExecutionBlocked("cleanup progress journal hash chain changed")
        previous = expected
        if index == 0:
            if record != header:
                raise CleanupExecutionBlocked("cleanup journal does not bind frozen plan")
        elif record == {"kind": "begin", "index": completed} and pending is None and not finished:
            pending = completed
        elif record == {"kind": "done", "index": completed} and pending == completed and not finished:
            completed += 1
            pending = None
        elif (record == {"kind": "finalized", "count": operation_count}
              and completed == operation_count and pending is None and not finished):
            finished = True
        else:
            raise CleanupExecutionBlocked("invalid cleanup journal step sequence")
    return previous, completed, pending, finished


def _append(path: Path, previous: str, event: dict) -> str:
    line, chained = _line(previous, event)
    fd = os.open(
        path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW |
        getattr(os, "O_CLOEXEC", 0),
    )
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise CleanupExecutionBlocked("cleanup journal changed during append")
        if info.st_size + len(line) > _MAX_JOURNAL_BYTES:
            raise CleanupExecutionBlocked("cleanup journal size limit exceeded")
        written = os.write(fd, line)
        if written != len(line):
            raise CleanupExecutionBlocked("partial cleanup journal write; manual review")
        os.fsync(fd)
    finally:
        os.close(fd)
    return chained


def _new_journal(path: Path, header: dict) -> str:
    line, digest = _line("0" * 64, header)
    folder_fd = _open_directory_nofollow(path.parent)
    try:
        fd = os.open(
            path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=folder_fd,
        )
        with os.fdopen(fd, "wb") as stream:
            st = os.fstat(stream.fileno())
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                    or st.st_nlink != 1):
                raise CleanupExecutionBlocked("new progress journal ownership unsafe")
            os.fchmod(stream.fileno(), 0o600)
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(folder_fd)
    finally:
        os.close(folder_fd)
    return digest


def _entry(parent_fd: int, name: str):
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _file_matches(info, identity) -> bool:
    return (info is not None and stat.S_ISREG(info.st_mode) and
            [int(info.st_dev), int(info.st_ino), int(info.st_size),
             int(info.st_mtime_ns)] == identity)


def _check_public(manifest: dict, group_receipts: dict[str, tuple[int, int]]) -> None:
    unit = Path(manifest["unit"])
    for name, identity in group_receipts.items():
        folder = unit / name
        fd = _open_directory_nofollow(folder)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISDIR(info.st_mode) or
                    (int(info.st_dev), int(info.st_ino)) != identity):
                raise CleanupExecutionBlocked("final group identity changed")
            parent_fd = _open_directory_nofollow(unit)
            try:
                bound = _entry(parent_fd, name)
                if (bound is None or
                        (int(bound.st_dev), int(bound.st_ino)) != identity):
                    raise CleanupExecutionBlocked("final group basename changed")
            finally:
                os.close(parent_fd)
        finally:
            os.close(fd)
    for row in manifest["moves"]:
        final = Path(row["final"])
        parent_fd = _open_directory_nofollow(final.parent)
        try:
            if not _file_matches(_entry(parent_fd, final.name), row["identity"]):
                raise CleanupExecutionBlocked("published final media identity changed")
        finally:
            os.close(parent_fd)


def _check_direct_unrecognized(manifest: dict) -> None:
    """Refuse extra root-level files that were not part of the frozen plan."""
    unit = Path(manifest["unit"])
    expected = {Path(manifest["stage_directory"]).name}
    for row in manifest["moves"]:
        for key in ("source", "final"):
            p = Path(row[key])
            if p.parent == unit:
                expected.add(p.name)
            elif p.is_relative_to(unit):
                expected.add(p.relative_to(unit).parts[0])
    for group in manifest["groups"]:
        expected.add(group["name"])
    fd = _open_directory_nofollow(unit)
    try:
        info = os.fstat(fd)
        if (int(info.st_dev), int(info.st_ino)) != (
                manifest["unit_dev"], manifest["unit_ino"]):
            raise CleanupExecutionBlocked("organizing unit directory changed")
        with os.scandir(fd) as entries:
            for e in entries:
                if e.name in expected:
                    continue
                st = e.stat(follow_symlinks=False)
                # Independent protected children may legitimately be present.
                # Unknown root media/files or symlinks are never silently ignored.
                if not stat.S_ISDIR(st.st_mode):
                    raise CleanupExecutionBlocked("unknown root file during cleanup")
    finally:
        os.close(fd)


def _verify_marker(parent_fd: int, name: str, authority: bytes) -> None:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        if (not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= 4096
                or st.st_nlink != 1):
            raise CleanupExecutionBlocked("unsafe completion marker inode")
        if handle.read(4097) != authority:
            raise CleanupExecutionBlocked("completion marker witness changed")


def _mutate_one(op: dict, *, previously_begun: bool,
                custody: ExclusiveNamespaceCustody, witness: bytes,
                manifest: dict, receipts: dict[str, tuple[int, int]]) -> None:
    path = Path(op["path"])
    kind = op["kind"]
    if not path.is_relative_to(Path(manifest["unit"])):
        raise CleanupExecutionBlocked("cleanup mutation escaped frozen unit")
    custody.assert_exclusive(path.parent)
    parent_fd = _open_directory_nofollow(path.parent)
    try:
        info = _entry(parent_fd, path.name)
        if info is None:
            if previously_begun:
                # Crash between unlink/rmdir and durable DONE. Missing name is
                # reconciled ONLY with a durable, chained BEGIN record.
                return
            raise CleanupExecutionBlocked("source vanished without cleanup journal")
        if kind in ("original", "stage-link"):
            if not _file_matches(info, op["identity"]):
                raise CleanupExecutionBlocked("frozen source identity changed")
            final = Path(op["published"])
            final_fd = _open_directory_nofollow(final.parent)
            try:
                if not _file_matches(_entry(final_fd, final.name), op["identity"]):
                    raise CleanupExecutionBlocked("final hardlink changed before unlink")
            finally:
                os.close(final_fd)
            # A named unlink cannot atomically compare inode. This is allowed
            # solely INSIDE the externally established exclusive namespace.
            custody.assert_exclusive(path.parent)
            if not _file_matches(_entry(parent_fd, path.name), op["identity"]):
                raise CleanupExecutionBlocked("source identity changed at mutation boundary")
            os.unlink(path.name, dir_fd=parent_fd)
        elif kind in ("wrapper", "stage-directory"):
            if (not stat.S_ISDIR(info.st_mode) or
                    [int(info.st_dev), int(info.st_ino)] != op["identity"]):
                raise CleanupExecutionBlocked("cleanup directory identity changed")
            directory_fd = os.open(
                path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                opened = os.fstat(directory_fd)
                if [int(opened.st_dev), int(opened.st_ino)] != op["identity"]:
                    raise CleanupExecutionBlocked("opened directory identity differs")
                with os.scandir(directory_fd) as entries:
                    if next(entries, None) is not None:
                        raise CleanupExecutionBlocked("cleanup directory not empty")
            finally:
                os.close(directory_fd)
            custody.assert_exclusive(path.parent)
            bound = _entry(parent_fd, path.name)
            if bound is None or [int(bound.st_dev), int(bound.st_ino)] != op["identity"]:
                raise CleanupExecutionBlocked("cleanup directory rebound")
            os.rmdir(path.name, dir_fd=parent_fd)
        elif kind in ("group-marker", "stage-marker"):
            if not stat.S_ISREG(info.st_mode):
                raise CleanupExecutionBlocked("untrusted completion marker")
            if kind == "group-marker":
                group = path.parent
                name = op["group_name"]
                if group != Path(manifest["unit"]) / name:
                    raise CleanupExecutionBlocked("marker escaped frozen group")
                binding = receipts.get(name)
                if binding is None:
                    raise CleanupExecutionBlocked("missing frozen group receipt")
                opened_fd = os.fstat(parent_fd)
                if (int(opened_fd.st_dev), int(opened_fd.st_ino)) != binding:
                    raise CleanupExecutionBlocked("public group binding changed")
            _verify_marker(parent_fd, path.name, witness)
            custody.assert_exclusive(path.parent)
            _verify_marker(parent_fd, path.name, witness)
            os.unlink(path.name, dir_fd=parent_fd)
        else:
            raise CleanupExecutionBlocked("unknown cleanup operation")
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _verify_finished_scan(manifest: dict, frozen: Path,
                          allowed_roots: list[Path],
                          quarantine_root: Path | None) -> dict:
    """Check using the ORIGINAL frozen bytes, never a decorated manifest."""
    unit = Path(manifest["unit"])
    _check_public(manifest, _group_receipts(manifest, frozen))
    result = preview_semantic_unit(
        unit, allowed_roots=allowed_roots, quarantine_root=quarantine_root,
        exclude_dir_names=manifest.get("excluded_dir_names", []),
    )
    if (result.get("status") != "already_organized"
            or result.get("needed_moves") != 0
            or result.get("renamed_count") != 0
            or any(result.get("conflicts", []))
            or len(result.get("items", [])) != len(manifest["moves"])):
        raise CleanupExecutionBlocked("canonical second scan is not zero-change")
    return result


def finish_deferred_cleanup(
    manifest: dict, *, frozen_manifest_path: Path, allowed_roots: list[Path],
    confirmation: str, custody: ExclusiveNamespaceCustody | None = None,
    quarantine_root: Path | None = None,
    after_mutation: Callable[[int], None] | None = None,
) -> dict:
    """Execute real cleanup ONLY with separate approval and external custody.

    There is intentionally NO production caller/issuer for namespace custody.
    Testing code may inject a fixture that has exclusive control of tmp_path.
    """
    if custody is None or not callable(getattr(custody, "assert_exclusive", None)):
        raise CleanupExecutionBlocked("verified exclusive namespace custody required")
    if not callable(after_mutation) and after_mutation is not None:
        raise CleanupExecutionBlocked("invalid test interruption callback")
    if os.geteuid() == 0:
        raise CleanupExecutionBlocked("dedicated non-root Worker required for cleanup")
    try:
        unit = Path(manifest["unit"])
        frozen = Path(frozen_manifest_path)
        approved = load_frozen_preview_manifest(
            frozen, job_id=manifest["job_id"], unit=unit,
        )
        if approved != manifest or manifest.get("cleanup_policy") != "deferred":
            raise CleanupExecutionBlocked("cleanup frozen manifest changed")
        _check_scope(
            unit, [Path(p) for p in allowed_roots], quarantine_root,
        )
        # The saved record is self-checksummed and immutable. The stage inode
        # may be absent on recovery after the final rmdir: do not regenerate it.
        plan = _read_existing(cleanup_plan_path(frozen))
        ops = _operations(manifest, plan)
        if confirmation != cleanup_confirmation(
                manifest["job_id"], str(unit), plan["plan_sha256"]):
            raise CleanupExecutionBlocked("exact separate cleanup confirmation required")
        for op in ops:
            custody.assert_exclusive(Path(op["path"]).parent)
        custody.assert_exclusive(unit)
        receipts = _group_receipts(manifest, frozen)
        path = _journal_path(frozen)
        header = {
            "kind": "header",
            "job_id": manifest["job_id"],
            "unit": str(unit),
            "manifest_checksum": _checksum(manifest),
            "plan_sha256": plan["plan_sha256"],
            "operations_sha256": hashlib.sha256(_canonical(ops)).hexdigest(),
            "operations_count": len(ops),
        }
        journal_exists = os.path.lexists(path)
        if not journal_exists:
            # Initial acceptance must establish every original and stage
            # BEFORE any entry is unlinked. After a crash, the chained journal
            # governs which frozen names may already be gone.
            audit_deferred_cleanup_inventory(
                manifest, frozen_manifest_path=frozen,
                allowed_roots=allowed_roots, quarantine_root=quarantine_root,
            )
            _check_direct_unrecognized(manifest)
            _check_public(manifest, receipts)
            try:
                chain = _new_journal(path, header)
            except FileExistsError as exc:
                raise CleanupExecutionBlocked("cleanup journal appeared during preflight") from exc
            completed = 0
            pending = None
            finished = False
        else:
            chain, completed, pending, finished = _load_journal(
                path, header, len(ops),
            )
        _check_public(manifest, receipts)
        _check_direct_unrecognized(manifest)
        witness = _authority(manifest)
        for i, op in enumerate(ops):
            if i < completed:
                if os.path.lexists(op["path"]):
                    raise CleanupExecutionBlocked("completed cleanup pathname was replaced")
                continue
            if pending != i:
                chain = _append(path, chain, {"kind": "begin", "index": i})
            _mutate_one(
                op, previously_begun=(pending == i),
                custody=custody, witness=witness,
                manifest=manifest, receipts=receipts,
            )
            if after_mutation is not None:
                after_mutation(i)
            chain = _append(path, chain, {"kind": "done", "index": i})
            pending = None
        # No staging/old wrappers remain. The second scan must now find the
        # complete frozen output unchanged before the final durable event.
        scanned = _verify_finished_scan(
            manifest, frozen, [Path(p) for p in allowed_roots], quarantine_root,
        )
        if not finished:
            _append(path, chain, {"kind": "finalized", "count": len(ops)})
        return {
            "job_id": manifest["job_id"],
            "unit": str(unit),
            "finalized": True,
            "already_organized": True,
            "needed_moves": int(scanned["needed_moves"]),
            "renamed_count": int(scanned["renamed_count"]),
            "originals_removed": len(manifest["moves"]),
            "old_wrappers_removed": len(manifest["wrapper_identities"]),
            "groups_verified": len(manifest["groups"]),
            "stage_removed": True,
            "namespace_exclusive_custody_proven": False,
            "scope": "injected_custody_only_not_production_authorized",
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, CleanupExecutionBlocked):
            raise
        raise CleanupExecutionBlocked(
            f"frozen cleanup proof failed or namespace changed: {exc}"
        ) from exc
