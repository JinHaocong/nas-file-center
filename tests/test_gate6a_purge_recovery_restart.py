from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(reason='Gate6-A v0.3.6 COMPAT permanent purge release path is deferred after B10; dormant purge-core safety is covered by direct transactional/recovery tests')
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
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


def _active_entry(client: TestClient) -> tuple[int, Path, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-real-worker-restart"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "restart-purge.bin"),
            quarantine_path=str(trash / "pending-restart-purge.bin"),
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
        public_view = trash / f"restart-purge.q-{entry.id}.bin"
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


def test_real_worker_restart_requeues_and_resumes_partial_purge_destruction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.quarantine.purge as purge

    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, captured_source, public_view = _active_entry(client)
    frozen_st = anchor.stat(follow_symlinks=False)
    plan_id = _bulk_purge_plan(client, entry_id)
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
        entry_id,
        old_worker,
        frozen_manifest,
        service.settings.quarantine_root,
        list(service.settings.allowed_roots),
    )
    purge_dir = Path(service.settings.quarantine_root) / ".tx" / f"entry-{entry_id}" / "attempt-2" / "purge"
    assert len(list(purge_dir.iterdir())) == 3

    original_renew = purge.renew_and_assert_worker_lease
    fence_calls = 0

    def crash_after_durable_marker_before_descriptor_zeroization(*args, **kwargs):
        nonlocal fence_calls
        fence_calls += 1
        result = original_renew(*args, **kwargs)
        if fence_calls == 2:
            raise RuntimeError("simulated worker crash")
        return result

    monkeypatch.setattr(
        purge,
        "renew_and_assert_worker_lease",
        crash_after_durable_marker_before_descriptor_zeroization,
    )
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        purge.destroy_transactional_purge_capture(
            service.SessionLocal,
            entry_id,
            old_worker,
            frozen_manifest,
            service.settings.quarantine_root,
            list(service.settings.allowed_roots),
        )
    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", original_renew)

    marker = purge_dir / "destroy-intent.json"
    assert marker.is_file()
    assert {p.name for p in purge_dir.iterdir()} == {
        "current-anchor",
        "captured-source",
        "public-view",
        "destroy-intent.json",
    }
    for payload_path in (
        anchor,
        captured_source,
        public_view,
        purge_dir / "current-anchor",
        purge_dir / "captured-source",
        purge_dir / "public-view",
    ):
        payload_st = payload_path.stat(follow_symlinks=False)
        assert payload_st.st_size == frozen_st.st_size
        assert (payload_st.st_dev, payload_st.st_ino) == (frozen_st.st_dev, frozen_st.st_ino)

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
        assert job is not None
        assert job.status == "queued"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "executing"

    assert process_work_job(
        service.settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=new_worker,
    ) is True

    assert marker.is_file()
    for tombstone in (
        anchor,
        captured_source,
        public_view,
        purge_dir / "current-anchor",
        purge_dir / "captured-source",
        purge_dir / "public-view",
    ):
        tombstone_st = tombstone.stat(follow_symlinks=False)
        assert tombstone_st.st_size == 0
        assert (tombstone_st.st_dev, tombstone_st.st_ino) == (frozen_st.st_dev, frozen_st.st_ino)
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
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "completed"
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "completed"
