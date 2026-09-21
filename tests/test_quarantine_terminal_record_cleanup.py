import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import Settings
from app.main import create_app
from app.models import QuarantineEntry, TaskLock, WorkJob, utcnow
from app.service import FileCenterService
from app.worker import process_work_job


@pytest.fixture
def maintenance_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
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
    client.headers["Origin"] = "http://testserver"
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200

    return {
        "service": service,
        "settings": settings,
        "data": data,
        "trash": trash,
        "admin": client,
    }


def _seed(service, data: Path, trash: Path, *, state: str, name: str) -> int:
    with service.SessionLocal() as session:
        row = QuarantineEntry(
            original_path=str(data / name),
            quarantine_path=str(trash / (name + ".q")),
            state=state,
            size=0,
            mtime_ns=0,
            device=0,
            inode=0,
        )
        session.add(row)
        session.commit()
        return int(row.id)



def _seed_restored_with_artifacts(
    service,
    data: Path,
    trash: Path,
    *,
    name: str,
    mode: str = "compat_transactional",
    artifact_names: tuple[str, ...] = ("anchor", "captured_source", "captured_quarantine_view"),
) -> tuple[int, Path, Path]:
    target = data / name
    payload = (f"restored-payload-{name}").encode("utf-8")
    target.write_bytes(payload)
    target_stat = os.lstat(target)
    content_hash = hashlib.sha256(payload).hexdigest()

    with service.SessionLocal() as session:
        row = QuarantineEntry(
            original_path=str(target),
            quarantine_path=str(trash / (name + ".q")),
            state="restored",
            tx_phase="restored",
            transaction_mode=mode,
            size=len(payload),
            content_hash=content_hash,
            mtime_ns=int(target_stat.st_mtime_ns),
            device=int(target_stat.st_dev),
            inode=int(target_stat.st_ino),
            restore_target_path=str(target),
            restore_device=int(target_stat.st_dev),
            restore_inode=int(target_stat.st_ino),
            restore_mtime_ns=int(target_stat.st_mtime_ns),
        )
        session.add(row)
        session.commit()
        entry_id = int(row.id)

    attempt = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
    attempt.mkdir(parents=True)

    if mode == "cross_storage_transactional":
        for artifact_name in artifact_names:
            (attempt / artifact_name).write_bytes(payload)
    else:
        for artifact_name in artifact_names:
            os.link(target, attempt / artifact_name)
        with service.SessionLocal() as session:
            row = session.get(QuarantineEntry, entry_id)
            row.authoritative_anchor_path = str(attempt / "anchor")
            session.commit()

    return entry_id, target, attempt


def _run_cleanup_job(env: dict, job_id: int, *, worker_id: str = "cleanup-test-worker") -> bool:
    service = env["service"]
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(
                id=1,
                locked=True,
                owner=worker_id,
                acquired_at=utcnow(),
            )
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        session.commit()

    return process_work_job(
        env["settings"],
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=worker_id,
    )

def test_terminal_record_cleanup_accepts_abandoned_and_conflict(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    ids = [
        _seed(service, data, trash, state="abandoned", name="abandoned"),
        _seed(service, data, trash, state="conflict", name="conflict"),
    ]
    for entry_id in ids:
        response = admin.delete(
            f"/api/quarantine/{entry_id}/record?confirmation=DELETE_RECORD"
        )
        assert response.status_code == 200

    with service.SessionLocal() as session:
        for entry_id in ids:
            assert session.get(QuarantineEntry, entry_id) is None


def test_conflict_record_cleanup_blocks_when_tx_artifact_exists(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    entry_id = _seed(service, data, trash, state="conflict", name="conflict-artifact")
    tx_dir = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
    tx_dir.mkdir(parents=True)
    (tx_dir / "anchor").write_text("evidence", encoding="utf-8")

    response = admin.delete(
        f"/api/quarantine/{entry_id}/record?confirmation=DELETE_RECORD"
    )
    assert response.status_code == 409

    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is not None


def test_bulk_terminal_record_cleanup_accepts_mixed_states(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    ids = [
        _seed(service, data, trash, state="purged", name="purged"),
        _seed(service, data, trash, state="abandoned", name="abandoned-bulk"),
        _seed(service, data, trash, state="conflict", name="conflict-bulk"),
    ]
    response = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": ids, "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.json()["deleted_ids"] == ids

    with service.SessionLocal() as session:
        assert list(
            session.scalars(select(QuarantineEntry).where(QuarantineEntry.id.in_(ids)))
        ) == []


def test_bulk_cleanup_restored_same_storage_reclaims_private_artifacts(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    entry_id, target, attempt = _seed_restored_with_artifacts(
        service,
        data,
        trash,
        name="restored-same-storage.bin",
    )
    tx_entry_root = trash / ".tx" / f"entry-{entry_id}"
    assert target.exists()
    assert (attempt / "anchor").exists()

    response = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": [entry_id], "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["entry_ids"] == [entry_id]
    job_id = int(body["work_job_id"])

    assert _run_cleanup_job(env, job_id) is True
    assert target.exists()
    assert not tx_entry_root.exists()

    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is None
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "completed"


def test_bulk_cleanup_restored_cross_storage_hash_verifies_payload(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    entry_id, target, attempt = _seed_restored_with_artifacts(
        service,
        data,
        trash,
        name="restored-cross-storage.bin",
        mode="cross_storage_transactional",
        artifact_names=("cross-storage-staging",),
    )
    artifact = attempt / "cross-storage-staging"

    response = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": [entry_id], "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    job_id = int(body["work_job_id"])
    assert _run_cleanup_job(env, job_id) is True
    assert target.exists()
    assert not artifact.exists()
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "completed"


def test_restored_cleanup_blocks_when_restore_target_identity_changed(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    entry_id, target, attempt = _seed_restored_with_artifacts(
        service,
        data,
        trash,
        name="restored-replaced.bin",
    )
    previous = target.with_suffix(".previous")
    target.rename(previous)
    target.write_bytes(b"replacement")

    response = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": [entry_id], "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    job_id = int(body["work_job_id"])
    assert _run_cleanup_job(env, job_id) is False
    assert target.read_bytes() == b"replacement"
    assert (attempt / "anchor").exists()
    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is not None
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "failed"


def test_restored_cleanup_blocks_unknown_private_artifact(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    entry_id, target, attempt = _seed_restored_with_artifacts(
        service,
        data,
        trash,
        name="restored-unknown.bin",
    )
    (attempt / "unexpected.bin").write_bytes(b"unknown")

    response = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": [entry_id], "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    job_id = int(body["work_job_id"])
    assert _run_cleanup_job(env, job_id) is False
    assert target.exists()
    assert (attempt / "unexpected.bin").exists()
    assert (attempt / "anchor").exists()
    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is not None
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "failed"
