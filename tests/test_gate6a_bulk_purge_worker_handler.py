from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
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
    payload = b"gate6a-purge-worker-handler"
    original = data / "purge-handler.bin"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / "pending-purge-handler.bin"),
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
        public_view = trash / f"purge-handler.q-{entry.id}.bin"
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
        return int(entry.id), anchor, captured_source, public_view


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


def _bulk_purge_plan(client: TestClient, entry_id: int) -> int:
    service = client.app.state.service
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    digest = preview.json()["preview_digest"]

    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "confirmation": "DELETE",
            "expected_preview_digest": digest,
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    return plan_id


def _run_worker(service, job_id: int, worker_id: str) -> None:
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(service.engine, service.SessionLocal, job_id, worker_id)
        BatchPlanExecuteHandler().run(job, context, service.settings)


def test_bulk_purge_worker_handler_passes_entry_and_frozen_manifest_to_executor(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, captured_source, public_view = _active_entry(client)
    plan_id = _bulk_purge_plan(client, entry_id)

    worker_id = "worker-gate6a-purge-handler"
    job_id = _prepare_worker(service, plan_id, worker_id)
    _run_worker(service, job_id, worker_id)

    assert not anchor.exists()
    assert not captured_source.exists()
    assert not public_view.exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "completed"
        assert item.reason == "purged"
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "completed"


def test_bulk_purge_worker_resumes_after_crash_immediately_after_durable_purging_intent(tmp_path: Path) -> None:
    from app.quarantine.purge import _begin_transactional_purge_intent

    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, captured_source, public_view = _active_entry(client)
    plan_id = _bulk_purge_plan(client, entry_id)

    worker_id = "worker-gate6a-purge-resume-intent"
    job_id = _prepare_worker(service, plan_id, worker_id)

    _begin_transactional_purge_intent(service.SessionLocal, entry_id, worker_id)
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.active_attempt_generation == 1
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        item.state = "executing"
        session.commit()

    assert anchor.exists()
    assert captured_source.exists()
    assert public_view.exists()

    _run_worker(service, job_id, worker_id)

    assert not anchor.exists()
    assert not captured_source.exists()
    assert not public_view.exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
        assert entry.active_attempt_generation == 2
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "completed"
        assert item.reason == "purged"


def test_bulk_purge_worker_resumes_after_generation_allocation_before_attempt_mkdir(tmp_path: Path) -> None:
    from app.quarantine.purge import _begin_transactional_purge_intent
    from app.quarantine.tx_allocator import allocate_next_generation

    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, captured_source, public_view = _active_entry(client)
    plan_id = _bulk_purge_plan(client, entry_id)

    worker_id = "worker-gate6a-purge-resume-generation"
    job_id = _prepare_worker(service, plan_id, worker_id)

    _begin_transactional_purge_intent(service.SessionLocal, entry_id, worker_id)
    generation, attempt_dir = allocate_next_generation(
        service.SessionLocal,
        entry_id,
        worker_id,
        quarantine_root=service.settings.quarantine_root,
    )
    assert generation == 2
    assert not attempt_dir.exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.active_attempt_generation == 2
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        item.state = "executing"
        session.commit()

    assert anchor.exists()
    assert captured_source.exists()
    assert public_view.exists()

    _run_worker(service, job_id, worker_id)

    assert not anchor.exists()
    assert not captured_source.exists()
    assert not public_view.exists()
    assert not attempt_dir.exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
        assert entry.active_attempt_generation == 3
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "completed"
        assert item.reason == "purged"
