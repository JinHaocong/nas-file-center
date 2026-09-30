from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.batch.plans import OperationItem
from app.config import Settings
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.service import FileCenterService
from app.storage_optimization.capability import (
    CapabilityProbeResult,
    StorageOptimizationCapability,
)
from app.storage_optimization.executor import execute_storage_optimization
from app.storage_optimization.metadata import capture_file_metadata
from app.tasks.state_machine import JobLeaseLost


WORKER_ID = "storage-opt-test-worker"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(
    tmp_path: Path,
    *,
    operation: str = "hardlink_optimize",
):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    settings = Settings(
        config_dir=config,
        data_mount=data,
        quarantine_root=quarantine,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
    )
    service = FileCenterService(settings)

    keep = data / "keep.bin"
    source = data / "source.bin"
    payload = (b"nas-file-center-storage-optimization-" * 512)
    keep.write_bytes(payload)
    source.write_bytes(payload)

    # Keep inode-level metadata compatible for Hardlink.
    keep.chmod(0o640)
    source.chmod(0o640)

    keep_st = keep.stat(follow_symlinks=False)
    source_st = source.stat(follow_symlinks=False)
    keep_meta = capture_file_metadata(keep)
    source_meta = capture_file_metadata(source)
    content_hash = _sha256(source)
    tx_id = "0123456789abcdef0123456789abcdef"

    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="storage-opt-test",
            kind="dedupe",
            status="ready",
            expected_changes=1,
            expected_reclaim_bytes=source_st.st_size,
            metadata_json=json.dumps(
                {
                    "source": "dedupe",
                    "storage_action": (
                        "hardlink" if operation == "hardlink_optimize" else "reflink"
                    ),
                },
                sort_keys=True,
            ),
        )
        session.add(plan)
        session.flush()

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps(
                {"plan_id": int(plan.id), "requested_by_user_id": None},
                sort_keys=True,
            ),
            created_at=utcnow(),
            started_at=utcnow(),
        )
        session.add(job)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=0,
            operation=operation,
            source_path=str(source),
            target_path=None,
            keep_path=str(keep),
            expected_size=int(source_st.st_size),
            expected_mtime_ns=int(source_st.st_mtime_ns),
            expected_device=int(source_st.st_dev),
            expected_inode=int(source_st.st_ino),
            expected_hash=content_hash,
            state="executing",
            metadata_json=json.dumps(
                {
                    "storage_action": (
                        "hardlink" if operation == "hardlink_optimize" else "reflink"
                    ),
                    "storage_optimization_transaction_id": tx_id,
                    "keep_snapshot": {
                        "device": int(keep_st.st_dev),
                        "inode": int(keep_st.st_ino),
                        "size": int(keep_st.st_size),
                        "mtime_ns": int(keep_st.st_mtime_ns),
                        "object_type": "file",
                        "hash": content_hash,
                    },
                    "storage_optimization": {
                        "schema_version": 1,
                        "transaction_id": tx_id,
                        "operation": operation,
                        "frozen_source_metadata": source_meta.to_json_dict(),
                        "frozen_keep_metadata": keep_meta.to_json_dict(),
                        "metadata_reason": "test",
                    },
                    "execution": {
                        "phase": "intent",
                        "task_id": int(job.id),
                        "operation": operation,
                    },
                },
                sort_keys=True,
            ),
        )
        session.add(item)

        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(
                id=1,
                locked=True,
                owner=WORKER_ID,
                acquired_at=utcnow(),
            )
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = WORKER_ID
            lock.acquired_at = utcnow()

        session.commit()
        plan_id = int(plan.id)
        item_id = int(item.id)

    op = OperationItem(
        sequence=0,
        operation=operation,
        source=source,
        keep=keep,
        expected_size=int(source_st.st_size),
        expected_hash=content_hash,
        state="executing",
        expected_mtime_ns=int(source_st.st_mtime_ns),
        expected_device=int(source_st.st_dev),
        expected_inode=int(source_st.st_ino),
    )
    return {
        "service": service,
        "settings": settings,
        "keep": keep,
        "source": source,
        "payload": payload,
        "source_original_inode": int(source_st.st_ino),
        "keep_original_inode": int(keep_st.st_ino),
        "plan_id": plan_id,
        "item_id": item_id,
        "item": op,
        "tx_id": tx_id,
    }


def _journal_phases(env) -> list[str]:
    with env["service"].SessionLocal() as session:
        rows = list(
            session.scalars(
                select(OperationJournal)
                .where(OperationJournal.plan_item_id == env["item_id"])
                .order_by(OperationJournal.id.asc())
            )
        )
    phases: list[str] = []
    for row in rows:
        before = json.loads(row.before_json or "{}")
        phase = before.get("phase")
        if isinstance(phase, str):
            phases.append(phase)
    return phases


def _emulate_ficlone(dst_fd: int, request: int, src_fd: int):
    from app.storage_optimization.capability import FICLONE

    assert request == FICLONE
    src_pos = os.lseek(src_fd, 0, os.SEEK_CUR)
    dst_pos = os.lseek(dst_fd, 0, os.SEEK_CUR)
    try:
        os.lseek(src_fd, 0, os.SEEK_SET)
        payload = bytearray()
        while True:
            chunk = os.read(src_fd, 1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
        os.ftruncate(dst_fd, 0)
        os.lseek(dst_fd, 0, os.SEEK_SET)
        os.write(dst_fd, bytes(payload))
    finally:
        os.lseek(src_fd, src_pos, os.SEEK_SET)
        os.lseek(dst_fd, dst_pos, os.SEEK_SET)
    return 0


def test_hardlink_optimization_success_is_journaled_and_preserves_path(tmp_path: Path):
    env = _seed(tmp_path, operation="hardlink_optimize")

    reason = execute_storage_optimization(
        env["item"],
        plan_id=str(env["plan_id"]),
        allowed_roots=env["settings"].allowed_roots,
        session_factory=env["service"].SessionLocal,
        worker_id=WORKER_ID,
    )

    assert "completed" in reason
    assert env["source"].read_bytes() == env["payload"]
    assert env["keep"].read_bytes() == env["payload"]
    assert env["source"].stat().st_ino == env["keep"].stat().st_ino
    assert env["source"].stat().st_ino == env["keep_original_inode"]
    assert env["source_original_inode"] != env["source"].stat().st_ino

    parent = env["source"].parent
    assert not (parent / f".__nfc_opt_{env['tx_id']}.new").exists()
    assert not (parent / f".__nfc_opt_{env['tx_id']}.old").exists()

    phases = _journal_phases(env)
    assert phases == [
        "prepared_new",
        "captured_old",
        "source_retire_intent",
        "source_retired",
        "published",
        "old_retire_intent",
        "completed",
    ]

    with env["service"].SessionLocal() as session:
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.operation == "hardlink_optimize",
                    AuditEvent.result == "completed",
                )
            )
        )
        assert len(audits) == 1


def test_reflink_optimization_preserves_independent_inode_semantics(
    tmp_path: Path,
    monkeypatch,
):
    env = _seed(tmp_path, operation="reflink_optimize")

    monkeypatch.setattr(
        "app.storage_optimization.executor.probe_reflink_between",
        lambda *_args, **_kwargs: CapabilityProbeResult(
            StorageOptimizationCapability.SUPPORTED,
            "reflink",
            "test-supported",
        ),
    )
    monkeypatch.setattr(
        "app.storage_optimization.executor.fcntl.ioctl",
        _emulate_ficlone,
    )

    execute_storage_optimization(
        env["item"],
        plan_id=str(env["plan_id"]),
        allowed_roots=env["settings"].allowed_roots,
        session_factory=env["service"].SessionLocal,
        worker_id=WORKER_ID,
    )

    assert env["source"].read_bytes() == env["payload"]
    assert env["keep"].read_bytes() == env["payload"]
    assert env["source"].stat().st_ino != env["keep"].stat().st_ino

    with env["source"].open("r+b") as handle:
        handle.seek(0)
        handle.write(b"X")
        handle.flush()
        os.fsync(handle.fileno())

    assert env["source"].read_bytes() != env["keep"].read_bytes()
    assert env["keep"].read_bytes() == env["payload"]


@pytest.mark.parametrize(
    "crash_phase",
    [
        "prepared_new",
        "captured_old",
        "source_retired",
        "published",
        "completed",
    ],
)
def test_hardlink_crash_windows_converge_without_payload_loss(
    tmp_path: Path,
    monkeypatch,
    crash_phase: str,
):
    env = _seed(tmp_path, operation="hardlink_optimize")
    import app.storage_optimization.executor as executor_module

    original_phase_journal = executor_module._phase_journal
    fired = {"value": False}

    def crash_once(*args, **kwargs):
        if kwargs.get("phase") == crash_phase and not fired["value"]:
            fired["value"] = True
            raise RuntimeError(f"synthetic-crash:{crash_phase}")
        return original_phase_journal(*args, **kwargs)

    monkeypatch.setattr(executor_module, "_phase_journal", crash_once)

    with pytest.raises(RuntimeError, match="synthetic-crash"):
        execute_storage_optimization(
            env["item"],
            plan_id=str(env["plan_id"]),
            allowed_roots=env["settings"].allowed_roots,
            session_factory=env["service"].SessionLocal,
            worker_id=WORKER_ID,
        )

    # At every injected crash point, at least one NFC-authorized path still
    # carries the complete payload.
    parent = env["source"].parent
    candidates = [
        env["source"],
        parent / f".__nfc_opt_{env['tx_id']}.new",
        parent / f".__nfc_opt_{env['tx_id']}.old",
        env["keep"],
    ]
    assert any(
        path.exists() and path.is_file() and path.read_bytes() == env["payload"]
        for path in candidates
    )

    monkeypatch.setattr(executor_module, "_phase_journal", original_phase_journal)

    reason = execute_storage_optimization(
        env["item"],
        plan_id=str(env["plan_id"]),
        allowed_roots=env["settings"].allowed_roots,
        session_factory=env["service"].SessionLocal,
        worker_id=WORKER_ID,
    )

    assert "completed" in reason or "recovered" in reason
    assert env["source"].read_bytes() == env["payload"]
    assert env["source"].stat().st_ino == env["keep"].stat().st_ino
    assert not (parent / f".__nfc_opt_{env['tx_id']}.new").exists()
    assert not (parent / f".__nfc_opt_{env['tx_id']}.old").exists()
    assert _journal_phases(env).count("completed") == 1


def test_foreign_transaction_new_path_is_preserved_and_blocks_execution(tmp_path: Path):
    env = _seed(tmp_path, operation="hardlink_optimize")
    foreign = env["source"].parent / f".__nfc_opt_{env['tx_id']}.new"
    foreign.write_bytes(b"foreign-payload")

    with pytest.raises(Exception):
        execute_storage_optimization(
            env["item"],
            plan_id=str(env["plan_id"]),
            allowed_roots=env["settings"].allowed_roots,
            session_factory=env["service"].SessionLocal,
            worker_id=WORKER_ID,
        )

    assert foreign.read_bytes() == b"foreign-payload"
    assert env["source"].read_bytes() == env["payload"]
    assert env["keep"].read_bytes() == env["payload"]


def test_source_aba_is_rejected_before_retirement(tmp_path: Path):
    env = _seed(tmp_path, operation="hardlink_optimize")
    old_source = env["source"]
    replacement = old_source.with_suffix(".replacement")
    replacement.write_bytes(env["payload"])
    os.replace(replacement, old_source)

    assert old_source.stat().st_ino != env["source_original_inode"]

    with pytest.raises(Exception):
        execute_storage_optimization(
            env["item"],
            plan_id=str(env["plan_id"]),
            allowed_roots=env["settings"].allowed_roots,
            session_factory=env["service"].SessionLocal,
            worker_id=WORKER_ID,
        )

    assert env["source"].read_bytes() == env["payload"]
    assert env["keep"].read_bytes() == env["payload"]


def test_keep_change_is_rejected_before_source_retirement(tmp_path: Path):
    env = _seed(tmp_path, operation="hardlink_optimize")
    env["keep"].write_bytes(b"changed-keep")

    with pytest.raises(Exception):
        execute_storage_optimization(
            env["item"],
            plan_id=str(env["plan_id"]),
            allowed_roots=env["settings"].allowed_roots,
            session_factory=env["service"].SessionLocal,
            worker_id=WORKER_ID,
        )

    assert env["source"].read_bytes() == env["payload"]
    assert env["source"].stat().st_ino == env["source_original_inode"]


def test_lease_loss_before_first_mutation_preserves_both_payloads(
    tmp_path: Path,
    monkeypatch,
):
    env = _seed(tmp_path, operation="hardlink_optimize")

    def lose_lease(*_args, **_kwargs):
        raise JobLeaseLost("synthetic lease loss")

    monkeypatch.setattr(
        "app.storage_optimization.executor.renew_and_assert_worker_lease",
        lose_lease,
    )

    with pytest.raises(JobLeaseLost):
        execute_storage_optimization(
            env["item"],
            plan_id=str(env["plan_id"]),
            allowed_roots=env["settings"].allowed_roots,
            session_factory=env["service"].SessionLocal,
            worker_id=WORKER_ID,
        )

    assert env["source"].read_bytes() == env["payload"]
    assert env["keep"].read_bytes() == env["payload"]
    assert env["source"].stat().st_ino == env["source_original_inode"]


def test_late_source_hardlink_blocks_reclaim_before_transaction_starts(tmp_path: Path):
    env = _seed(tmp_path, operation="hardlink_optimize")
    alias = env["source"].parent / "late-source-alias.bin"
    os.link(env["source"], alias)
    assert env["source"].stat().st_nlink == 2

    with pytest.raises(Exception, match="SOURCE_HAS_ADDITIONAL_HARDLINKS"):
        execute_storage_optimization(
            env["item"],
            plan_id=str(env["plan_id"]),
            allowed_roots=env["settings"].allowed_roots,
            session_factory=env["service"].SessionLocal,
            worker_id=WORKER_ID,
        )

    assert env["source"].read_bytes() == env["payload"]
    assert alias.read_bytes() == env["payload"]
    assert env["keep"].read_bytes() == env["payload"]
    parent = env["source"].parent
    assert not (parent / f".__nfc_opt_{env['tx_id']}.old").exists()


def test_hardlink_added_after_old_capture_blocks_source_retirement(
    tmp_path: Path,
    monkeypatch,
):
    env = _seed(tmp_path, operation="hardlink_optimize")
    import app.storage_optimization.executor as executor_module

    original_phase_journal = executor_module._phase_journal
    alias = env["source"].parent / "race-source-alias.bin"
    injected = {"value": False}

    def inject_alias_after_capture(*args, **kwargs):
        result = original_phase_journal(*args, **kwargs)
        if kwargs.get("phase") == "captured_old" and not injected["value"]:
            injected["value"] = True
            os.link(env["source"], alias)
        return result

    monkeypatch.setattr(
        executor_module,
        "_phase_journal",
        inject_alias_after_capture,
    )

    with pytest.raises(Exception, match="SOURCE_LINK_COUNT_CHANGED_BEFORE_RETIRE"):
        execute_storage_optimization(
            env["item"],
            plan_id=str(env["plan_id"]),
            allowed_roots=env["settings"].allowed_roots,
            session_factory=env["service"].SessionLocal,
            worker_id=WORKER_ID,
        )

    assert env["source"].read_bytes() == env["payload"]
    assert alias.read_bytes() == env["payload"]
    assert env["keep"].read_bytes() == env["payload"]
    old_anchor = env["source"].parent / f".__nfc_opt_{env['tx_id']}.old"
    assert old_anchor.exists()
    assert old_anchor.read_bytes() == env["payload"]
