from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.exceptions import StateConflictError
from app.models import (
    BatchPlan,
    BatchPlanItem,
    DuplicateFile,
    DuplicateGroup,
    OperationJournal,
    QuarantineEntry,
    ScanJob,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.planning.dedupe_engine import directory_ancestors_to_scan_root
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler


RECURSIVE_MODE = "recursive_directory_balanced_by_bytes"


def _setup_env(tmp_path: Path) -> dict:
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    config_dir.mkdir()
    quarantine_dir = data_dir / ".nas-file-center-trash"
    quarantine_dir.mkdir()

    settings = Settings(
        config_dir=config_dir,
        database_path=config_dir / "app.db",
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        protect_last_file=True,
        allow_mutation=True,
        allow_delete=True,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    return {
        "service": service,
        "settings": settings,
        "SessionLocal": service.SessionLocal,
        "root": data_dir,
        "quarantine": quarantine_dir,
    }


def _recursive_config() -> dict:
    return {
        "schema_version": 1,
        "selection_mode": RECURSIVE_MODE,
        "factors": {},
    }


def _create_completed_scan(env: dict, *, scan_id: int) -> tuple[Path, Path]:
    root: Path = env["root"]
    left_dir = root / "A" / "deep"
    right_dir = root / "B" / "deep"
    left_dir.mkdir(parents=True)
    right_dir.mkdir(parents=True)

    payload = b"gate6b-amendment-a-lifecycle"
    left = left_dir / "dup.bin"
    right = right_dir / "dup.bin"
    left.write_bytes(payload)
    right.write_bytes(payload)
    (left_dir / "extra.bin").write_bytes(b"keep-left-subtree-alive")
    (right_dir / "extra.bin").write_bytes(b"keep-right-subtree-alive")

    with env["SessionLocal"]() as session:
        session.add(
            ScanJob(
                id=scan_id,
                name=f"amendment-a-{scan_id}",
                mode="normal",
                roots_json=json.dumps([str(root)]),
                status="completed",
                started_at=utcnow(),
                finished_at=utcnow(),
                total_groups=1,
                total_files_in_groups=2,
                reclaimable_bytes=len(payload),
            )
        )
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=hashlib.sha256(payload).hexdigest(),
            file_size=len(payload),
            member_count=2,
        )
        session.add(group)
        session.flush()
        for path in (left, right):
            st = os.lstat(path)
            relative = path.relative_to(root)
            session.add(
                DuplicateFile(
                    group_id=group.id,
                    root_id=0,
                    absolute_path=str(path),
                    relative_path=relative.as_posix(),
                    top_level_dir=str(root / relative.parts[0]),
                    size=st.st_size,
                    mtime_ns=st.st_mtime_ns,
                    device=st.st_dev,
                    inode=st.st_ino,
                )
            )
        session.commit()
    return left, right


def _generate(env: dict, *, scan_id: int) -> dict:
    left, right = _create_completed_scan(env, scan_id=scan_id)
    service: FileCenterService = env["service"]
    config = _recursive_config()
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)
    generated = service.create_advanced_dedupe_plan(
        scan_id,
        scorer_config=config,
        expected_preview_digest=preview["preview_digest"],
    )
    plan_id = int(generated["id"])

    with env["SessionLocal"]() as session:
        rows = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert len(rows) == 1
        row = rows[0]
        metadata = json.loads(row.metadata_json or "{}")
        source = Path(row.source_path)
        keeper = Path(row.keep_path or "")
        assert row.operation == "quarantine"

    assert source in {left, right}
    assert keeper in {left, right}
    assert keeper != source
    authority = metadata["recursive_protection"]
    assert authority["source_path"] == str(source)
    assert authority["scan_root_path"] == str(env["root"])
    assert authority["protected_ancestors"] == list(
        directory_ancestors_to_scan_root(str(source), str(env["root"]))
    )

    return {
        "plan_id": plan_id,
        "source": source,
        "keeper": keeper,
    }


def _acquire_lease(service: FileCenterService, worker_id: str) -> None:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        session.commit()


def _execute_with_worker(env: dict, plan_id: int, *, worker_id: str) -> None:
    service: FileCenterService = env["service"]
    enqueued = service.enqueue_plan_execution(plan_id)
    job_id = int(enqueued["work_job_id"])
    handler = get_handler("batch-plan-execute")
    assert handler is not None
    _acquire_lease(service, worker_id)

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        job.status = "running"
        job.started_at = utcnow()
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id=worker_id)
        handler.run(job, context, env["settings"])

    # The production worker owns WorkJob terminalization around handler.run().
    # This fixture calls the handler directly, so close the synthetic job here.
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        if job.status == "running":
            job.status = "completed"
            job.finished_at = utcnow()
            session.commit()


def _plan_item_state(env: dict, plan_id: int) -> tuple[str, str, str | None, dict]:
    with env["SessionLocal"]() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        row = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert row is not None
        return plan.status, row.state, row.reason, json.loads(row.metadata_json or "{}")


def _remove_other_regular_files(source: Path) -> None:
    for sibling in list(source.parent.iterdir()):
        if sibling != source and sibling.is_file() and not sibling.is_symlink():
            sibling.unlink()
    assert source.exists()
    assert sum(1 for p in source.parent.iterdir() if p.is_file() and not p.is_symlink()) == 1


def test_amendment_a_real_generate_freeze_validate_execute_quarantine_and_undo_available(tmp_path: Path):
    env = _setup_env(tmp_path)
    service: FileCenterService = env["service"]
    case = _generate(env, scan_id=1501)
    plan_id = case["plan_id"]
    source: Path = case["source"]
    keeper: Path = case["keeper"]

    service.freeze_plan(plan_id)
    status, item_state, _reason, metadata = _plan_item_state(env, plan_id)
    assert status == "frozen"
    assert item_state == "planned", "Freeze seals the plan while items remain planned until Validate"
    authority = metadata["recursive_protection"]
    frozen = metadata["frozen_recursive_protection"]
    assert frozen["scope_digest"]
    assert list(frozen["frozen_ancestors"].keys()) == authority["protected_ancestors"]

    # Safe count/tree changes are allowed: Validate checks current safety, not snapshot equality.
    benign = source.parent / "benign-after-freeze.bin"
    benign.write_bytes(b"benign-current-state-change")
    empty_child = source.parent / "empty-child-must-not-be-removed"
    empty_child.mkdir()

    validated = service.validate_plan(plan_id)
    assert validated["status"] == "ready"
    _execute_with_worker(env, plan_id, worker_id="gate6b-amendment-a-happy")

    status, item_state, reason, _metadata = _plan_item_state(env, plan_id)
    assert status == "completed"
    assert item_state == "completed"
    assert reason == "quarantined"
    assert not source.exists()
    assert keeper.exists()
    assert benign.exists()
    assert empty_child.exists(), "recursive dedupe must not auto-remove empty directories"

    with env["SessionLocal"]() as session:
        row = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert row is not None and row.operation == "quarantine"
        qentry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == row.id))
        assert qentry is not None and qentry.state == "active"
        assert Path(qentry.quarantine_path).exists(), "completed dedupe is recoverable Quarantine, not permanent delete"
        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == row.id))
        assert journal is not None and journal.operation == "quarantine"
        qentry_id = qentry.id

    undo = service.create_undo_plan(plan_id)
    assert undo["kind"] == "undo"
    assert undo["status"] == "draft"
    with env["SessionLocal"]() as session:
        undo_row = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == undo["id"]))
        assert undo_row is not None
        undo_meta = json.loads(undo_row.metadata_json or "{}")
        assert undo_row.operation == "restore"
        assert undo_meta["quarantine_entry_id"] == qentry_id


def test_amendment_a_change_after_generate_before_validate_is_blocked_without_replanning(tmp_path: Path):
    env = _setup_env(tmp_path)
    service: FileCenterService = env["service"]
    case = _generate(env, scan_id=1502)
    plan_id = case["plan_id"]
    source: Path = case["source"]
    keeper: Path = case["keeper"]

    service.freeze_plan(plan_id)
    _remove_other_regular_files(source)

    validated = service.validate_plan(plan_id)
    assert validated["status"] == "stale"
    status, item_state, reason, _metadata = _plan_item_state(env, plan_id)
    assert status == "stale"
    assert item_state == "stale"
    assert reason is not None and "RECURSIVE_PROTECT_LAST_FILE" in reason
    assert source.exists()
    assert keeper.exists(), "Validate failure must not choose a lower-score fallback candidate"
    with env["SessionLocal"]() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        assert session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == item.id)) is None
        assert session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id)) is None


def test_amendment_a_change_after_validate_before_execute_is_blocked_by_live_preflight(tmp_path: Path):
    env = _setup_env(tmp_path)
    service: FileCenterService = env["service"]
    case = _generate(env, scan_id=1503)
    plan_id = case["plan_id"]
    source: Path = case["source"]
    keeper: Path = case["keeper"]

    service.freeze_plan(plan_id)
    assert service.validate_plan(plan_id)["status"] == "ready"

    _remove_other_regular_files(source)
    _execute_with_worker(env, plan_id, worker_id="gate6b-amendment-a-stale-execute")

    status, item_state, reason, _metadata = _plan_item_state(env, plan_id)
    assert status == "stale"
    assert item_state == "failed"
    assert reason is not None and "RECURSIVE_PROTECT_LAST_FILE" in reason
    assert source.exists(), "live Execute preflight must veto before filesystem mutation"
    assert keeper.exists(), "Execute veto must not replan to a lower-score candidate"

    with env["SessionLocal"]() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        qentry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == item.id))
        # Phase 1 intentionally persists a Quarantine intent before the final live
        # preflight. A veto must retire it as abandoned, never as an active move.
        assert qentry is not None
        assert qentry.state == "abandoned"
        assert qentry.last_error is not None and "RECURSIVE_PROTECT_LAST_FILE" in qentry.last_error
        assert qentry.quarantine_path
        assert not Path(qentry.quarantine_path).exists()
        assert session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id)) is None


def test_amendment_a_symlinked_protected_ancestry_fails_closed_before_freeze_persistence(tmp_path: Path):
    env = _setup_env(tmp_path)
    service: FileCenterService = env["service"]
    case = _generate(env, scan_id=1504)
    plan_id = case["plan_id"]
    source: Path = case["source"]
    protected = source.parent
    moved = protected.with_name(protected.name + "-real")

    protected.rename(moved)
    protected.symlink_to(moved, target_is_directory=True)
    assert source.exists(), "lexical source remains reachable only through the inserted symlink"

    with pytest.raises((StateConflictError, ValueError), match="RECURSIVE_PROTECTION|recursive|symlink|unstable"):
        service.freeze_plan(plan_id)

    status, item_state, _reason, metadata = _plan_item_state(env, plan_id)
    assert status == "draft"
    assert item_state == "planned"
    assert "frozen_recursive_protection" not in metadata
    with env["SessionLocal"]() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        assert session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == item.id)) is None
        assert session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id)) is None
