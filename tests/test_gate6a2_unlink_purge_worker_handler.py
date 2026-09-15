from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.quarantine.unlink_purge import execute_journaled_unlink_purge
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


def _active_entry(client: TestClient) -> tuple[int, Path, Path, Path, Path, Path, bytes]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    indexed = data / "indexed"
    indexed.mkdir()
    payload = b"gate6a2-worker-unlink-purge"
    original = data / "selected.bin"
    external_survivor = indexed / "external-hardlink.bin"
    unrelated = indexed / "unrelated.bin"
    unrelated.write_bytes(b"must-survive")

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / "pending.bin"),
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
        public_view = trash / f"selected.q-{entry.id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        os.link(anchor, external_survivor)
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.size = st.st_size
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.mtime_ns = st.st_mtime_ns
        entry.device = st.st_dev
        entry.inode = st.st_ino
        session.commit()
        return (
            int(entry.id),
            anchor,
            captured,
            public_view,
            external_survivor,
            unrelated,
            payload,
        )


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

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        metadata = json.loads(item.metadata_json or "{}")
        assert item.operation == "quarantine_unlink_purge"
        assert metadata["purge_semantics"] == "unlink_v1"
        assert metadata["quarantine_entry_id"] == entry_id
        assert isinstance(metadata["unlink_manifest"], dict)
    return plan_id


def _claim_worker_and_job(service, plan_id: int, worker_id: str) -> int:
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


def _claim_worker_only(service, worker_id: str) -> None:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()
        session.commit()


def _run_worker(service, job_id: int, worker_id: str) -> None:
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(service.engine, service.SessionLocal, job_id, worker_id)
        BatchPlanExecuteHandler().run(job, context, service.settings)


def _assert_safe_terminal(
    service,
    plan_id: int,
    entry_id: int,
    anchor: Path,
    captured: Path,
    public_view: Path,
    external_survivor: Path,
    unrelated: Path,
    payload: bytes,
) -> None:
    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()
    assert external_survivor.exists()
    assert external_survivor.read_bytes() == payload
    assert unrelated.read_bytes() == b"must-survive"

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None

        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.operation == "quarantine_unlink_purge"
        assert item.state == "completed"
        assert item.reason == "purged"

        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "completed"


def test_bulk_unlink_purge_worker_executes_exact_frozen_authority(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    (
        entry_id,
        anchor,
        captured,
        public_view,
        external_survivor,
        unrelated,
        payload,
    ) = _active_entry(client)
    survivor_before = external_survivor.stat(follow_symlinks=False)
    plan_id = _bulk_purge_plan(client, entry_id)

    worker_id = "worker-gate6a2-unlink"
    job_id = _claim_worker_and_job(service, plan_id, worker_id)
    _run_worker(service, job_id, worker_id)

    _assert_safe_terminal(
        service,
        plan_id,
        entry_id,
        anchor,
        captured,
        public_view,
        external_survivor,
        unrelated,
        payload,
    )
    survivor_after = external_survivor.stat(follow_symlinks=False)
    assert (survivor_after.st_dev, survivor_after.st_ino) == (
        survivor_before.st_dev,
        survivor_before.st_ino,
    )


def test_bulk_unlink_purge_successor_worker_resumes_only_durable_exact_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.quarantine.unlink_purge as unlink_purge

    client = _client(tmp_path)
    service = client.app.state.service
    (
        entry_id,
        anchor,
        captured,
        public_view,
        external_survivor,
        unrelated,
        payload,
    ) = _active_entry(client)
    plan_id = _bulk_purge_plan(client, entry_id)

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        metadata = json.loads(item.metadata_json or "{}")
        frozen_manifest = metadata["unlink_manifest"]

    old_worker = "worker-gate6a2-before-crash"
    _claim_worker_only(service, old_worker)
    real_unlink = unlink_purge.os.unlink
    unlink_calls = 0

    def crash_after_first_authorized_unlink(path, *args, **kwargs):
        nonlocal unlink_calls
        result = real_unlink(path, *args, **kwargs)
        unlink_calls += 1
        if unlink_calls == 1:
            raise RuntimeError("simulated worker crash after first unlink")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(unlink_purge.os, "unlink", crash_after_first_authorized_unlink)
        with pytest.raises(RuntimeError, match="simulated worker crash"):
            execute_journaled_unlink_purge(
                service.SessionLocal,
                entry_id=entry_id,
                quarantine_root=service.settings.quarantine_root,
                frozen_manifest=frozen_manifest,
                worker_id=old_worker,
            )

    assert not anchor.exists()
    assert captured.exists()
    assert public_view.exists()
    assert external_survivor.read_bytes() == payload
    assert unrelated.read_bytes() == b"must-survive"

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        item.state = "executing"
        item.reason = None
        session.commit()

    successor = "worker-gate6a2-after-crash"
    job_id = _claim_worker_and_job(service, plan_id, successor)

    def forbidden_ftruncate(*args, **kwargs):
        pytest.fail("new unlink recovery must never fall through to ftruncate")

    with monkeypatch.context() as patch:
        patch.setattr(os, "ftruncate", forbidden_ftruncate)
        _run_worker(service, job_id, successor)

    _assert_safe_terminal(
        service,
        plan_id,
        entry_id,
        anchor,
        captured,
        public_view,
        external_survivor,
        unrelated,
        payload,
    )
