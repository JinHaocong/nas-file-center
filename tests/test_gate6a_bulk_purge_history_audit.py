from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler


def test_bulk_purge_audits_retired_historical_conflict_alias(tmp_path: Path) -> None:
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
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    ).status_code == 200
    service = app.state.service

    payload = b"gate6a-purge-history-audit"
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
    assert historical_id in preview_body["items"][0]["purge_topology_manifest"]["historical_conflict_entry_ids"]
    preview_digest = preview_body["preview_digest"]

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

    worker_id = "worker-gate6a-purge-history-audit"
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
        job_id = int(job.id)

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        BatchPlanExecuteHandler().run(
            job,
            JobContext(service.engine, service.SessionLocal, job_id, worker_id),
            service.settings,
        )

    assert not historical_anchor.exists()
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "completed"
        historical_row = session.get(QuarantineEntry, historical_id)
        assert historical_row is not None
        assert historical_row.state == "conflict"
        assert historical_row.tx_phase == "conflict"
        retired_alias_audit = (
            session.query(AuditEvent)
            .filter(AuditEvent.path == str(historical_anchor), AuditEvent.result == "completed")
            .order_by(AuditEvent.id.desc())
            .first()
        )
        assert retired_alias_audit is not None
