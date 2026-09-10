import json
import os
from pathlib import Path
import pytest

from app.models import IndexRoot, User, BatchPlan, BatchPlanItem, OperationJournal
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password
from app.batch.plans import OperationItem
from app.execution.executor import execute_item


@pytest.fixture
def undo_test_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    db_path = config_dir / "app.db"
    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=db_path,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        protect_last_file=True,
        allow_mutation=True,
        allow_delete=True,
    )

    service = FileCenterService(settings)

    root_path = data_dir / "root1"
    root_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root_path))
        session.add(r)
        reg_user = User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        )
        session.add(reg_user)
        session.commit()

    return {
        "service": service,
        "settings": settings,
        "data_dir": data_dir,
        "root_path": root_path,
        "quarantine_dir": quarantine_dir,
    }


def test_undo_rmdir_empty_produces_mkdir_empty_in_shallowest_first_order(undo_test_env):
    service = undo_test_env["service"]
    root = undo_test_env["root_path"]

    scope = root / "scope"
    (scope / "a" / "b").mkdir(parents=True)

    action = {
        "type": "remove_empty_dirs",
        "scope_paths": [str(scope)],
    }

    preview = service.get_batch_utility_preview(action=service.parse_batch_utility_action(action) if hasattr(service, "parse_batch_utility_action") else None or
        __import__("app.batch_utilities.schema", fromlist=["RemoveEmptyDirsAction"]).RemoveEmptyDirsAction(**action))
    digest = preview["preview_digest"]

    plan_res = service.create_batch_utility_plan(
        action=__import__("app.batch_utilities.schema", fromlist=["RemoveEmptyDirsAction"]).RemoveEmptyDirsAction(**action),
        expected_preview_digest=digest,
    )
    plan_id = plan_res["id"]

    service.freeze_plan(plan_id)
    service.validate_plan(plan_id)

    # Execute plan via job handler
    job = service.enqueue_plan_execution(plan_id)
    from app.tasks.handlers import BatchPlanExecuteHandler
    from app.tasks.context import JobContext
    from app.models import TaskLock, WorkJob, utcnow

    def _acquire_lease(service, worker_id: str):
        with service.SessionLocal() as session:
            lock = session.get(TaskLock, 1)
            if not lock:
                lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
                session.add(lock)
            else:
                lock.locked = True
                lock.owner = worker_id
                lock.acquired_at = utcnow()
            session.commit()

    _acquire_lease(service, "worker-test")
    handler = BatchPlanExecuteHandler()
    with service.SessionLocal() as session:
        job_db = session.get(WorkJob, job["work_job_id"])
        job_db.status = "running"
        session.commit()
        ctx = JobContext(service.engine, service.SessionLocal, job_db.id, worker_id="worker-test")
        handler.run(job_db, ctx, undo_test_env["settings"])
        job_db.status = "completed"
        session.commit()

    # Assert directories were deleted
    assert not (scope / "a" / "b").exists()
    assert not (scope / "a").exists()
    assert scope.exists()

    # Verify journals were created
    with service.SessionLocal() as session:
        journals = session.query(OperationJournal).filter_by(plan_id=plan_id).order_by(OperationJournal.sequence).all()
        assert len(journals) == 2
        j1_b = json.loads(journals[0].before_json)
        j1_a = json.loads(journals[0].after_json)
        assert j1_b["path"] == str(scope / "a" / "b")
        assert j1_b["scope_root"] == str(scope.resolve())
        assert j1_a["removed"] is True

        j2_b = json.loads(journals[1].before_json)
        assert j2_b["path"] == str(scope / "a")
        assert j2_b["scope_root"] == str(scope.resolve())

    # Create Undo Plan
    undo_res = service.create_undo_plan(plan_id)
    undo_id = undo_res["id"]

    with service.SessionLocal() as session:
        undo_items = session.query(BatchPlanItem).filter_by(plan_id=undo_id).order_by(BatchPlanItem.sequence).all()
        assert len(undo_items) == 2

        # Shallowest-first: sequence 1 must create 'a', sequence 2 creates 'a/b'
        assert undo_items[0].sequence == 1
        assert undo_items[0].operation == "mkdir_empty"
        assert undo_items[0].source_path == str(scope.resolve())
        assert undo_items[0].target_path == str(scope / "a")
        assert undo_items[0].expected_device == 0
        assert undo_items[0].expected_inode == 0

        assert undo_items[1].sequence == 2
        assert undo_items[1].operation == "mkdir_empty"
        assert undo_items[1].source_path == str(scope.resolve())
        assert undo_items[1].target_path == str(scope / "a" / "b")

        meta0 = json.loads(undo_items[0].metadata_json)
        assert meta0["undo"]["structural_only"] is True

    # Now Freeze, Validate, and Execute the Undo plan!
    service.freeze_plan(undo_id)
    val_undo = service.validate_plan(undo_id)
    assert val_undo["status"] == "ready"

    job_undo = service.enqueue_plan_execution(undo_id)
    with service.SessionLocal() as session:
        job_undo_db = session.get(WorkJob, job_undo["work_job_id"])
        job_undo_db.status = "running"
        session.commit()
        ctx_undo = JobContext(service.engine, service.SessionLocal, job_undo_db.id, worker_id="worker-test")
        handler.run(job_undo_db, ctx_undo, undo_test_env["settings"])
        job_undo_db.status = "completed"
        session.commit()

    # Assert directories are restored!
    assert (scope / "a").is_dir()
    assert (scope / "a" / "b").is_dir()


def test_undo_mkdir_empty_inverts_to_rmdir_empty(undo_test_env):
    service = undo_test_env["service"]
    root = undo_test_env["root_path"]

    scope = root / "scope_mkdir"
    scope.mkdir()

    # Manually create and run a plan with mkdir_empty
    with service.SessionLocal() as session:
        plan = BatchPlan(name="plan-mkdir", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="mkdir_empty",
            source_path=str(scope),
            target_path=str(scope / "new_dir"),
            state="planned",
            metadata_json=json.dumps({"scope_root": str(scope)}),
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    service.freeze_plan(plan_id)
    service.validate_plan(plan_id)

    job = service.enqueue_plan_execution(plan_id)
    from app.tasks.handlers import BatchPlanExecuteHandler
    from app.tasks.context import JobContext
    from app.models import TaskLock, WorkJob, utcnow

    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner="worker-test", acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = "worker-test"
            lock.acquired_at = utcnow()
        session.commit()

    handler = BatchPlanExecuteHandler()
    with service.SessionLocal() as session:
        job_db = session.get(WorkJob, job["work_job_id"])
        job_db.status = "running"
        session.commit()
        ctx = JobContext(service.engine, service.SessionLocal, job_db.id, worker_id="worker-test")
        handler.run(job_db, ctx, undo_test_env["settings"])
        job_db.status = "completed"
        session.commit()

    assert (scope / "new_dir").is_dir()

    # Now create undo plan of the mkdir_empty plan
    undo_res = service.create_undo_plan(plan_id)
    undo_id = undo_res["id"]

    with service.SessionLocal() as session:
        undo_items = session.query(BatchPlanItem).filter_by(plan_id=undo_id).all()
        assert len(undo_items) == 1
        assert undo_items[0].operation == "rmdir_empty"
        assert undo_items[0].source_path == str(scope / "new_dir")
        assert undo_items[0].target_path is None

    # Freeze, validate, and execute undo-of-mkdir
    service.freeze_plan(undo_id)
    val_undo = service.validate_plan(undo_id)
    assert val_undo["status"] == "ready"

    job_undo = service.enqueue_plan_execution(undo_id)
    with service.SessionLocal() as session:
        job_undo_db = session.get(WorkJob, job_undo["work_job_id"])
        job_undo_db.status = "running"
        session.commit()
        ctx_undo = JobContext(service.engine, service.SessionLocal, job_undo_db.id, worker_id="worker-test")
        handler.run(job_undo_db, ctx_undo, undo_test_env["settings"])
        job_undo_db.status = "completed"
        session.commit()

    assert not (scope / "new_dir").exists()


def test_undo_mkdir_empty_validation_conflicts(undo_test_env):
    service = undo_test_env["service"]
    root = undo_test_env["root_path"]

    scope = root / "scope_conflicts"
    (scope / "child").mkdir(parents=True)

    action = {"type": "remove_empty_dirs", "scope_paths": [str(scope)]}
    preview = service.get_batch_utility_preview(action=__import__("app.batch_utilities.schema", fromlist=["RemoveEmptyDirsAction"]).RemoveEmptyDirsAction(**action))
    plan_res = service.create_batch_utility_plan(
        action=__import__("app.batch_utilities.schema", fromlist=["RemoveEmptyDirsAction"]).RemoveEmptyDirsAction(**action),
        expected_preview_digest=preview["preview_digest"],
    )
    plan_id = plan_res["id"]
    service.freeze_plan(plan_id)
    service.validate_plan(plan_id)

    job = service.enqueue_plan_execution(plan_id)
    from app.tasks.handlers import BatchPlanExecuteHandler
    from app.tasks.context import JobContext
    from app.models import TaskLock, WorkJob, utcnow
    from app.exceptions import StateConflictError

    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner="worker-test", acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = "worker-test"
            lock.acquired_at = utcnow()
        session.commit()

    handler = BatchPlanExecuteHandler()
    with service.SessionLocal() as session:
        job_db = session.get(WorkJob, job["work_job_id"])
        job_db.status = "running"
        session.commit()
        ctx = JobContext(service.engine, service.SessionLocal, job_db.id, worker_id="worker-test")
        handler.run(job_db, ctx, undo_test_env["settings"])
        job_db.status = "completed"
        session.commit()

    assert not (scope / "child").exists()

    # Create Undo plan
    undo_res = service.create_undo_plan(plan_id)
    undo_id = undo_res["id"]

    # Test 1: Cannot execute in Draft state
    with pytest.raises(StateConflictError):
        service.enqueue_plan_execution(undo_id)

    # Test 2: Target already exists as a file -> Validate fails
    (scope / "child").write_text("re-created as a file!")
    service.freeze_plan(undo_id)
    val = service.validate_plan(undo_id)
    assert val["status"] == "partial"
    assert val["items"][0]["state"] == "skipped"

    # Test 3: Target is a symlink -> Validate fails
    (scope / "child").unlink()
    outside = root / "outside"
    outside.mkdir()
    (scope / "child").symlink_to(outside)
    val = service.validate_plan(undo_id)
    assert val["status"] == "partial"
    assert val["items"][0]["state"] == "skipped"

