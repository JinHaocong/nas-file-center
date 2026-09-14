from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.tasks.handlers import _reconcile_executing_item


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    app = create_app(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=trash,
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
            allow_mutation=True,
            allow_delete=True,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client


def _active_entry(client: TestClient) -> int:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    original = data / "reconcile-restore.txt"
    payload = b"gate6a-restore-reconcile-audit"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / "pending-reconcile-restore.txt"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=0,
            content_hash=None,
            mtime_ns=0,
            device=0,
            inode=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()

        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"reconcile-restore.q-{entry.id}.txt"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.size = st.st_size
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.mtime_ns = st.st_mtime_ns
        entry.device = st.st_dev
        entry.inode = st.st_ino
        session.commit()
        return int(entry.id)


def _bulk_restore_plan(client: TestClient, entry_id: int, conflict_policy: str = "skip") -> int:
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": [entry_id], "conflict_policy": conflict_policy},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": conflict_policy,
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    service = client.app.state.service
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    return plan_id


def _prepare_worker(service, plan_id: int, worker_id: str) -> int:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan_id}),
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(job)
        session.commit()
        return int(job.id)


def _reconcile_twice(service, *, plan_id: int, item_id: int, job_id: int, worker_id: str) -> None:
    for _ in range(2):
        with service.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            item = session.get(BatchPlanItem, item_id)
            assert item is not None
            _reconcile_executing_item(
                session,
                item,
                plan_id,
                job_id,
                None,
                service.settings,
                utcnow(),
                worker_id=worker_id,
                pre_reconciled=True,
            )
            session.commit()


def test_bulk_restore_reconcile_restored_terminal_writes_exactly_one_bound_audit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id = _active_entry(client)
    plan_id = _bulk_restore_plan(client, entry_id, "rename")
    worker_id = "worker-gate6a-reconcile-restored"
    job_id = _prepare_worker(service, plan_id, worker_id)

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        item.state = "executing"
        entry.state = "restored"
        entry.tx_phase = "restored"
        entry.restored_at = utcnow()
        session.commit()
        item_id = int(item.id)
        frozen_target = item.target_path

    _reconcile_twice(
        service,
        plan_id=plan_id,
        item_id=item_id,
        job_id=job_id,
        worker_id=worker_id,
    )

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        assert item.state == "completed"
        audits = session.query(AuditEvent).filter_by(operation="restore").all()
        assert len(audits) == 1
        audit = audits[0]
        assert audit.result == "completed"
        details = json.loads(audit.details_json or "{}")
        assert details["plan_id"] == plan_id
        assert details["item_id"] == item_id
        assert details["task_id"] == job_id
        assert details["quarantine_entry_id"] == entry_id
        assert details["target"] == frozen_target
        assert details["conflict_policy"] == "rename"
        assert details["result_path"] == frozen_target
        assert "reconciled transactional restore after crash" in details["reason"]


def test_bulk_restore_reconcile_conflict_terminal_writes_exactly_one_bound_failure_audit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id = _active_entry(client)
    plan_id = _bulk_restore_plan(client, entry_id, "skip")
    worker_id = "worker-gate6a-reconcile-conflict"
    job_id = _prepare_worker(service, plan_id, worker_id)

    sentinel_error = "restore core committed conflict before worker phase-3"
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        item.state = "executing"
        entry.state = "conflict"
        entry.tx_phase = "conflict"
        entry.last_error = sentinel_error
        session.commit()
        item_id = int(item.id)
        frozen_target = item.target_path

    _reconcile_twice(
        service,
        plan_id=plan_id,
        item_id=item_id,
        job_id=job_id,
        worker_id=worker_id,
    )

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        assert item.state == "failed"
        audits = session.query(AuditEvent).filter_by(operation="restore").all()
        assert len(audits) == 1
        audit = audits[0]
        assert audit.result == "failed"
        details = json.loads(audit.details_json or "{}")
        assert details["plan_id"] == plan_id
        assert details["item_id"] == item_id
        assert details["task_id"] == job_id
        assert details["quarantine_entry_id"] == entry_id
        assert details["target"] == frozen_target
        assert details["conflict_policy"] == "skip"
        assert details["result_path"] is None
        assert sentinel_error in details["reason"]
