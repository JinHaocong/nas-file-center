"""V1.6 / #403 API-to-Worker mutation-boundary regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import QuarantineEntry, User, WorkJob, utcnow
from app.service import FileCenterService
from app.tasks.recovery import acquire_worker_ownership
from app.worker import process_work_job


def test_transactional_single_purge_api_only_enqueues_worker_and_preserves_payload_until_worker_runs(
    tmp_path: Path,
):
    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200

    payload = b"single-purge-must-run-in-worker"
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "original.bin"),
            quarantine_path="pending-public-view",
            state="active",
            tx_phase="active",
            transaction_mode="same_storage_transactional",
            active_attempt_generation=1,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()
        entry_id = int(entry.id)

        attempt = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"single-purge.q-{entry_id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)

        entry.authoritative_anchor_path = str(anchor)
        entry.quarantine_path = str(public_view)
        entry.device = st.st_dev
        entry.inode = st.st_ino
        entry.size = st.st_size
        entry.mtime_ns = st.st_mtime_ns
        entry.content_hash = __import__("hashlib").sha256(payload).hexdigest()
        session.commit()

    response = client.post(
        f"/api/quarantine/{entry_id}/purge",
        json={"confirmation": "DELETE"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 202
    result = response.json()
    assert result["status"] == "queued"
    assert result["entry_id"] == entry_id
    assert isinstance(result["work_job_id"], int)
    assert anchor.is_file()
    assert captured.is_file()
    assert public_view.is_file()
    assert anchor.read_bytes() == captured.read_bytes() == public_view.read_bytes() == payload

    with service.SessionLocal() as session:
        persisted = session.get(QuarantineEntry, entry_id)
        job = session.get(WorkJob, result["work_job_id"])
        assert persisted is not None
        assert persisted.state == "active"
        assert job is not None
        assert job.kind == "quarantine-single-purge"
        state = json.loads(job.state_json or "{}")
        assert state["entry_id"] == entry_id
        assert state["confirmation"] == "DELETE"
        assert state["frozen_manifest"]["selected_entry_id"] == entry_id

    worker_id = "worker-single-purge-test"
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id)
    assert process_work_job(
        settings,
        result["work_job_id"],
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=worker_id,
    )

    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()
    with service.SessionLocal() as session:
        persisted = session.get(QuarantineEntry, entry_id)
        job = session.get(WorkJob, result["work_job_id"])
        assert persisted is not None
        assert persisted.state == "purged"
        assert job is not None
        assert job.status == "completed"

def test_legacy_restore_api_only_enqueues_worker_and_preserves_payload_until_worker_runs(
    tmp_path: Path,
):
    """Legacy restore must not rename a media file in the API process."""
    import hashlib

    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    client = TestClient(create_app(settings))
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200

    payload = b"legacy-restore-must-run-in-worker"
    quarantined = trash / "legacy-restore.q.bin"
    destination = data / "restored.bin"
    quarantined.write_bytes(payload)
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(destination),
            quarantine_path=str(quarantined),
            state="active",
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()
        entry_id = int(entry.id)
        session.commit()

    response = client.post(
        f"/api/quarantine/{entry_id}/restore",
        json={"conflict_policy": "skip"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "queued"
    assert queued["entry_id"] == entry_id
    assert isinstance(queued["work_job_id"], int)
    assert quarantined.is_file()
    assert quarantined.read_bytes() == payload
    assert not destination.exists()

    with service.SessionLocal() as session:
        persisted = session.get(QuarantineEntry, entry_id)
        job = session.get(WorkJob, queued["work_job_id"])
        assert persisted is not None
        assert persisted.state == "active"
        assert job is not None
        assert job.kind == "quarantine-restore"
        state = json.loads(job.state_json or "{}")
        assert state["entry_id"] == entry_id
        assert state["conflict_policy"] == "skip"
        assert state["expected_identity"]["quarantine_path"] == str(quarantined)

    worker_id = "worker-legacy-restore-test"
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id)
    assert process_work_job(
        settings,
        queued["work_job_id"],
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=worker_id,
    )

    assert destination.read_bytes() == payload
    assert not quarantined.exists()
    with service.SessionLocal() as session:
        persisted = session.get(QuarantineEntry, entry_id)
        job = session.get(WorkJob, queued["work_job_id"])
        assert persisted is not None
        assert persisted.state == "restored"
        assert job is not None
        assert job.status == "completed"
        assert job.checkpoint_json
        checkpoint = json.loads(job.checkpoint_json)
        assert checkpoint["schema_version"] == 1
        assert checkpoint["result"]["state"] == "restored"
