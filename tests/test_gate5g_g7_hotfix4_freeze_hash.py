import hashlib
import os
from pathlib import Path
import stat
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.exceptions import StateConflictError
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, WorkJob
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler
import app.service as service_module


def _setup_service(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir = data_dir / ".nas-file-center-trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"

    settings = Settings(
        config_dir=config_dir,
        database_path=db_path,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=trash_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    app = create_app(settings)
    service: FileCenterService = app.state.service
    return service, settings, data_dir, trash_dir


def test_red_root_regression_generic_quarantine_freeze_captures_sha256(tmp_path):
    """
    TEST 1 — root regression
    Generic regular-file quarantine:
    operation="quarantine", keep_path=None, expected_hash=None
    Freeze must result in expected_hash == SHA256(actual source bytes).
    On untouched baseline 958c5d0 this test MUST FAIL.
    """
    service, settings, data_dir, trash_dir = _setup_service(tmp_path)
    file_path = data_dir / "sample.txt"
    payload = b"GENERIC_QUARANTINE_TEST_PAYLOAD_12345"
    file_path.write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest()

    plan = service.create_plan(
        name="test-generic-quarantine",
        kind="cleanup",
        items=[
            {
                "operation": "quarantine",
                "source": str(file_path),
            }
        ],
    )
    assert plan.status == "draft"

    with service.SessionLocal() as session:
        item = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)
        ).one()
        assert item.expected_hash is None
        assert item.operation == "quarantine"
        assert item.keep_path is None

    # Freeze the plan
    frozen_plan = service.freeze_plan(plan.id)
    assert frozen_plan.status == "frozen"

    with service.SessionLocal() as session:
        item = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)
        ).one()
        # This MUST assert that expected_hash was captured as expected_sha
        assert item.expected_hash == expected_sha


def test_freeze_mutation_during_hashing_fails_closed(tmp_path, monkeypatch):
    """
    TEST 2 — mutation during hashing
    Arrange for source identity/stability facts to differ across hash.
    Freeze MUST fail closed, plan MUST remain draft, no partial hash persisted.
    """
    service, settings, data_dir, trash_dir = _setup_service(tmp_path)
    file_path = data_dir / "mutate_target.txt"
    file_path.write_bytes(b"INITIAL_CONTENT")

    plan = service.create_plan(
        name="test-mutate-during-hash",
        kind="cleanup",
        items=[{"operation": "quarantine", "source": str(file_path)}],
    )

    # Simulate file mutation when hash helper is invoked:
    # Modify the file during safe_quarantine_hash execution
    orig_hash_func = service_module.safe_quarantine_hash

    def mutating_hash(p, *args, **kwargs):
        # Mutate the file on disk during hashing
        with open(p, "ab") as f:
            f.write(b"_APPENDED_MUTATION")
        return orig_hash_func(p, *args, **kwargs)

    monkeypatch.setattr(service_module, "safe_quarantine_hash", mutating_hash)

    with pytest.raises((StateConflictError, ValueError)):
        service.freeze_plan(plan.id)

    # Verify plan remains draft and expected_hash is not set
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "draft"
        it = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)
        ).one()
        assert it.expected_hash is None


def test_freeze_hash_io_failure_fails_closed(tmp_path, monkeypatch):
    """
    TEST 3 — hash / I/O failure
    Cause the required SHA helper or read path to raise.
    Freeze MUST fail closed, plan.status == 'draft', no partial SHA persisted.
    """
    service, settings, data_dir, trash_dir = _setup_service(tmp_path)
    file_path = data_dir / "io_fail_target.txt"
    file_path.write_bytes(b"IO_FAIL_PAYLOAD")

    plan = service.create_plan(
        name="test-io-fail",
        kind="cleanup",
        items=[{"operation": "quarantine", "source": str(file_path)}],
    )

    def failing_hash(p, *args, **kwargs):
        raise OSError("Simulated disk I/O failure during quarantine hashing")

    monkeypatch.setattr(service_module, "safe_quarantine_hash", failing_hash)

    with pytest.raises((StateConflictError, ValueError)):
        service.freeze_plan(plan.id)

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "draft"
        it = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)
        ).one()
        assert it.expected_hash is None


def test_freeze_pre_existing_hash_preserved(tmp_path):
    """
    TEST 4 — pre-existing hash preservation
    Start with non-null expected_hash. Freeze must not overwrite it.
    """
    service, settings, data_dir, trash_dir = _setup_service(tmp_path)
    file_path = data_dir / "pre_existing.txt"
    file_path.write_bytes(b"CONTENT_A")

    PRE_EXISTING_HASH = "pre_existing_sha256_hash_value_12345"

    plan = service.create_plan(
        name="test-pre-existing-hash",
        kind="cleanup",
        items=[
            {
                "operation": "quarantine",
                "source": str(file_path),
                "expected_hash": PRE_EXISTING_HASH,
            }
        ],
    )

    frozen_plan = service.freeze_plan(plan.id)
    assert frozen_plan.status == "frozen"

    with service.SessionLocal() as session:
        it = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)
        ).one()
        assert it.expected_hash == PRE_EXISTING_HASH


def test_freeze_non_regular_quarantine_source_preserves_behavior(tmp_path):
    """
    TEST 5 — non-regular compatibility
    A non-regular quarantine source (e.g. directory) must not gain new Hotfix4
    hashing semantics. Preserve existing behavior.
    """
    service, settings, data_dir, trash_dir = _setup_service(tmp_path)
    dir_path = data_dir / "some_dir"
    dir_path.mkdir()

    plan = service.create_plan(
        name="test-dir-quarantine",
        kind="cleanup",
        items=[
            {
                "operation": "quarantine",
                "source": str(dir_path),
            }
        ],
    )

    frozen_plan = service.freeze_plan(plan.id)
    assert frozen_plan.status == "frozen"

    with service.SessionLocal() as session:
        it = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)
        ).one()
        # Directory must not be hashed
        assert it.expected_hash is None


def test_freeze_hash_propagates_to_quarantine_entry_content_hash(tmp_path, monkeypatch):
    """
    TEST 6 — cross-layer propagation
    Prove that a generic quarantine hash captured at Freeze propagates through
    the existing execution preparation layer into QuarantineEntry.content_hash
    and enables successful candidate qualification under COMPAT_TRANSACTIONAL.
    """
    from app.quarantine.capability import MutationCapability
    service, settings, data_dir, trash_dir = _setup_service(tmp_path)
    file_path = data_dir / "propagate_target.txt"
    payload = b"PROPAGATION_TEST_PAYLOAD"
    file_path.write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    plan = service.create_plan(
        name="test-propagation",
        kind="cleanup",
        items=[{"operation": "quarantine", "source": str(file_path)}],
    )

    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)
    res = service.enqueue_plan_execution(plan.id, user_id=1)
    work_job_id = res["work_job_id"]

    from app.models import TaskLock, utcnow

    worker_id = "test-worker-1"
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        job = session.get(WorkJob, work_job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    ctx = JobContext(service.engine, service.SessionLocal, work_job_id, worker_id=worker_id)
    handler = BatchPlanExecuteHandler()
    handler.run(job, ctx, settings)

    with service.SessionLocal() as session:
        q_entry = session.scalars(
            select(QuarantineEntry).where(QuarantineEntry.task_id == work_job_id)
        ).first()
        assert q_entry is not None
        assert q_entry.state == "active"
        assert q_entry.tx_phase == "active"
        assert q_entry.content_hash == expected_sha
