from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
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


def _run_worker(service, job_id: int, worker_id: str) -> None:
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(service.engine, service.SessionLocal, job_id, worker_id)
        BatchPlanExecuteHandler().run(job, context, service.settings)


def _bulk_restore_plan_many(client: TestClient, entry_ids: list[int], conflict_policy: str) -> int:
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": entry_ids, "conflict_policy": conflict_policy},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": entry_ids,
            "conflict_policy": conflict_policy,
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    return int(generated.json()["id"])


def _bulk_restore_plan(client: TestClient, entry_id: int, conflict_policy: str) -> int:
    return _bulk_restore_plan_many(client, [entry_id], conflict_policy)


def test_bulk_restore_worker_handler_uses_exact_frozen_rename_target(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, public_view, original = _active_entry(client)

    foreign_payload = b"foreign-original-occupant-must-survive"
    original.write_bytes(foreign_payload)
    plan_id = _bulk_restore_plan(client, entry_id, "rename")

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
    job_id = _prepare_worker(service, plan_id, worker_id)

    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    _run_worker(service, job_id, worker_id)

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


def test_bulk_restore_worker_fails_closed_when_frozen_target_is_occupied_after_validate(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, public_view, original = _active_entry(client)

    original_foreign = b"original-foreign-owner"
    original.write_bytes(original_foreign)
    plan_id = _bulk_restore_plan(client, entry_id, "rename")

    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.target_path is not None
        frozen_target = Path(item.target_path)
        assert frozen_target != original
        assert not frozen_target.exists()

    execute_time_foreign = b"execute-time-foreign-owner-must-survive"
    frozen_target.write_bytes(execute_time_foreign)

    worker_id = "worker-gate6a-occupied-target"
    job_id = _prepare_worker(service, plan_id, worker_id)

    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    _run_worker(service, job_id, worker_id)

    assert original.read_bytes() == original_foreign
    assert frozen_target.read_bytes() == execute_time_foreign
    assert public_view.exists()
    assert anchor.exists()
    assert not (original.parent / "handler-restore.restored-2.txt").exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state != "restored"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state != "completed"


def test_bulk_restore_worker_rejects_entry_that_became_non_active_after_validate(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, public_view, original = _active_entry(client)
    plan_id = _bulk_restore_plan(client, entry_id, "skip")

    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    assert not original.exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        entry.state = "conflict"
        entry.tx_phase = "conflict"
        entry.last_error = "sentinel conflict before execute"
        session.commit()

    worker_id = "worker-gate6a-non-active"
    job_id = _prepare_worker(service, plan_id, worker_id)

    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    _run_worker(service, job_id, worker_id)

    assert not original.exists()
    assert public_view.exists()
    assert anchor.exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"
        assert entry.last_error == "sentinel conflict before execute"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state != "completed"


def test_bulk_restore_worker_continues_after_middle_failure_and_audits_each_success(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    data = Path(service.settings.data_mount)

    first_id, first_anchor, first_public, first_original = _active_entry(client)
    second_id, second_anchor, second_public, _ = _active_entry(client)
    third_id, third_anchor, third_public, _ = _active_entry(client)
    second_original = data / "handler-restore-2.txt"
    third_original = data / "handler-restore-3.txt"

    with service.SessionLocal() as session:
        second = session.get(QuarantineEntry, second_id)
        third = session.get(QuarantineEntry, third_id)
        assert second is not None and third is not None
        second.original_path = str(second_original)
        third.original_path = str(third_original)
        session.commit()

    plan_id = _bulk_restore_plan_many(client, [first_id, second_id, third_id], "skip")
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"

    with service.SessionLocal() as session:
        second = session.get(QuarantineEntry, second_id)
        assert second is not None
        second.state = "conflict"
        second.tx_phase = "conflict"
        second.last_error = "middle entry invalidated before execute"
        session.commit()

    worker_id = "worker-gate6a-partial"
    job_id = _prepare_worker(service, plan_id, worker_id)

    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    _run_worker(service, job_id, worker_id)

    assert first_original.exists()
    assert first_original.read_bytes() == first_anchor.read_bytes()
    assert not first_public.exists()
    assert not second_original.exists()
    assert second_public.exists()
    assert second_anchor.exists()
    assert third_original.exists()
    assert third_original.read_bytes() == third_anchor.read_bytes()
    assert not third_public.exists()

    with service.SessionLocal() as session:
        first = session.get(QuarantineEntry, first_id)
        second = session.get(QuarantineEntry, second_id)
        third = session.get(QuarantineEntry, third_id)
        assert first is not None and second is not None and third is not None
        assert (first.state, first.tx_phase) == ("restored", "restored")
        assert (second.state, second.tx_phase) == ("conflict", "conflict")
        assert second.last_error == "middle entry invalidated before execute"
        assert (third.state, third.tx_phase) == ("restored", "restored")

        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).order_by(BatchPlanItem.sequence).all()
        assert [item.state for item in items] == ["completed", "failed", "completed"]
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "partial"

        completed_restore_audits = session.query(AuditEvent).filter_by(operation="restore", result="completed").all()
        assert {event.path for event in completed_restore_audits} == {str(first_public), str(third_public)}
