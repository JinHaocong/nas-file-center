from __future__ import annotations

import json
from pathlib import Path
import pytest
from sqlalchemy import select
from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    TaskLock,
    WorkJob,
    utcnow,
)
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
    svc = FileCenterService(settings)
    return svc, settings, data_dir, trash_dir


def test_undo_of_restore_generates_quarantine_and_executes_to_new_entry(tmp_path: Path):
    svc, settings, data_dir, trash_dir = _setup_service(tmp_path)
    handler = get_handler("batch-plan-execute")
    _acquire_lease(svc, "test-worker-1")

    src = data_dir / "doc.txt"
    src.write_text("important document", encoding="utf-8")

    # 1. Quarantine doc.txt
    p1 = svc.create_plan(
        name="Plan 1 Quarantine",
        kind="organize",
        items=[{"operation": "quarantine", "source": str(src)}],
    )
    svc.freeze_plan(p1.id)
    svc.validate_plan(p1.id)

    now = utcnow()
    with svc.SessionLocal() as session:
        j1 = WorkJob(id=201, kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": p1.id}), started_at=now, created_at=now)
        session.add(j1)
        session.commit()
        ctx = JobContext(svc.engine, svc.SessionLocal, j1.id, worker_id="test-worker-1")
        handler.run(j1, ctx, settings)
        j1.status = "completed"
        j1.completed_at = utcnow()
        session.commit()

    with svc.SessionLocal() as session:
        q1 = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src)))
        assert q1 is not None
        assert q1.state == "active"
        q1_id = q1.id

    # 2. Restore doc.txt via Undo Plan 1
    undo1_info = svc.create_undo_plan(p1.id)
    undo1_id = undo1_info["id"]
    svc.freeze_plan(undo1_id)
    svc.validate_plan(undo1_id)

    with svc.SessionLocal() as session:
        j2 = WorkJob(id=202, kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": undo1_id}), started_at=utcnow(), created_at=utcnow())
        session.add(j2)
        session.commit()
        ctx = JobContext(svc.engine, svc.SessionLocal, j2.id, worker_id="test-worker-1")
        handler.run(j2, ctx, settings)
        j2.status = "completed"
        j2.completed_at = utcnow()
        session.commit()

    assert src.exists()
    with svc.SessionLocal() as session:
        q1_refreshed = session.get(QuarantineEntry, q1_id)
        assert q1_refreshed.state == "restored"

    # 3. Create Undo Plan of the Restore (Undo of Undo Plan 1)
    undo2_info = svc.create_undo_plan(undo1_id)
    undo2_id = undo2_info["id"]

    # Verify Undo Plan structure
    with svc.SessionLocal() as session:
        undo2_plan = session.get(BatchPlan, undo2_id)
        plan_meta = json.loads(undo2_plan.metadata_json or "{}")
        assert plan_meta.get("is_undo") is True
        assert plan_meta.get("undo_of_plan_id") == undo1_id
        assert len(plan_meta.get("source_journal_ids", [])) == 1

        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == undo2_id)))
        assert len(items) == 1
        item = items[0]

        # Inverse of restore is quarantine!
        assert item.operation == "quarantine"
        assert item.source_path == str(src)
        assert item.target_path is None or item.target_path == ""
        item_meta = json.loads(item.metadata_json or "{}")
        assert item_meta.get("undo", {}).get("inverse_of_restore") is True

    # 4. Execute Undo Plan 2 (Quarantine the restored file)
    svc.freeze_plan(undo2_id)
    svc.validate_plan(undo2_id)

    with svc.SessionLocal() as session:
        j3 = WorkJob(id=203, kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": undo2_id}), started_at=utcnow(), created_at=utcnow())
        session.add(j3)
        session.commit()
        ctx = JobContext(svc.engine, svc.SessionLocal, j3.id, worker_id="test-worker-1")
        handler.run(j3, ctx, settings)
        j3.status = "completed"
        j3.completed_at = utcnow()
        session.commit()

    assert not src.exists()

    # 5. Verify QuarantineEntries:
    # - The OLD entry (q1) must STILL be in state "restored"! NEVER reactivated!
    # - A NEW entry (q2) must be created with state "active"!
    with svc.SessionLocal() as session:
        q1_final = session.get(QuarantineEntry, q1_id)
        assert q1_final.state == "restored", "Old quarantine entry must NOT be reactivated"

        all_q = list(session.scalars(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src)).order_by(QuarantineEntry.id)))
        assert len(all_q) == 2, "A new QuarantineEntry must have been created"
        q2 = all_q[1]
        assert q2.id != q1_id
        assert q2.state == "active"
        assert Path(q2.quarantine_path).exists()


def test_undo_rejects_unsupported_operation(tmp_path: Path):
    svc, settings, data_dir, _ = _setup_service(tmp_path)
    now = utcnow()

    plan = svc.create_plan(
        name="Unsupported Op Plan",
        kind="organize",
        items=[{"operation": "touch", "source": str(data_dir)}],
    )

    with svc.SessionLocal() as session:
        db_plan = session.get(BatchPlan, plan.id)
        assert db_plan is not None
        db_plan.status = "completed"
        session.add(OperationJournal(
            operation="unknown_alien_op",
            sequence=1,
            plan_id=plan.id,
            plan_item_id=1,
            task_id=None,
            user_id=None,
            before_json="{}",
            after_json="{}",
            metadata_before_json="{}",
            metadata_after_json="{}",
            created_at=now,
        ))
        session.commit()

    with pytest.raises(ValueError) as exc:
        svc.create_undo_plan(plan.id)
    assert "unsupported operation" in str(exc.value).lower()
