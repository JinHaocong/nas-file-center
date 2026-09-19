from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.exceptions import StateConflictError
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.planning.dedupe_engine import directory_ancestors_to_scan_root
from app.planning.recursive_protection import RecursiveProtectionSnapshot
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler


RECURSIVE_MODE = "recursive_directory_balanced_by_bytes"


def _setup_service(tmp_path: Path):
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    quarantine_dir = data_dir / ".nas-file-center-trash"
    quarantine_dir.mkdir()
    config_dir.mkdir()

    settings = Settings(
        config_dir=config_dir,
        database_path=config_dir / "app.db",
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    return service, settings, data_dir, quarantine_dir


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


def _recursive_authority(source: Path, root: Path, *, token: str) -> dict:
    return {
        "schema_version": 1,
        "selection_mode": RECURSIVE_MODE,
        "scan_job_id": 9001,
        "scan_root_index": 0,
        "scan_root_path": str(root),
        "source_path": str(source),
        "protected_ancestors": list(directory_ancestors_to_scan_root(str(source), str(root))),
        "group_provenance_id": f"execute-{token}",
        "group_decision_fingerprint": "a" * 64,
        "preview_source_snapshot_digest": "b" * 64,
        "preview_db_lineage_digest": "c" * 64,
    }


def _create_ready_recursive_plan(
    service: FileCenterService,
    settings: Settings,
    root: Path,
    source: Path,
    *,
    token: str,
) -> int:
    plan = service.create_plan(
        name=f"recursive execute {token}",
        kind="dedupe",
        items=[{"source": str(source), "operation": "quarantine"}],
        metadata={"selection_mode": RECURSIVE_MODE},
    )
    with service.SessionLocal() as session:
        row = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        assert row is not None
        row.metadata_json = json.dumps(
            {
                "protected_dir": str(source.parent),
                "recursive_protection": _recursive_authority(source, root, token=token),
            },
            ensure_ascii=False,
        )
        session.commit()

    service.freeze_plan(plan.id)
    detail = service.validate_plan(plan.id)
    assert detail["status"] == "ready"
    return int(plan.id)


def _enqueue_and_run_worker(
    service: FileCenterService,
    settings: Settings,
    plan_id: int,
    *,
    worker_id: str,
) -> int:
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
        handler.run(job, context, settings)
    return job_id


def _item_state(service: FileCenterService, plan_id: int) -> tuple[str, str, str | None]:
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        row = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert row is not None
        return plan.status, row.state, row.reason


def test_worker_recursive_preflight_blocks_count_one_after_validate_before_execute(tmp_path: Path):
    service, settings, root, _ = _setup_service(tmp_path)
    protected = root / "set"
    protected.mkdir()
    source = protected / "delete.bin"
    sibling = protected / "keep.bin"
    source.write_bytes(b"duplicate")
    sibling.write_bytes(b"survivor")

    plan_id = _create_ready_recursive_plan(service, settings, root, source, token="count-one")

    # Validate saw two real regular files. External/NFC state then changes to one.
    sibling.unlink()
    assert source.exists()

    _enqueue_and_run_worker(service, settings, plan_id, worker_id="gate6b-count-one")

    plan_status, item_state, reason = _item_state(service, plan_id)
    assert source.exists(), "live preflight must block before Quarantine filesystem mutation"
    assert item_state == "failed"
    assert reason is not None and "RECURSIVE_PROTECT_LAST_FILE" in reason
    assert plan_status == "stale"


def test_worker_recursive_preflight_count_two_allows_one_quarantine(tmp_path: Path):
    service, settings, root, _ = _setup_service(tmp_path)
    protected = root / "set"
    protected.mkdir()
    source = protected / "delete.bin"
    sibling = protected / "keep.bin"
    source.write_bytes(b"duplicate")
    sibling.write_bytes(b"survivor")

    plan_id = _create_ready_recursive_plan(service, settings, root, source, token="count-two")
    _enqueue_and_run_worker(service, settings, plan_id, worker_id="gate6b-count-two")

    assert not source.exists()
    assert sibling.exists()
    with service.SessionLocal() as session:
        row = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert row is not None and row.state == "completed"
        qentry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == row.id))
        assert qentry is not None and qentry.state == "active"
        assert Path(qentry.quarantine_path).exists()


def test_two_recursive_plans_share_ancestor_first_executes_second_blocks_on_live_one(tmp_path: Path):
    service, settings, root, _ = _setup_service(tmp_path)
    protected = root / "set"
    protected.mkdir()
    source_a = protected / "a.bin"
    source_b = protected / "b.bin"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")

    # Both independent frozen plans are individually safe against the same initial live count=2.
    plan_a = _create_ready_recursive_plan(service, settings, root, source_a, token="plan-a")
    plan_b = _create_ready_recursive_plan(service, settings, root, source_b, token="plan-b")

    _enqueue_and_run_worker(service, settings, plan_a, worker_id="gate6b-shared-a")
    assert not source_a.exists()
    assert source_b.exists()

    _enqueue_and_run_worker(service, settings, plan_b, worker_id="gate6b-shared-b")

    assert source_b.exists(), "second plan must observe the first mutation through the live filesystem count"
    plan_status, item_state, reason = _item_state(service, plan_b)
    assert plan_status == "stale"
    assert item_state == "failed"
    assert reason is not None and "RECURSIVE_PROTECT_LAST_FILE" in reason


def test_root_direct_quarantine_does_not_count_reserved_quarantine_as_survivor(tmp_path: Path):
    service, settings, root, quarantine_root = _setup_service(tmp_path)
    source_a = root / "a.bin"
    source_b = root / "b.bin"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")

    # A root-direct source has exactly one protected ancestor: the Scan Root.
    # Both plans validate against the initial source-scope count=2.
    plan_a = _create_ready_recursive_plan(service, settings, root, source_a, token="root-direct-a")
    plan_b = _create_ready_recursive_plan(service, settings, root, source_b, token="root-direct-b")

    _enqueue_and_run_worker(service, settings, plan_a, worker_id="gate6b-root-direct-a")
    assert not source_a.exists()
    assert source_b.exists()
    assert any(path.is_file() for path in quarantine_root.rglob("*"))

    _enqueue_and_run_worker(service, settings, plan_b, worker_id="gate6b-root-direct-b")

    assert source_b.exists(), (
        "reserved Quarantine storage must not count as a surviving regular file "
        "for Recursive Last-File Protection"
    )
    plan_status, item_state, reason = _item_state(service, plan_b)
    assert plan_status == "stale"
    assert item_state == "failed"
    assert reason is not None and "RECURSIVE_PROTECT_LAST_FILE" in reason


def test_worker_recursive_preflight_unstable_read_blocks_before_execute_item(tmp_path: Path, monkeypatch):
    service, settings, root, _ = _setup_service(tmp_path)
    protected = root / "set"
    protected.mkdir()
    source = protected / "delete.bin"
    sibling = protected / "keep.bin"
    source.write_bytes(b"duplicate")
    sibling.write_bytes(b"survivor")

    plan_id = _create_ready_recursive_plan(service, settings, root, source, token="unstable")

    import app.planning.recursive_protection as recursive_protection
    import app.tasks.handlers_base as handlers_base

    monkeypatch.setattr(
        recursive_protection,
        "snapshot_recursive_regular_files",
        lambda _path, **_kwargs: RecursiveProtectionSnapshot(
            count=0,
            stable=False,
            device=None,
            inode=None,
            tree_identity_digest=None,
        ),
    )
    execute_calls: list[str] = []
    original_execute = handlers_base.execute_item

    def tracked_execute(*args, **kwargs):
        execute_calls.append("execute")
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(handlers_base, "execute_item", tracked_execute)

    _enqueue_and_run_worker(service, settings, plan_id, worker_id="gate6b-unstable")

    assert execute_calls == [], "untrustworthy recursive scope must block before execute_item()"
    assert source.exists()
    _, item_state, reason = _item_state(service, plan_id)
    assert item_state == "failed"
    assert reason is not None and "RECURSIVE_PROTECTION_UNSTABLE" in reason


def test_worker_recursive_preflight_order_is_after_final_freshness_and_before_execute_item(tmp_path: Path, monkeypatch):
    service, settings, root, _ = _setup_service(tmp_path)
    protected = root / "set"
    protected.mkdir()
    source = protected / "delete.bin"
    sibling = protected / "keep.bin"
    source.write_bytes(b"duplicate")
    sibling.write_bytes(b"survivor")

    plan_id = _create_ready_recursive_plan(service, settings, root, source, token="ordering")

    import app.planning.recursive_protection as recursive_protection
    import app.tasks.handlers_base as handlers_base

    events: list[str] = []
    original_verify = handlers_base._verify_plan_item_and_keep_freshness
    original_snapshot = recursive_protection.snapshot_recursive_regular_files
    original_execute = handlers_base.execute_item

    def tracked_verify(*args, **kwargs):
        events.append("freshness")
        return original_verify(*args, **kwargs)

    def tracked_snapshot(path, **kwargs):
        events.append("live_preflight")
        return original_snapshot(path, **kwargs)

    def tracked_execute(*args, **kwargs):
        events.append("execute")
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(handlers_base, "_verify_plan_item_and_keep_freshness", tracked_verify)
    monkeypatch.setattr(recursive_protection, "snapshot_recursive_regular_files", tracked_snapshot)
    monkeypatch.setattr(handlers_base, "execute_item", tracked_execute)

    _enqueue_and_run_worker(service, settings, plan_id, worker_id="gate6b-ordering")

    freshness_indices = [i for i, event in enumerate(events) if event == "freshness"]
    live_indices = [i for i, event in enumerate(events) if event == "live_preflight"]
    execute_index = events.index("execute")
    assert len(freshness_indices) >= 2, events
    assert live_indices, events
    assert max(freshness_indices) < min(live_indices) < execute_index, events


def test_recursive_plan_cannot_bypass_worker_via_synchronous_execute_plan(tmp_path: Path):
    service, settings, root, _ = _setup_service(tmp_path)
    protected = root / "set"
    protected.mkdir()
    source = protected / "delete.bin"
    sibling = protected / "keep.bin"
    source.write_bytes(b"duplicate")
    sibling.write_bytes(b"survivor")

    plan_id = _create_ready_recursive_plan(service, settings, root, source, token="direct-bypass")

    with pytest.raises((StateConflictError, ValueError), match="recursive|Worker|preflight"):
        service.execute_plan(plan_id)

    assert source.exists()
    _, item_state, _ = _item_state(service, plan_id)
    assert item_state == "validated"


def test_nonrecursive_synchronous_execute_plan_remains_compatible(tmp_path: Path):
    service, _, root, _ = _setup_service(tmp_path)
    source = root / "legacy.bin"
    source.write_bytes(b"legacy")
    plan = service.create_plan(
        name="legacy direct execute",
        kind="dedupe",
        items=[{"source": str(source), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    result = service.execute_plan(plan.id)

    assert result["status"] == "completed"
    assert not source.exists()

def test_worker_recursive_preflight_keeps_final_legacy_last_file_fence(tmp_path: Path, monkeypatch):
    service, settings, root, _ = _setup_service(tmp_path)
    protected = root / "set"
    protected.mkdir()
    source = protected / "delete.bin"
    sibling = protected / "keep.bin"
    source.write_bytes(b"duplicate")
    sibling.write_bytes(b"survivor")

    plan_id = _create_ready_recursive_plan(service, settings, root, source, token="final-last-file-fence")

    import app.execution.executor as executor

    recount_calls: list[str] = []
    real_count = executor._count_regular_files

    def tracked_count(path):
        recount_calls.append(str(path))
        return real_count(path)

    monkeypatch.setattr(executor, "_count_regular_files", tracked_count)

    _enqueue_and_run_worker(service, settings, plan_id, worker_id="gate6b-final-last-file-fence")

    assert recount_calls == [str(protected)]
    assert not source.exists()
    assert sibling.exists()


def test_worker_duplicate_boundary_defers_sha256_until_execute_fence(tmp_path: Path, monkeypatch):
    service, settings, root, _ = _setup_service(tmp_path)
    keep = root / "keep.bin"
    source = root / "delete.bin"
    payload = b"same-payload" * 1000
    keep.write_bytes(payload)
    source.write_bytes(payload)

    plan = service.create_plan(
        name="dedupe hash deferral",
        kind="dedupe",
        items=[
            {
                "source": str(source),
                "keep": str(keep),
                "operation": "quarantine",
            }
        ],
    )
    service.freeze_plan(plan.id)
    detail = service.validate_plan(plan.id)
    assert detail["status"] == "ready"

    import app.tasks.handlers_base as handlers_base

    original_verify = handlers_base._verify_plan_item_and_keep_freshness
    worker_hash_modes: list[bool] = []

    def tracked_verify(*args, **kwargs):
        worker_hash_modes.append(bool(kwargs.get("check_hash", True)))
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(handlers_base, "_verify_plan_item_and_keep_freshness", tracked_verify)

    _enqueue_and_run_worker(service, settings, int(plan.id), worker_id="dedupe-hash-deferral")

    assert worker_hash_modes.count(False) >= 2, worker_hash_modes
    assert True not in worker_hash_modes, worker_hash_modes
    assert not source.exists()
    assert keep.exists()
