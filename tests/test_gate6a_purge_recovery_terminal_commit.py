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
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
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


def _active_entry(client: TestClient) -> int:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-terminal-purge-finalize-crash"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "terminal-purge.bin"),
            quarantine_path=str(trash / "pending-terminal-purge.bin"),
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
        public_view = trash / f"terminal-purge.q-{entry.id}.bin"
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
        return int(entry.id)


def _bulk_purge_plan(client: TestClient, entry_id: int) -> tuple[int, str]:
    service = client.app.state.service
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_digest = str(preview.json()["preview_digest"])
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "confirmation": "DELETE",
            "expected_preview_digest": preview_digest,
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    return plan_id, preview_digest


def test_worker_reconciles_terminal_purge_committed_before_item_and_audit_finalize(tmp_path: Path) -> None:
    import app.quarantine.purge as purge

    client = _client(tmp_path)
    service = client.app.state.service
    entry_id = _active_entry(client)
    plan_id, preview_digest = _bulk_purge_plan(client, entry_id)
    old_worker = "worker-old"
    new_worker = "worker-new"

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
        item.state = "executing"
        metadata = json.loads(item.metadata_json or "{}")
        frozen_manifest = metadata["purge_topology_manifest"]
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

    # Simulate the exact crash window: the purge engine has already committed the
    # irreversible terminal QuarantineEntry truth, but Worker Phase 3 has not yet
    # finalized BatchPlanItem or emitted the purge audit.
    purge.execute_transactional_purge_capture(
        service.SessionLocal,
        entry_id,
        old_worker,
        frozen_manifest,
        service.settings.quarantine_root,
        list(service.settings.allowed_roots),
    )
    purge.destroy_transactional_purge_capture(
        service.SessionLocal,
        entry_id,
        old_worker,
        frozen_manifest,
        service.settings.quarantine_root,
        list(service.settings.allowed_roots),
    )

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "executing"
        audits = list(session.scalars(select(AuditEvent).where(AuditEvent.operation == "quarantine_purge")))
        assert audits == []
        lock = session.get(TaskLock, 1)
        assert lock is not None
        lock.acquired_at = utcnow() - timedelta(seconds=31)
        session.commit()

    assert acquire_worker_ownership(service.engine, service.SessionLocal, new_worker) is True
    stats = recover_interrupted_jobs(service.engine, service.SessionLocal, worker_id=new_worker)
    assert stats["recovered_requeued"] == 1
    assert stats["failed_interrupted"] == 0

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

        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "completed"
        assert item.reason == "reconciled transactional purge after crash (purged)"

        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "completed"
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "completed"

        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.operation == "quarantine_purge",
                    AuditEvent.result == "completed",
                )
            )
        )
        assert len(audits) == 1
        details = json.loads(audits[0].details_json or "{}")
        assert details["quarantine_entry_id"] == entry_id
        assert details["preview_digest"] == preview_digest
        assert details["reason"] == "reconciled transactional purge after crash (purged)"
