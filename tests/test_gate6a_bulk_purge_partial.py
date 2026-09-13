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
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    ).status_code == 200
    return client


def _active_entry(client: TestClient, label: str) -> tuple[int, Path, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = f"gate6a-purge-partial-{label}".encode()

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / f"{label}.bin"),
            quarantine_path=str(trash / f"pending-{label}.bin"),
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
        entry_id = int(entry.id)
        attempt = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured_source = attempt / "captured_source"
        public_view = trash / f"{label}.q-{entry_id}.bin"
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
        return entry_id, anchor, captured_source, public_view


def test_bulk_purge_continues_after_one_entry_failure_and_finishes_partial(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    first = _active_entry(client, "first")
    second = _active_entry(client, "second")
    third = _active_entry(client, "third")
    entry_ids = [first[0], second[0], third[0]]

    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": entry_ids},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_digest = preview.json()["preview_digest"]
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": entry_ids,
            "confirmation": "DELETE",
            "expected_preview_digest": preview_digest,
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"

    # Execute-time DB lifecycle race on only the middle member. Filesystem identity
    # stays unchanged so batch preflight cannot convert this into a whole-plan stale abort.
    with service.SessionLocal() as session:
        middle = session.get(QuarantineEntry, second[0])
        assert middle is not None
        middle.state = "conflict"
        middle.tx_phase = "conflict"
        middle.last_error = "test-only execute-time lifecycle race"
        session.commit()

    worker_id = "worker-gate6a-purge-partial"
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

    for path in first[1:]:
        assert not path.exists()
    for path in second[1:]:
        assert path.exists()
    for path in third[1:]:
        assert not path.exists()

    with service.SessionLocal() as session:
        rows = list(
            session.query(BatchPlanItem)
            .filter_by(plan_id=plan_id)
            .order_by(BatchPlanItem.sequence)
        )
        assert [row.state for row in rows] == ["completed", "failed", "completed"]
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "partial"

        first_entry = session.get(QuarantineEntry, first[0])
        second_entry = session.get(QuarantineEntry, second[0])
        third_entry = session.get(QuarantineEntry, third[0])
        assert first_entry is not None and first_entry.state == "purged"
        assert second_entry is not None and second_entry.state == "conflict"
        assert third_entry is not None and third_entry.state == "purged"
