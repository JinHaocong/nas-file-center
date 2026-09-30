from __future__ import annotations

from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.batch.plans import OperationItem
from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.exceptions import StateConflictError
from app.models import AuditEvent, BatchPlan, BatchPlanItem, OperationJournal, WorkJob
from app.storage_optimization.capability import (
    FICLONE,
    StorageOptimizationCapability,
    probe_hardlink_between,
    probe_hardlink_capability,
    probe_reflink_between,
)
from app.storage_optimization.metadata import (
    FrozenFileMetadata,
    StorageMetadataError,
    apply_frozen_metadata_fd,
    capture_file_metadata_fd,
    replacement_metadata_matches,
)
from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease


OPTIMIZATION_OPERATIONS = frozenset({"hardlink_optimize", "reflink_optimize"})
_HASH_CHUNK_BYTES = 8 * 1024 * 1024


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mtime_ns(st: os.stat_result) -> int:
    return int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))


def _identity(st: os.stat_result) -> dict[str, int]:
    return {
        "device": int(st.st_dev),
        "inode": int(st.st_ino),
        "size": int(st.st_size),
        "mtime_ns": _mtime_ns(st),
    }


def _stat_optional(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _hash_fd(
    fd: int,
    *,
    session_factory: sessionmaker,
    worker_id: str,
) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    last_fence = time.monotonic()
    while True:
        chunk = os.read(fd, _HASH_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
        if time.monotonic() - last_fence >= 2.0:
            renew_and_assert_worker_lease(session_factory, worker_id)
            last_fence = time.monotonic()
    return digest.hexdigest()


def _qualify_fd(
    fd: int,
    *,
    expected_device: int | None,
    expected_inode: int | None,
    expected_size: int,
    expected_mtime_ns: int | None,
    expected_hash: str,
    session_factory: sessionmaker,
    worker_id: str,
    failure_prefix: str,
) -> os.stat_result:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise StateConflictError(f"{failure_prefix}_NOT_REGULAR")
    if expected_device is not None and int(before.st_dev) != int(expected_device):
        raise StateConflictError(f"{failure_prefix}_DEVICE_CHANGED")
    if expected_inode is not None and int(before.st_ino) != int(expected_inode):
        raise StateConflictError(f"{failure_prefix}_INODE_CHANGED")
    if int(before.st_size) != int(expected_size):
        raise StateConflictError(f"{failure_prefix}_SIZE_CHANGED")
    if expected_mtime_ns is not None and _mtime_ns(before) != int(expected_mtime_ns):
        raise StateConflictError(f"{failure_prefix}_MTIME_CHANGED")

    actual_hash = _hash_fd(
        fd,
        session_factory=session_factory,
        worker_id=worker_id,
    )
    after = os.fstat(fd)
    if (
        int(after.st_dev) != int(before.st_dev)
        or int(after.st_ino) != int(before.st_ino)
        or int(after.st_size) != int(before.st_size)
        or _mtime_ns(after) != _mtime_ns(before)
    ):
        raise StateConflictError(f"{failure_prefix}_CHANGED_DURING_HASH")
    if actual_hash.lower() != expected_hash.lower():
        raise StateConflictError(f"{failure_prefix}_SHA256_CHANGED")
    return after


def _parse_json_dict(raw: str | None, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except Exception as exc:
        raise StateConflictError(f"{label}_MALFORMED") from exc
    if not isinstance(value, dict):
        raise StateConflictError(f"{label}_MALFORMED")
    return value


def _load_authority(
    session_factory: sessionmaker,
    item: OperationItem,
    *,
    plan_id: str,
) -> tuple[int, int | None, dict[str, Any]]:
    try:
        numeric_plan_id = int(plan_id)
    except (TypeError, ValueError) as exc:
        raise StateConflictError("STORAGE_OPTIMIZATION_PLAN_ID_INVALID") from exc

    with session_factory() as session:
        plan = session.get(BatchPlan, numeric_plan_id)
        if plan is None or plan.kind != "dedupe":
            raise StateConflictError("STORAGE_OPTIMIZATION_PLAN_AUTHORITY_MISSING")
        plan_meta = _parse_json_dict(plan.metadata_json, label="STORAGE_OPTIMIZATION_PLAN_METADATA")
        action = plan_meta.get("storage_action")
        expected_operation = {
            "hardlink": "hardlink_optimize",
            "reflink": "reflink_optimize",
        }.get(action)
        if (
            plan_meta.get("source") != "dedupe"
            or expected_operation is None
            or item.operation != expected_operation
        ):
            raise StateConflictError("STORAGE_OPTIMIZATION_PLAN_AUTHORITY_CHANGED")

        rows = list(
            session.scalars(
                select(BatchPlanItem).where(
                    BatchPlanItem.plan_id == numeric_plan_id,
                    BatchPlanItem.sequence == item.sequence,
                )
            )
        )
        if len(rows) != 1:
            raise StateConflictError("STORAGE_OPTIMIZATION_ITEM_AUTHORITY_NOT_UNIQUE")
        row = rows[0]
        if row.state != "executing":
            raise StateConflictError("STORAGE_OPTIMIZATION_ITEM_NOT_EXECUTING")
        if (
            row.operation != item.operation
            or row.source_path != os.fspath(item.source)
            or row.keep_path != (os.fspath(item.keep) if item.keep is not None else None)
        ):
            raise StateConflictError("STORAGE_OPTIMIZATION_ITEM_AUTHORITY_CHANGED")
        for attr in (
            "expected_device",
            "expected_inode",
            "expected_size",
            "expected_mtime_ns",
            "expected_hash",
        ):
            if getattr(row, attr) != getattr(item, attr):
                raise StateConflictError(
                    f"STORAGE_OPTIMIZATION_{attr.upper()}_AUTHORITY_CHANGED"
                )
        if not row.expected_hash or len(row.expected_hash) != 64 or not row.keep_path:
            raise StateConflictError("STORAGE_OPTIMIZATION_FROZEN_HASH_OR_KEEP_MISSING")

        item_meta = _parse_json_dict(row.metadata_json, label="STORAGE_OPTIMIZATION_ITEM_METADATA")
        frozen_opt = item_meta.get("storage_optimization")
        if not isinstance(frozen_opt, dict):
            raise StateConflictError("STORAGE_OPTIMIZATION_FROZEN_METADATA_MISSING")
        tx_id = frozen_opt.get("transaction_id")
        if (
            not isinstance(tx_id, str)
            or not tx_id.strip()
            or tx_id != item_meta.get("storage_optimization_transaction_id")
        ):
            raise StateConflictError("STORAGE_OPTIMIZATION_TRANSACTION_ID_CHANGED")
        if frozen_opt.get("operation") != row.operation:
            raise StateConflictError("STORAGE_OPTIMIZATION_OPERATION_CHANGED")

        execution = item_meta.get("execution")
        task_id = execution.get("task_id") if isinstance(execution, dict) else None
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
            raise StateConflictError("STORAGE_OPTIMIZATION_TASK_AUTHORITY_MISSING")

        keep_snapshot = item_meta.get("keep_snapshot")
        if not isinstance(keep_snapshot, dict):
            raise StateConflictError("STORAGE_OPTIMIZATION_KEEP_SNAPSHOT_MISSING")
        source_metadata = FrozenFileMetadata.from_json_dict(
            frozen_opt.get("frozen_source_metadata") or {}
        )
        keep_metadata = FrozenFileMetadata.from_json_dict(
            frozen_opt.get("frozen_keep_metadata") or {}
        )

        job = session.get(WorkJob, task_id)
        requested_by_user_id: int | None = None
        if job is not None:
            job_state = _parse_json_dict(job.state_json, label="STORAGE_OPTIMIZATION_JOB_STATE")
            raw_user = job_state.get("requested_by_user_id")
            if isinstance(raw_user, int) and not isinstance(raw_user, bool) and raw_user > 0:
                requested_by_user_id = int(raw_user)

        new_name = f".__nfc_opt_{tx_id}.new"
        old_name = f".__nfc_opt_{tx_id}.old"
        manifest = {
            "semantics": "storage_optimization_v1",
            "transaction_id": tx_id,
            "operation": row.operation,
            "storage_action": action,
            "plan_id": numeric_plan_id,
            "plan_item_id": int(row.id),
            "sequence": int(row.sequence),
            "source_path": row.source_path,
            "keep_path": row.keep_path,
            "new_name": new_name,
            "old_name": old_name,
            "expected_source": {
                "device": int(row.expected_device),
                "inode": int(row.expected_inode),
                "size": int(row.expected_size),
                "mtime_ns": int(row.expected_mtime_ns),
                "sha256": str(row.expected_hash).lower(),
            },
            "expected_keep": {
                "device": int(keep_snapshot.get("device") or 0),
                "inode": int(keep_snapshot.get("inode") or 0),
                "size": int(keep_snapshot.get("size") or 0),
                "mtime_ns": int(keep_snapshot.get("mtime_ns") or 0),
                "sha256": str(keep_snapshot.get("hash") or row.expected_hash).lower(),
            },
            "frozen_source_metadata": source_metadata.to_json_dict(),
            "frozen_keep_metadata": keep_metadata.to_json_dict(),
        }
        if manifest["expected_keep"]["device"] <= 0 or manifest["expected_keep"]["inode"] <= 0:
            raise StateConflictError("STORAGE_OPTIMIZATION_KEEP_IDENTITY_MISSING")
        return int(row.id), requested_by_user_id, manifest


def _journal_payload(row: OperationJournal) -> dict[str, Any]:
    try:
        value = json.loads(row.before_json or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _phase_journal(
    session_factory: sessionmaker,
    *,
    worker_id: str,
    manifest: dict[str, Any],
    phase: str,
    task_id: int,
    user_id: int | None,
    after: dict[str, Any] | None = None,
    terminal_audit: bool = False,
) -> None:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        item = session.get(BatchPlanItem, int(manifest["plan_item_id"]))
        if item is None or item.state != "executing":
            raise StateConflictError("STORAGE_OPTIMIZATION_ITEM_AUTHORITY_CHANGED")

        rows = list(
            session.scalars(
                select(OperationJournal)
                .where(
                    OperationJournal.operation == str(manifest["operation"]),
                    OperationJournal.plan_item_id == int(manifest["plan_item_id"]),
                )
                .order_by(OperationJournal.id.asc())
            )
        )
        matches: list[OperationJournal] = []
        for row in rows:
            payload = _journal_payload(row)
            if payload.get("phase") != phase:
                continue
            if payload.get("manifest") != manifest:
                raise StateConflictError(
                    f"STORAGE_OPTIMIZATION_JOURNAL_AUTHORITY_CHANGED:{phase}"
                )
            matches.append(row)
        if len(matches) > 1:
            raise StateConflictError(
                f"STORAGE_OPTIMIZATION_JOURNAL_DUPLICATE:{phase}"
            )
        if matches:
            session.rollback()
            return

        session.add(
            OperationJournal(
                operation=str(manifest["operation"]),
                sequence=int(manifest["sequence"]),
                plan_id=int(manifest["plan_id"]),
                plan_item_id=int(manifest["plan_item_id"]),
                task_id=task_id,
                user_id=user_id,
                before_json=_json({"phase": phase, "manifest": manifest}),
                after_json=_json(after or {}),
                metadata_before_json="{}",
                metadata_after_json="{}",
            )
        )
        if terminal_audit:
            session.add(
                AuditEvent(
                    operation=str(manifest["operation"]),
                    path=str(manifest["source_path"]),
                    result="completed",
                    details_json=_json(
                        {
                            "plan_id": int(manifest["plan_id"]),
                            "plan_item_id": int(manifest["plan_item_id"]),
                            "task_id": task_id,
                            "transaction_id": manifest["transaction_id"],
                            "storage_action": manifest["storage_action"],
                            "filesystem_mutation": True,
                        }
                    ),
                )
            )
        session.commit()


def _journals(
    session_factory: sessionmaker,
    manifest: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    with session_factory() as session:
        rows = list(
            session.scalars(
                select(OperationJournal)
                .where(
                    OperationJournal.operation == str(manifest["operation"]),
                    OperationJournal.plan_item_id == int(manifest["plan_item_id"]),
                )
                .order_by(OperationJournal.id.asc())
            )
        )
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row in rows:
        before = _journal_payload(row)
        phase = before.get("phase")
        if not isinstance(phase, str):
            continue
        if before.get("manifest") != manifest:
            raise StateConflictError("STORAGE_OPTIMIZATION_JOURNAL_AUTHORITY_CHANGED")
        if phase in result:
            raise StateConflictError(f"STORAGE_OPTIMIZATION_JOURNAL_DUPLICATE:{phase}")
        try:
            after = json.loads(row.after_json or "{}")
        except Exception as exc:
            raise StateConflictError(
                f"STORAGE_OPTIMIZATION_JOURNAL_AFTER_MALFORMED:{phase}"
            ) from exc
        if not isinstance(after, dict):
            raise StateConflictError(
                f"STORAGE_OPTIMIZATION_JOURNAL_AFTER_MALFORMED:{phase}"
            )
        result[phase] = (before, after)
    return result


def _open_regular(
    parent_fd: int,
    name: str,
    *,
    flags: int = os.O_RDONLY,
) -> int:
    return os.open(
        name,
        flags | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )


def _qualify_original(
    parent_fd: int,
    name: str,
    manifest: dict[str, Any],
    *,
    session_factory: sessionmaker,
    worker_id: str,
    failure_prefix: str,
) -> os.stat_result:
    expected = manifest["expected_source"]
    fd = _open_regular(parent_fd, name)
    try:
        return _qualify_fd(
            fd,
            expected_device=int(expected["device"]),
            expected_inode=int(expected["inode"]),
            expected_size=int(expected["size"]),
            expected_mtime_ns=int(expected["mtime_ns"]),
            expected_hash=str(expected["sha256"]),
            session_factory=session_factory,
            worker_id=worker_id,
            failure_prefix=failure_prefix,
        )
    finally:
        os.close(fd)


def _qualify_keep_fd(
    keep_fd: int,
    manifest: dict[str, Any],
    *,
    session_factory: sessionmaker,
    worker_id: str,
) -> os.stat_result:
    expected = manifest["expected_keep"]
    return _qualify_fd(
        keep_fd,
        expected_device=int(expected["device"]),
        expected_inode=int(expected["inode"]),
        expected_size=int(expected["size"]),
        expected_mtime_ns=int(expected["mtime_ns"]),
        expected_hash=str(expected["sha256"]),
        session_factory=session_factory,
        worker_id=worker_id,
        failure_prefix="STORAGE_OPTIMIZATION_KEEP",
    )


def _qualify_new(
    source_parent_fd: int,
    new_name: str,
    keep_stat: os.stat_result,
    manifest: dict[str, Any],
    *,
    session_factory: sessionmaker,
    worker_id: str,
) -> os.stat_result:
    fd = _open_regular(source_parent_fd, new_name)
    try:
        before = _qualify_fd(
            fd,
            expected_device=None,
            expected_inode=None,
            expected_size=int(manifest["expected_source"]["size"]),
            expected_mtime_ns=(
                int(manifest["expected_keep"]["mtime_ns"])
                if manifest["operation"] == "hardlink_optimize"
                else int(manifest["frozen_source_metadata"]["mtime_ns"])
            ),
            expected_hash=str(manifest["expected_source"]["sha256"]),
            session_factory=session_factory,
            worker_id=worker_id,
            failure_prefix="STORAGE_OPTIMIZATION_NEW",
        )
        if manifest["operation"] == "hardlink_optimize":
            if (int(before.st_dev), int(before.st_ino)) != (
                int(keep_stat.st_dev),
                int(keep_stat.st_ino),
            ):
                raise StateConflictError("STORAGE_OPTIMIZATION_NEW_HARDLINK_IDENTITY_CHANGED")
        else:
            if (int(before.st_dev), int(before.st_ino)) == (
                int(keep_stat.st_dev),
                int(keep_stat.st_ino),
            ):
                raise StateConflictError("STORAGE_OPTIMIZATION_NEW_REFLINK_NOT_INDEPENDENT")
            frozen_source = FrozenFileMetadata.from_json_dict(
                manifest["frozen_source_metadata"]
            )
            actual_metadata = capture_file_metadata_fd(fd)
            if not replacement_metadata_matches(actual_metadata, frozen_source):
                raise StateConflictError("STORAGE_OPTIMIZATION_NEW_METADATA_CHANGED")
        return before
    finally:
        os.close(fd)


def _qualify_published(
    source_parent_fd: int,
    source_name: str,
    keep_stat: os.stat_result,
    manifest: dict[str, Any],
    published_identity: dict[str, Any],
    *,
    session_factory: sessionmaker,
    worker_id: str,
) -> os.stat_result:
    fd = _open_regular(source_parent_fd, source_name)
    try:
        actual = _qualify_fd(
            fd,
            expected_device=int(published_identity["device"]),
            expected_inode=int(published_identity["inode"]),
            expected_size=int(manifest["expected_source"]["size"]),
            expected_mtime_ns=int(published_identity["mtime_ns"]),
            expected_hash=str(manifest["expected_source"]["sha256"]),
            session_factory=session_factory,
            worker_id=worker_id,
            failure_prefix="STORAGE_OPTIMIZATION_PUBLISHED",
        )
        if manifest["operation"] == "hardlink_optimize":
            if (int(actual.st_dev), int(actual.st_ino)) != (
                int(keep_stat.st_dev),
                int(keep_stat.st_ino),
            ):
                raise StateConflictError(
                    "STORAGE_OPTIMIZATION_PUBLISHED_HARDLINK_IDENTITY_CHANGED"
                )
        else:
            if (int(actual.st_dev), int(actual.st_ino)) == (
                int(keep_stat.st_dev),
                int(keep_stat.st_ino),
            ):
                raise StateConflictError(
                    "STORAGE_OPTIMIZATION_PUBLISHED_REFLINK_NOT_INDEPENDENT"
                )
            frozen_source = FrozenFileMetadata.from_json_dict(
                manifest["frozen_source_metadata"]
            )
            actual_metadata = capture_file_metadata_fd(fd)
            if not replacement_metadata_matches(actual_metadata, frozen_source):
                raise StateConflictError(
                    "STORAGE_OPTIMIZATION_PUBLISHED_METADATA_CHANGED"
                )
        return actual
    finally:
        os.close(fd)


def _create_new(
    *,
    keep_parent_fd: int,
    keep_name: str,
    keep_fd: int,
    keep_stat: os.stat_result,
    source_parent_fd: int,
    manifest: dict[str, Any],
    session_factory: sessionmaker,
    worker_id: str,
) -> os.stat_result:
    new_name = str(manifest["new_name"])
    if _stat_optional(source_parent_fd, new_name) is not None:
        return _qualify_new(
            source_parent_fd,
            new_name,
            keep_stat,
            manifest,
            session_factory=session_factory,
            worker_id=worker_id,
        )

    renew_and_assert_worker_lease(session_factory, worker_id)
    if manifest["operation"] == "hardlink_optimize":
        os.link(
            keep_name,
            new_name,
            src_dir_fd=keep_parent_fd,
            dst_dir_fd=source_parent_fd,
            follow_symlinks=False,
        )
    else:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        new_fd = os.open(new_name, flags, 0o600, dir_fd=source_parent_fd)
        try:
            fcntl.ioctl(new_fd, FICLONE, keep_fd)
            os.fsync(new_fd)
            # Full descriptor-bound verification before any SOURCE retirement.
            _qualify_fd(
                new_fd,
                expected_device=None,
                expected_inode=None,
                expected_size=int(manifest["expected_source"]["size"]),
                expected_mtime_ns=None,
                expected_hash=str(manifest["expected_source"]["sha256"]),
                session_factory=session_factory,
                worker_id=worker_id,
                failure_prefix="STORAGE_OPTIMIZATION_NEW_REFLINK",
            )
            frozen_source = FrozenFileMetadata.from_json_dict(
                manifest["frozen_source_metadata"]
            )
            apply_frozen_metadata_fd(new_fd, frozen_source)
            os.fsync(new_fd)
        finally:
            os.close(new_fd)

    os.fsync(source_parent_fd)
    return _qualify_new(
        source_parent_fd,
        new_name,
        keep_stat,
        manifest,
        session_factory=session_factory,
        worker_id=worker_id,
    )


def _ensure_initial_capability(
    manifest: dict[str, Any],
    *,
    allowed_roots: Iterable[Path | str],
) -> None:
    keep_parent = Path(str(manifest["keep_path"])).parent
    source_parent = Path(str(manifest["source_path"])).parent
    if manifest["operation"] == "hardlink_optimize":
        action_probe = probe_hardlink_between(
            keep_parent,
            source_parent,
            allowed_roots,
        )
    else:
        action_probe = probe_reflink_between(
            keep_parent,
            source_parent,
            allowed_roots,
        )
    if action_probe.capability is not StorageOptimizationCapability.SUPPORTED:
        raise StateConflictError(
            "STORAGE_OPTIMIZATION_EXECUTE_CAPABILITY_"
            f"{action_probe.capability.value.upper()}:{action_probe.reason}"
        )

    local_probe = probe_hardlink_capability(source_parent, allowed_roots)
    if local_probe.capability is not StorageOptimizationCapability.SUPPORTED:
        raise StateConflictError(
            "STORAGE_OPTIMIZATION_EXECUTE_LOCAL_PUBLISH_"
            f"{local_probe.capability.value.upper()}:{local_probe.reason}"
        )


def execute_storage_optimization(
    item: OperationItem,
    *,
    plan_id: str,
    allowed_roots: Iterable[Path | str],
    session_factory: sessionmaker,
    worker_id: str,
) -> str:
    if item.operation not in OPTIMIZATION_OPERATIONS:
        raise StateConflictError("STORAGE_OPTIMIZATION_OPERATION_UNSUPPORTED")
    if item.keep is None or not item.expected_hash:
        raise StateConflictError("STORAGE_OPTIMIZATION_FROZEN_AUTHORITY_MISSING")

    item_id, user_id, manifest = _load_authority(
        session_factory,
        item,
        plan_id=plan_id,
    )
    task_id: int
    with session_factory() as session:
        row = session.get(BatchPlanItem, item_id)
        assert row is not None
        item_meta = _parse_json_dict(row.metadata_json, label="STORAGE_OPTIMIZATION_ITEM_METADATA")
        execution = item_meta.get("execution")
        assert isinstance(execution, dict)
        task_id = int(execution["task_id"])

    source_path = Path(str(manifest["source_path"]))
    keep_path = Path(str(manifest["keep_path"]))
    new_name = str(manifest["new_name"])
    old_name = str(manifest["old_name"])

    with ExitStack() as stack:
        source_parent_fd, source_name = stack.enter_context(
            safe_open_parent_fd(source_path, allowed_roots)
        )
        keep_parent_fd, keep_name = stack.enter_context(
            safe_open_parent_fd(keep_path, allowed_roots)
        )
        keep_fd = _open_regular(keep_parent_fd, keep_name)
        stack.callback(os.close, keep_fd)

        keep_stat = _qualify_keep_fd(
            keep_fd,
            manifest,
            session_factory=session_factory,
            worker_id=worker_id,
        )

        journals = _journals(session_factory, manifest)
        completed = journals.get("completed")
        published = journals.get("published")

        if completed is not None:
            published_row = journals.get("published")
            if published_row is None:
                raise StateConflictError("STORAGE_OPTIMIZATION_COMPLETED_WITHOUT_PUBLICATION")
            published_identity = published_row[1].get("published_identity")
            if not isinstance(published_identity, dict):
                raise StateConflictError("STORAGE_OPTIMIZATION_PUBLISHED_IDENTITY_MISSING")
            _qualify_published(
                source_parent_fd,
                source_name,
                keep_stat,
                manifest,
                published_identity,
                session_factory=session_factory,
                worker_id=worker_id,
            )
            if _stat_optional(source_parent_fd, old_name) is not None:
                raise StateConflictError("STORAGE_OPTIMIZATION_COMPLETED_OLD_ANCHOR_REAPPEARED")
            return f"{manifest['storage_action']} optimization already completed"

        # Once publication has a durable journal, recovery must never create a
        # fresh .new candidate. The published pathname itself is now the
        # authoritative optimized copy; only NFC-owned aliases may remain.
        if published is not None:
            published_identity = published[1].get("published_identity")
            if not isinstance(published_identity, dict):
                raise StateConflictError("STORAGE_OPTIMIZATION_PUBLISHED_IDENTITY_MISSING")
            _qualify_published(
                source_parent_fd,
                source_name,
                keep_stat,
                manifest,
                published_identity,
                session_factory=session_factory,
                worker_id=worker_id,
            )

            new_stat = _stat_optional(source_parent_fd, new_name)
            if new_stat is not None:
                source_stat = os.stat(
                    source_name,
                    dir_fd=source_parent_fd,
                    follow_symlinks=False,
                )
                if (int(new_stat.st_dev), int(new_stat.st_ino)) != (
                    int(source_stat.st_dev),
                    int(source_stat.st_ino),
                ):
                    raise StateConflictError("STORAGE_OPTIMIZATION_NEW_ALIAS_FOREIGN")
                _qualify_new(
                    source_parent_fd,
                    new_name,
                    keep_stat,
                    manifest,
                    session_factory=session_factory,
                    worker_id=worker_id,
                )
                renew_and_assert_worker_lease(session_factory, worker_id)
                os.unlink(new_name, dir_fd=source_parent_fd)
                os.fsync(source_parent_fd)

            _phase_journal(
                session_factory,
                worker_id=worker_id,
                manifest=manifest,
                phase="old_retire_intent",
                task_id=task_id,
                user_id=user_id,
                after={},
            )
            old_stat = _stat_optional(source_parent_fd, old_name)
            if old_stat is not None:
                _qualify_original(
                    source_parent_fd,
                    old_name,
                    manifest,
                    session_factory=session_factory,
                    worker_id=worker_id,
                    failure_prefix="STORAGE_OPTIMIZATION_OLD",
                )
                _qualify_published(
                    source_parent_fd,
                    source_name,
                    keep_stat,
                    manifest,
                    published_identity,
                    session_factory=session_factory,
                    worker_id=worker_id,
                )
                renew_and_assert_worker_lease(session_factory, worker_id)
                os.unlink(old_name, dir_fd=source_parent_fd)
                os.fsync(source_parent_fd)

            _phase_journal(
                session_factory,
                worker_id=worker_id,
                manifest=manifest,
                phase="completed",
                task_id=task_id,
                user_id=user_id,
                after={"published_identity": published_identity},
                terminal_audit=True,
            )
            return f"{manifest['storage_action']} optimization recovered after publication"

        # A fresh transaction must prove capability immediately before creating
        # its first private optimized candidate. Recovery of an already-created
        # .new/.old transaction never invents new capability authority.
        if (
            _stat_optional(source_parent_fd, new_name) is None
            and _stat_optional(source_parent_fd, old_name) is None
            and "prepared_new" not in journals
        ):
            _qualify_original(
                source_parent_fd,
                source_name,
                manifest,
                session_factory=session_factory,
                worker_id=worker_id,
                failure_prefix="STORAGE_OPTIMIZATION_SOURCE",
            )
            _ensure_initial_capability(manifest, allowed_roots=allowed_roots)

        new_stat = _create_new(
            keep_parent_fd=keep_parent_fd,
            keep_name=keep_name,
            keep_fd=keep_fd,
            keep_stat=keep_stat,
            source_parent_fd=source_parent_fd,
            manifest=manifest,
            session_factory=session_factory,
            worker_id=worker_id,
        )
        _phase_journal(
            session_factory,
            worker_id=worker_id,
            manifest=manifest,
            phase="prepared_new",
            task_id=task_id,
            user_id=user_id,
            after={"new_identity": _identity(new_stat)},
        )
        journals = _journals(session_factory, manifest)

        old_stat = _stat_optional(source_parent_fd, old_name)
        source_stat = _stat_optional(source_parent_fd, source_name)

        if old_stat is None:
            if source_stat is None:
                raise StateConflictError(
                    "STORAGE_OPTIMIZATION_SOURCE_AND_OLD_MISSING_BEFORE_CAPTURE"
                )
            _qualify_original(
                source_parent_fd,
                source_name,
                manifest,
                session_factory=session_factory,
                worker_id=worker_id,
                failure_prefix="STORAGE_OPTIMIZATION_SOURCE",
            )
            renew_and_assert_worker_lease(session_factory, worker_id)
            os.link(
                source_name,
                old_name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
                follow_symlinks=False,
            )
            os.fsync(source_parent_fd)
            old_stat = _qualify_original(
                source_parent_fd,
                old_name,
                manifest,
                session_factory=session_factory,
                worker_id=worker_id,
                failure_prefix="STORAGE_OPTIMIZATION_OLD",
            )
        else:
            old_stat = _qualify_original(
                source_parent_fd,
                old_name,
                manifest,
                session_factory=session_factory,
                worker_id=worker_id,
                failure_prefix="STORAGE_OPTIMIZATION_OLD",
            )
            if source_stat is not None and (
                int(source_stat.st_dev),
                int(source_stat.st_ino),
            ) == (int(old_stat.st_dev), int(old_stat.st_ino)):
                _qualify_original(
                    source_parent_fd,
                    source_name,
                    manifest,
                    session_factory=session_factory,
                    worker_id=worker_id,
                    failure_prefix="STORAGE_OPTIMIZATION_SOURCE",
                )

        _phase_journal(
            session_factory,
            worker_id=worker_id,
            manifest=manifest,
            phase="captured_old",
            task_id=task_id,
            user_id=user_id,
            after={"old_identity": _identity(old_stat)},
        )
        journals = _journals(session_factory, manifest)

        # If source still names the original inode, retire only after durable
        # captured-old authority and a fresh descriptor-bound SHA fence.
        source_stat = _stat_optional(source_parent_fd, source_name)
        if source_stat is not None and (
            int(source_stat.st_dev),
            int(source_stat.st_ino),
        ) == (
            int(manifest["expected_source"]["device"]),
            int(manifest["expected_source"]["inode"]),
        ):
            _phase_journal(
                session_factory,
                worker_id=worker_id,
                manifest=manifest,
                phase="source_retire_intent",
                task_id=task_id,
                user_id=user_id,
                after={},
            )
            _qualify_original(
                source_parent_fd,
                source_name,
                manifest,
                session_factory=session_factory,
                worker_id=worker_id,
                failure_prefix="STORAGE_OPTIMIZATION_SOURCE",
            )
            renew_and_assert_worker_lease(session_factory, worker_id)
            os.unlink(source_name, dir_fd=source_parent_fd)
            os.fsync(source_parent_fd)
            _phase_journal(
                session_factory,
                worker_id=worker_id,
                manifest=manifest,
                phase="source_retired",
                task_id=task_id,
                user_id=user_id,
                after={},
            )
            source_stat = None

        journals = _journals(session_factory, manifest)
        published = journals.get("published")

        if published is None:
            source_stat = _stat_optional(source_parent_fd, source_name)
            if source_stat is None:
                new_stat = _qualify_new(
                    source_parent_fd,
                    new_name,
                    keep_stat,
                    manifest,
                    session_factory=session_factory,
                    worker_id=worker_id,
                )
                renew_and_assert_worker_lease(session_factory, worker_id)
                os.link(
                    new_name,
                    source_name,
                    src_dir_fd=source_parent_fd,
                    dst_dir_fd=source_parent_fd,
                    follow_symlinks=False,
                )
                os.fsync(source_parent_fd)
                source_after = os.stat(
                    source_name,
                    dir_fd=source_parent_fd,
                    follow_symlinks=False,
                )
                if (int(source_after.st_dev), int(source_after.st_ino)) != (
                    int(new_stat.st_dev),
                    int(new_stat.st_ino),
                ):
                    raise StateConflictError(
                        "STORAGE_OPTIMIZATION_PUBLICATION_IDENTITY_MISMATCH"
                    )
                published_identity = _identity(source_after)
            else:
                # Crash after link publication but before journal: ownership is
                # provable only while .new still exists as the same inode.
                new_stat = _stat_optional(source_parent_fd, new_name)
                if new_stat is None or (
                    int(source_stat.st_dev),
                    int(source_stat.st_ino),
                ) != (int(new_stat.st_dev), int(new_stat.st_ino)):
                    raise StateConflictError(
                        "STORAGE_OPTIMIZATION_PUBLICATION_AMBIGUOUS"
                    )
                _qualify_new(
                    source_parent_fd,
                    new_name,
                    keep_stat,
                    manifest,
                    session_factory=session_factory,
                    worker_id=worker_id,
                )
                published_identity = _identity(source_stat)

            _qualify_published(
                source_parent_fd,
                source_name,
                keep_stat,
                manifest,
                published_identity,
                session_factory=session_factory,
                worker_id=worker_id,
            )
            _phase_journal(
                session_factory,
                worker_id=worker_id,
                manifest=manifest,
                phase="published",
                task_id=task_id,
                user_id=user_id,
                after={"published_identity": published_identity},
            )
            published = _journals(session_factory, manifest).get("published")

        assert published is not None
        published_identity = published[1].get("published_identity")
        if not isinstance(published_identity, dict):
            raise StateConflictError("STORAGE_OPTIMIZATION_PUBLISHED_IDENTITY_MISSING")
        _qualify_published(
            source_parent_fd,
            source_name,
            keep_stat,
            manifest,
            published_identity,
            session_factory=session_factory,
            worker_id=worker_id,
        )

        # Retire the private .new alias only after publication identity is
        # durable. It is merely another name for the already-published inode.
        new_stat = _stat_optional(source_parent_fd, new_name)
        if new_stat is not None:
            source_stat = os.stat(
                source_name,
                dir_fd=source_parent_fd,
                follow_symlinks=False,
            )
            if (int(new_stat.st_dev), int(new_stat.st_ino)) != (
                int(source_stat.st_dev),
                int(source_stat.st_ino),
            ):
                raise StateConflictError("STORAGE_OPTIMIZATION_NEW_ALIAS_FOREIGN")
            renew_and_assert_worker_lease(session_factory, worker_id)
            os.unlink(new_name, dir_fd=source_parent_fd)
            os.fsync(source_parent_fd)

        _phase_journal(
            session_factory,
            worker_id=worker_id,
            manifest=manifest,
            phase="old_retire_intent",
            task_id=task_id,
            user_id=user_id,
            after={},
        )

        old_stat = _stat_optional(source_parent_fd, old_name)
        if old_stat is not None:
            _qualify_original(
                source_parent_fd,
                old_name,
                manifest,
                session_factory=session_factory,
                worker_id=worker_id,
                failure_prefix="STORAGE_OPTIMIZATION_OLD",
            )
            # Re-verify the published optimized pathname immediately before the
            # only payload-destroying unlink in this transaction.
            _qualify_published(
                source_parent_fd,
                source_name,
                keep_stat,
                manifest,
                published_identity,
                session_factory=session_factory,
                worker_id=worker_id,
            )
            renew_and_assert_worker_lease(session_factory, worker_id)
            os.unlink(old_name, dir_fd=source_parent_fd)
            os.fsync(source_parent_fd)

        _phase_journal(
            session_factory,
            worker_id=worker_id,
            manifest=manifest,
            phase="completed",
            task_id=task_id,
            user_id=user_id,
            after={"published_identity": published_identity},
            terminal_audit=True,
        )

        return f"{manifest['storage_action']} optimization completed"
