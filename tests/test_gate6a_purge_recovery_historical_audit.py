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


def test_restart_reconstructs_historical_conflict_audit_after_terminal_purge_crash(tmp_path: Path) -> None:
    import app.quarantine.purge as purge

    client = _client(tmp_path)
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-terminal-purge-history-audit-crash"

    with service.SessionLocal() as session:
        selected = QuarantineEntry(
            original_path=str(data / "selected.bin"),
            quarantine_path=str(trash / "pending-selected.bin"),
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
        session.add(selected)
        session.flush()
        selected_id = int(selected.id)

        selected_attempt = trash / ".tx" / f"entry-{selected_id}" / "attempt-1"
        selected_attempt.mkdir(parents=True)
        anchor = selected_attempt / "anchor"
        captured_source = selected_attempt / "captured_source"
        public_view = trash / f"selected.q-{selected_id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured_source)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)
        digest = hashlib.sha256(payload).hexdigest()

        selected.quarantine_path = str(public_view)
        selected.authoritative_anchor_path = str(anchor)
        selected.size = st.st_size
        selected.content_hash = digest
        selected.mtime_ns = st.st_mtime_ns
        selected.device = st.st_dev
        selected.inode = st.st_ino

        historical = QuarantineEntry(
            original_path=str(data / "historical.bin"),
            quarantine_path=str(trash / "historical.q.bin"),
            state="conflict",
            tx_phase="conflict",
            authoritative_anchor_path=None,
            active_attempt_generation=1,
            size=st.st_size,
            content_hash=digest,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(historical)
        session.flush()
        historical_id = int(historical.id)
        historical_attempt = trash / ".tx" / f"entry-{historical_id}" / "attempt-1"
        historical_attempt.mkdir(parents=True)
        historical_anchor = historical_attempt / "anchor"
        os.link(anchor, historical_anchor)
        session.commit()

    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [selected_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["blocked_count"] == 0
    preview_item = preview_body["items"][0]
    frozen_preview_manifest = preview_item["purge_topology_manifest"]
    assert historical_id in frozen_preview_manifest["historical_conflict_entry_ids"]
    assert any(
        alias.get("role") == "historical_conflict_candidate"
        and alias.get("owner_entry_id") == historical_id
        and alias.get("path") == str(historical_anchor)
        for alias in frozen_preview_manifest["aliases"]
    )
    preview_digest = str(preview_body["preview_digest"])

    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [selected_id],
            "confirmation": "DELETE",
            "expected_preview_digest": preview_digest,
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"

    old_worker = "worker-old-history-audit-crash"
    new_worker = "worker-new-history-audit-crash"
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
        frozen_manifest = dict(metadata["frozen_purge_topology_manifest"])
        frozen_manifest["frozen_payload_identity"] = {
            "device": item.expected_device,
            "inode": item.expected_inode,
            "size": item.expected_size,
            "mtime_ns": item.expected_mtime_ns,
            "content_hash": item.expected_hash,
        }
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

    purge.execute_transactional_purge_capture(
        service.SessionLocal,
        selected_id,
        old_worker,
        frozen_manifest,
        service.settings.quarantine_root,
        list(service.settings.allowed_roots),
    )
    purge.destroy_transactional_purge_capture(
        service.SessionLocal,
        selected_id,
        old_worker,
        frozen_manifest,
        service.settings.quarantine_root,
        list(service.settings.allowed_roots),
    )

    with service.SessionLocal() as session:
        selected = session.get(QuarantineEntry, selected_id)
        historical = session.get(QuarantineEntry, historical_id)
        assert selected is not None and selected.state == "purged" and selected.tx_phase == "purged"
        assert historical is not None and historical.state == "conflict" and historical.tx_phase == "conflict"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "executing"
        assert list(session.scalars(select(AuditEvent).where(AuditEvent.operation == "quarantine_purge"))) == []
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
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "completed"
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None and plan.status == "completed"
        job = session.get(WorkJob, job_id)
        assert job is not None and job.status == "completed"

        completed_audits = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.operation == "quarantine_purge", AuditEvent.result == "completed")
                .order_by(AuditEvent.id)
            )
        )
        decoded = [(event, json.loads(event.details_json or "{}")) for event in completed_audits]
        selected_audits = [
            (event, details)
            for event, details in decoded
            if details.get("quarantine_entry_id") == selected_id
            and details.get("role") != "historical_conflict_candidate"
        ]
        historical_audits = [
            (event, details)
            for event, details in decoded
            if details.get("quarantine_entry_id") == selected_id
            and details.get("role") == "historical_conflict_candidate"
        ]

        assert len(selected_audits) == 1
        assert selected_audits[0][1]["preview_digest"] == preview_digest
        assert len(historical_audits) == 1
        historical_event, historical_details = historical_audits[0]
        assert historical_event.path == str(historical_anchor)
        assert historical_details["linked_quarantine_entry_id"] == historical_id
        assert historical_details["preview_digest"] == preview_digest
        assert historical_details["reason"] == "retired linked historical conflict alias"
