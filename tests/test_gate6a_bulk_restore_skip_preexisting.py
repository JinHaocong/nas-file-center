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
    data = tmp_path / "data"; data.mkdir()
    trash = data / ".nas-file-center-trash"; trash.mkdir()
    config = tmp_path / "config"; config.mkdir()
    app = create_app(Settings(config_dir=config, data_mount=data, allowed_roots_raw=str(data), quarantine_root=trash, initial_admin_username="admin", initial_admin_password="AdminPassword123!", allow_mutation=True, allow_delete=True))
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    return client


def _active_entry(client: TestClient, name: str, payload: bytes) -> tuple[int, Path, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount); trash = Path(service.settings.quarantine_root); original = data / name
    with service.SessionLocal() as session:
        entry = QuarantineEntry(original_path=str(original), quarantine_path=str(trash / f"pending-{name}"), state="active", tx_phase="active", active_attempt_generation=1, size=0, content_hash=None, mtime_ns=0, device=0, inode=0, created_at=utcnow(), updated_at=utcnow())
        session.add(entry); session.flush()
        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"; attempt.mkdir(parents=True)
        anchor = attempt / "anchor"; captured = attempt / "captured_source"; public_view = trash / f"{Path(name).stem}.q-{entry.id}{Path(name).suffix}"
        anchor.write_bytes(payload); os.link(anchor, captured); os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)
        entry.quarantine_path = str(public_view); entry.authoritative_anchor_path = str(anchor); entry.size = st.st_size; entry.content_hash = hashlib.sha256(payload).hexdigest(); entry.mtime_ns = st.st_mtime_ns; entry.device = st.st_dev; entry.inode = st.st_ino
        session.commit(); return int(entry.id), anchor, public_view, original


def _prepare_worker(service, plan_id: int, worker_id: str) -> int:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1); session.add(lock)
        lock.locked = True; lock.owner = worker_id; lock.acquired_at = utcnow()
        job = WorkJob(kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": plan_id}), started_at=utcnow(), heartbeat_at=utcnow())
        session.add(job); session.commit(); return int(job.id)


def _run_worker(service, job_id: int, worker_id: str) -> None:
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id); assert job is not None
        BatchPlanExecuteHandler().run(job, JobContext(service.engine, service.SessionLocal, job_id, worker_id), service.settings)


def test_skip_preexisting_target_is_frozen_skip_and_sibling_still_restores(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path); service = client.app.state.service
    skipped_id, skipped_anchor, skipped_public, skipped_original = _active_entry(client, "skip-existing.txt", b"quarantined-skip-payload")
    restored_id, restored_anchor, restored_public, restored_original = _active_entry(client, "restore-normal.txt", b"quarantined-normal-payload")
    foreign_payload = b"foreign-owner-must-survive"; skipped_original.write_bytes(foreign_payload)

    preview = client.post("/api/quarantine/bulk-preview", json={"action": "restore", "entry_ids": [skipped_id, restored_id], "conflict_policy": "skip"}, headers={"Origin": "http://testserver"})
    assert preview.status_code == 200
    preview_body = preview.json(); assert preview_body["eligible_count"] == 2; assert preview_body["blocked_count"] == 0
    generated = client.post("/api/quarantine/bulk-plan", json={"action": "restore", "entry_ids": [skipped_id, restored_id], "conflict_policy": "skip", "expected_preview_digest": preview_body["preview_digest"]}, headers={"Origin": "http://testserver"})
    assert generated.status_code == 200; plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    validation = service.validate_plan(plan_id)
    assert validation["status"] == "ready"

    worker_id = "worker-gate6a-b3-skip-preexisting"; job_id = _prepare_worker(service, plan_id, worker_id)
    from app.quarantine.capability import MutationCapability
    monkeypatch.setattr("app.quarantine.capability.resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)
    _run_worker(service, job_id, worker_id)

    assert skipped_original.read_bytes() == foreign_payload; assert skipped_anchor.exists(); assert skipped_public.exists()
    assert restored_original.exists(); assert restored_original.read_bytes() == restored_anchor.read_bytes(); assert not restored_public.exists()
    with service.SessionLocal() as session:
        skipped_entry = session.get(QuarantineEntry, skipped_id); restored_entry = session.get(QuarantineEntry, restored_id)
        assert skipped_entry is not None and restored_entry is not None
        assert (skipped_entry.state, skipped_entry.tx_phase) == ("active", "active")
        assert (restored_entry.state, restored_entry.tx_phase) == ("restored", "restored")
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).order_by(BatchPlanItem.sequence).all()
        assert [item.state for item in items] == ["skipped", "completed"]
        assert "pre-existing" in (items[0].reason or "").lower()
        plan = session.get(BatchPlan, plan_id); assert plan is not None; assert plan.status == "partial"
        audits = session.query(AuditEvent).filter_by(operation="restore").all(); assert len(audits) == 2
        by_qid = {json.loads(event.details_json or "{}")["quarantine_entry_id"]: event for event in audits}
        assert set(by_qid) == {skipped_id, restored_id}; assert by_qid[skipped_id].result == "skipped"; assert by_qid[restored_id].result == "completed"
        skipped_details = json.loads(by_qid[skipped_id].details_json or "{}")
        assert skipped_details["target"] == str(skipped_original); assert skipped_details["conflict_policy"] == "skip"; assert skipped_details["result_path"] is None; assert "pre-existing" in skipped_details["reason"].lower()
