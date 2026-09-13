from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler


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


def _active_entry(client: TestClient) -> tuple[int, Path, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    original = data / "handler-restore.txt"
    payload = b"gate6a-handler-frozen-target"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / "pending-handler-restore.txt"),
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
        public_view = trash / f"handler-restore.q-{entry.id}.txt"
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
        return entry.id, anchor, public_view, original


def test_bulk_restore_worker_handler_uses_exact_frozen_rename_target(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, public_view, original = _active_entry(client)

    foreign_payload = b"foreign-original-occupant-must-survive"
    original.write_bytes(foreign_payload)

    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": [entry_id], "conflict_policy": "rename"},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "rename",
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])

    frozen = service.freeze_plan(plan_id)
    assert frozen.status == "frozen"
    detail = service.validate_plan(plan_id)
    assert detail["status"] == "ready"

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.target_path is not None
        frozen_target = Path(item.target_path)
        assert frozen_target != original
        assert not frozen_target.exists()

        worker_id = "worker-gate6a-handler"
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
        job_id = job.id

    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(service.engine, service.SessionLocal, job_id, worker_id)
        BatchPlanExecuteHandler().run(job, context, service.settings)

    assert original.read_bytes() == foreign_payload
    assert frozen_target.exists()
    assert frozen_target.read_bytes() == anchor.read_bytes()
    assert not public_view.exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "restored"
        assert entry.tx_phase == "restored"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "completed"
