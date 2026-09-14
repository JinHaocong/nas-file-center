from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    QuarantineEntry,
    TaskEvent,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.tasks.recovery import acquire_worker_ownership, recover_interrupted_jobs
from app.worker import process_work_job


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


def _active_entry(client: TestClient) -> tuple[int, Path, Path, Path, bytes]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-pre-intent-worker-restart"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "pre-intent-purge.bin"),
            quarantine_path=str(trash / "pending-pre-intent-purge.bin"),
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
        captured_source = attempt / "captured_source"
        public_view = trash / f"pre-intent-purge.q-{entry.id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured_source)
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
        return int(entry.id), anchor, captured_source, public_view, payload


def _bulk_purge_plan(client: TestClient, entry_id: int) -> int:
    service = client.app.state.service
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "confirmation": "DELETE",
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    return plan_id


def test_worker_restart_retries_purge_item_that_crashed_before_irreversible_intent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, captured_source, public_view, payload = _active_entry(client)
    frozen_st = anchor.stat(follow_symlinks=False)
    plan_id = _bulk_purge_plan(client, entry_id)
    old_worker = "worker-old-pre-intent"
    new_worker = "worker-new-pre-intent"

    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = old_worker
        lock.acquired_at = utcnow()

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan_id}),
            checkpoint_json=json.dumps({"schema_version": 1}),
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(job)
        session.flush()
        job_id = int(job.id)

        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        item_id = int(item.id)
        item.state = "executing"
        metadata = json.loads(item.metadata_json or "{}")
        metadata["execution"] = {
            "phase": "intent",
            "task_id": job_id,
            "operation": "quarantine_purge",
            "source_stat": {},
            "metadata_before": {},
            "target_mtime_ns": None,
        }
        item.metadata_json = json.dumps(metadata, ensure_ascii=False)
        session.commit()

    # This is the exact B8 crash state: the plan item crossed Phase 1, but the
    # purge engine never committed its irreversible active -> purging intent.
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.active_attempt_generation == 1
    for path in (anchor, captured_source, public_view):
        assert path.read_bytes() == payload
        st = path.stat(follow_symlinks=False)
        assert (st.st_dev, st.st_ino, st.st_size) == (
            frozen_st.st_dev,
            frozen_st.st_ino,
            frozen_st.st_size,
        )
    assert not (
        Path(service.settings.quarantine_root) / ".tx" / f"entry-{entry_id}" / "attempt-2"
    ).exists()

    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock is not None
        lock.acquired_at = utcnow() - timedelta(seconds=31)
        session.commit()

    assert acquire_worker_ownership(service.engine, service.SessionLocal, new_worker) is True
    stats = recover_interrupted_jobs(service.engine, service.SessionLocal, worker_id=new_worker)
    assert stats["recovered_requeued"] == 1
    assert stats["failed_interrupted"] == 0

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None and job.status == "queued"
        item = session.get(BatchPlanItem, item_id)
        assert item is not None and item.state == "executing"
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert (entry.state, entry.tx_phase, entry.active_attempt_generation) == ("active", "active", 1)
        recovery_events = list(
            session.scalars(
                select(TaskEvent).where(
                    TaskEvent.job_id == job_id,
                    TaskEvent.event_type == "recovered_after_worker_restart",
                )
            )
        )
        assert len(recovery_events) == 1

    # Recovery must not mutate payload before the replacement Worker actually
    # resumes the job under its own live lease.
    for path in (anchor, captured_source, public_view):
        assert path.read_bytes() == payload

    assert process_work_job(
        service.settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=new_worker,
    ) is True

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None

        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        assert item.state == "completed"
        assert item.reason == "purged"

        plan = session.get(BatchPlan, plan_id)
        assert plan is not None and plan.status == "completed"
        job = session.get(WorkJob, job_id)
        assert job is not None and job.status == "completed"

        recovery_audits = []
        for event in session.scalars(
            select(AuditEvent).where(
                AuditEvent.operation == "quarantine_purge",
                AuditEvent.result == "recovered",
            )
        ):
            details = json.loads(event.details_json or "{}")
            if details.get("plan_id") == plan_id and details.get("item_id") == item_id:
                recovery_audits.append(details)
        assert len(recovery_audits) == 1
        assert recovery_audits[0]["quarantine_entry_id"] == entry_id
        assert recovery_audits[0]["recovery_phase"] == "pre_intent"

    # The resumed purge may only zeroize the frozen payload identity.
    for path in (anchor, captured_source, public_view):
        st = path.stat(follow_symlinks=False)
        assert st.st_size == 0
        assert (st.st_dev, st.st_ino) == (frozen_st.st_dev, frozen_st.st_ino)
