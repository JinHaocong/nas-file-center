import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import create_app
from app.models import (
    Base,
    IndexRoot,
    IndexedPath,
    BatchPlan,
    BatchPlanItem,
    WorkJob,
    TaskLock,
    User,
    OperationJournal,
    utcnow,
)
from app.auth.password import hash_password
from app.config import Settings
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler


def _acquire_lease(service: FileCenterService, worker_id: str):
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


@pytest.fixture
def lifecycle_test_env(tmp_path):
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
        allowed_roots_raw=f"{data_dir},{quarantine_dir}",
        quarantine_root=quarantine_dir,
        protect_last_file=True,
        allow_mutation=True,
        allow_delete=True,
    )

    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"

    with service.SessionLocal() as session:
        reg_user = User(
            username="adminuser",
            password_hash=hash_password("AdminPass123!"),
            is_active=True,
            role="admin",
        )
        session.add(reg_user)
        session.commit()

    login_resp = client.post(
        "/api/auth/login",
        json={"username": "adminuser", "password": "AdminPass123!"},
    )
    assert login_resp.status_code == 200

    return {
        "service": service,
        "settings": settings,
        "client": client,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def test_suffix_transform_freeze_validate_execute_undo_lifecycle(lifecycle_test_env):
    service = lifecycle_test_env["service"]
    settings = lifecycle_test_env["settings"]
    client = lifecycle_test_env["client"]
    data_dir = lifecycle_test_env["data_dir"]

    root_dir = data_dir / "root1"
    root_dir.mkdir()

    # Create vacating occupant pair:
    # file "a" -> "a.txt"
    # file "a.txt" -> "a.txt.txt"
    file_a = root_dir / "a"
    file_a.write_text("content of original a")
    file_atxt = root_dir / "a.txt"
    file_atxt.write_text("content of original a.txt")

    st_a = file_a.stat()
    st_atxt = file_atxt.stat()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root_dir))
        session.add(r)
        session.commit()

        p1 = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(file_a),
            relative_path="a",
            basename=file_a.name,
            stem=file_a.stem,
            suffix=file_a.suffix,
            size=st_a.st_size,
            mtime_ns=st_a.st_mtime_ns,
            device=st_a.st_dev,
            inode=st_a.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p2 = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(file_atxt),
            relative_path="a.txt",
            basename=file_atxt.name,
            stem=file_atxt.stem,
            suffix=file_atxt.suffix,
            size=st_atxt.st_size,
            mtime_ns=st_atxt.st_mtime_ns,
            device=st_atxt.st_dev,
            inode=st_atxt.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add_all([p1, p2])
        session.commit()

    # 1. Preview
    prev_resp = client.post("/api/batch-utilities/preview", json={
        "action": {
            "type": "suffix_transform",
            "root_ids": [1],
            "mode": "append",
            "suffix": "txt",
        }
    })
    assert prev_resp.status_code == 200
    preview_data = prev_resp.json()
    assert preview_data["utility_action"] == "suffix_transform"
    assert preview_data["planned_operations_count"] == 2
    assert preview_data["blocking_conflict_count"] == 0
    digest = preview_data["preview_digest"]

    # 2. Generate Draft
    gen_resp = client.post("/api/batch-utilities/generate-plan", json={
        "action": {
            "type": "suffix_transform",
            "root_ids": [1],
            "mode": "append",
            "suffix": "txt",
        },
        "expected_preview_digest": digest,
    })
    assert gen_resp.status_code == 201
    plan_id = gen_resp.json()["plan_id"]

    # 3. Assert initial identity placeholders
    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).order_by(BatchPlanItem.sequence.asc()).all()
        assert len(items) == 2

        # Item 1 must be a.txt -> a.txt.txt (vacating occupant executes first!)
        assert items[0].source_path == str(file_atxt)
        assert items[0].target_path == str(root_dir / "a.txt.txt")
        assert items[0].sequence == 1
        assert items[0].expected_device == 0
        assert items[0].expected_inode == 0
        assert items[0].expected_mtime_ns == 0

        # Item 2 must be a -> a.txt
        assert items[1].source_path == str(file_a)
        assert items[1].target_path == str(file_atxt)
        assert items[1].sequence == 2
        assert items[1].expected_device == 0
        assert items[1].expected_inode == 0
        assert items[1].expected_mtime_ns == 0

    # 4. Freeze Plan -> captures real physical snapshot
    freeze_res = service.freeze_plan(plan_id)
    assert freeze_res.status == "frozen"

    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).order_by(BatchPlanItem.sequence.asc()).all()
        assert items[0].expected_mtime_ns > 0
        assert items[0].expected_device > 0
        assert items[0].expected_inode > 0
        assert items[1].expected_mtime_ns > 0
        assert items[1].expected_device > 0
        assert items[1].expected_inode > 0

    # 5. Validate Plan -> ready
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "ready"

    # 6. Execute Plan
    enqueue_res = client.post(f"/api/plans/{plan_id}/execute")
    assert enqueue_res.status_code == 200
    job_id = enqueue_res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    assert handler is not None

    _acquire_lease(service, "worker-1")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-1")
        handler.run(job, context, settings)
        job.status = "completed"
        job.completed_at = utcnow()
        session.commit()

    # 7. Check filesystem post-execution
    # Original 'a' is now 'a.txt' with content 'content of original a'
    # Original 'a.txt' is now 'a.txt.txt' with content 'content of original a.txt'
    file_atxttxt = root_dir / "a.txt.txt"
    assert not file_a.exists()
    assert file_atxt.exists()
    assert file_atxttxt.exists()

    assert file_atxt.read_text() == "content of original a"
    assert file_atxttxt.read_text() == "content of original a.txt"

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan.status == "completed"
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).all()
        assert all(it.state == "completed" for it in items)

        # Journal entries recorded
        journals = session.query(OperationJournal).filter_by(plan_id=plan.id).all()
        assert len(journals) == 2
        assert all(j.operation == "rename" for j in journals)

    # 8. Undo Plan creation and restoration
    undo_info = service.create_undo_plan(plan_id)
    undo_plan_id = undo_info["id"]

    # Freeze & Validate Undo Plan
    service.freeze_plan(undo_plan_id)
    undo_val = service.validate_plan(undo_plan_id)
    assert undo_val["status"] == "ready"

    # Execute Undo Plan
    enqueue_undo = client.post(f"/api/plans/{undo_plan_id}/execute")
    assert enqueue_undo.status_code == 200
    undo_job_id = enqueue_undo.json()["work_job_id"]

    _acquire_lease(service, "worker-1")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, undo_job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-1")
        handler.run(job, context, settings)
        job.status = "completed"
        job.completed_at = utcnow()
        session.commit()

    # 9. Verify restored files
    assert file_a.exists()
    assert file_atxt.exists()
    assert not file_atxttxt.exists()

    assert file_a.read_text() == "content of original a"
    assert file_atxt.read_text() == "content of original a.txt"


def test_suffix_transform_worker_exdev_fail_closed(lifecycle_test_env):
    import errno
    from unittest.mock import patch

    service = lifecycle_test_env["service"]
    settings = lifecycle_test_env["settings"]
    client = lifecycle_test_env["client"]
    data_dir = lifecycle_test_env["data_dir"]

    root_dir = data_dir / "root_exdev"
    root_dir.mkdir()

    file_x = root_dir / "x.png"
    file_x.write_text("x content")
    st = file_x.stat()

    with service.SessionLocal() as session:
        r = IndexRoot(id=2, root=str(root_dir))
        session.add(r)
        session.commit()

        p = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(file_x),
            relative_path="x.png",
            basename=file_x.name,
            stem=file_x.stem,
            suffix=file_x.suffix,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(p)
        session.commit()

    prev_resp = client.post("/api/batch-utilities/preview", json={
        "action": {
            "type": "suffix_transform",
            "root_ids": [2],
            "mode": "change",
            "suffix": ".webp",
        }
    })
    digest = prev_resp.json()["preview_digest"]

    gen_resp = client.post("/api/batch-utilities/generate-plan", json={
        "action": {
            "type": "suffix_transform",
            "root_ids": [2],
            "mode": "change",
            "suffix": ".webp",
        },
        "expected_preview_digest": digest,
    })
    plan_id = gen_resp.json()["plan_id"]

    service.freeze_plan(plan_id)
    service.validate_plan(plan_id)

    enqueue_res = client.post(f"/api/plans/{plan_id}/execute")
    job_id = enqueue_res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "worker-1")

    # Simulate EXDEV during rename
    with patch("app.fs_ops.rename_noreplace", side_effect=OSError(errno.EXDEV, "Invalid cross-device link")):
        with service.SessionLocal() as session:
            job = session.get(WorkJob, job_id)
            job.status = "running"
            job.started_at = utcnow()
            session.commit()

            context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-1")
            handler.run(job, context, settings)
            job.status = "completed"
            job.completed_at = utcnow()
            session.commit()

    # Fail closed: original file must still exist and target must NOT exist
    assert file_x.exists()
    assert not (root_dir / "x.webp").exists()

    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item.state == "failed"
        assert "cross-device" in (item.reason or "").lower() or "exdev" in (item.reason or "").lower() or "error" in (item.reason or "").lower()
