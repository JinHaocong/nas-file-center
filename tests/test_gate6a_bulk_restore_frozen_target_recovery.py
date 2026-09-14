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
    original = data / "crash-rename-restore.txt"
    payload = b"gate6a-frozen-target-crash-recovery"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / "pending-crash-rename.txt"),
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
        public_view = trash / f"crash-rename.q-{entry.id}.txt"
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
        return int(entry.id), anchor, public_view, original


def _prepare_rename_plan(client: TestClient, entry_id: int, original: Path) -> tuple[int, Path, bytes]:
    foreign_payload = b"foreign-original-owner-must-survive"
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

    service = client.app.state.service
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.target_path is not None
        frozen_target = Path(item.target_path)
    assert frozen_target != original
    assert not frozen_target.exists()
    return plan_id, frozen_target, foreign_payload


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


def _arm_crash_after_restore_intent(service, plan_id: int, entry_id: int) -> int:
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        item.state = "executing"
        entry.state = "restoring"
        entry.tx_phase = "restoring"
        entry.updated_at = utcnow()
        session.commit()
        return int(item.id)


def _run_worker(service, job_id: int, worker_id: str) -> None:
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(service.engine, service.SessionLocal, job_id, worker_id)
        BatchPlanExecuteHandler().run(job, context, service.settings)


def _assert_truthful_completed_restore(
    service,
    *,
    plan_id: int,
    item_id: int,
    entry_id: int,
    frozen_target: Path,
    job_id: int,
) -> None:
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        item = session.get(BatchPlanItem, item_id)
        assert entry is not None and item is not None
        assert (entry.state, entry.tx_phase) == ("restored", "restored")
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
        assert details["target"] == str(frozen_target)
        assert details["result_path"] == str(frozen_target)
        assert details["conflict_policy"] == "rename"


def test_restoring_crash_rename_keeps_frozen_target_when_original_owner_disappears(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, public_view, original = _active_entry(client)
    plan_id, frozen_target, _foreign_payload = _prepare_rename_plan(client, entry_id, original)
    item_id = _arm_crash_after_restore_intent(service, plan_id, entry_id)

    # The foreign owner legitimately moves away after Freeze/Validate but before restart.
    original.unlink()
    assert not original.exists()

    worker_id = "worker-gate6a-frozen-target-owner-disappears"
    job_id = _prepare_worker(service, plan_id, worker_id)
    _run_worker(service, job_id, worker_id)

    # Recovery authority is the frozen BatchPlanItem target, never a re-selected original path.
    assert not original.exists()
    assert frozen_target.exists()
    assert frozen_target.read_bytes() == anchor.read_bytes()
    assert not public_view.exists()
    _assert_truthful_completed_restore(
        service,
        plan_id=plan_id,
        item_id=item_id,
        entry_id=entry_id,
        frozen_target=frozen_target,
        job_id=job_id,
    )


def test_restoring_crash_rename_ignores_still_occupied_original_and_restores_frozen_target(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, public_view, original = _active_entry(client)
    plan_id, frozen_target, foreign_payload = _prepare_rename_plan(client, entry_id, original)
    item_id = _arm_crash_after_restore_intent(service, plan_id, entry_id)

    worker_id = "worker-gate6a-frozen-target-owner-remains"
    job_id = _prepare_worker(service, plan_id, worker_id)
    _run_worker(service, job_id, worker_id)

    assert original.read_bytes() == foreign_payload
    assert frozen_target.exists()
    assert frozen_target.read_bytes() == anchor.read_bytes()
    assert not public_view.exists()
    _assert_truthful_completed_restore(
        service,
        plan_id=plan_id,
        item_id=item_id,
        entry_id=entry_id,
        frozen_target=frozen_target,
        job_id=job_id,
    )


def test_restoring_crash_after_frozen_target_publish_converges_idempotently_without_touching_original(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, public_view, original = _active_entry(client)
    plan_id, frozen_target, foreign_payload = _prepare_rename_plan(client, entry_id, original)
    item_id = _arm_crash_after_restore_intent(service, plan_id, entry_id)

    # Simulate normal restore having already published the frozen target but crashing before terminal DB commit.
    os.link(anchor, frozen_target)
    assert frozen_target.exists()

    worker_id = "worker-gate6a-frozen-target-already-published"
    job_id = _prepare_worker(service, plan_id, worker_id)
    for _ in range(3):
        _run_worker(service, job_id, worker_id)

    assert original.read_bytes() == foreign_payload
    assert frozen_target.exists()
    assert frozen_target.read_bytes() == anchor.read_bytes()
    assert not public_view.exists()
    _assert_truthful_completed_restore(
        service,
        plan_id=plan_id,
        item_id=item_id,
        entry_id=entry_id,
        frozen_target=frozen_target,
        job_id=job_id,
    )
