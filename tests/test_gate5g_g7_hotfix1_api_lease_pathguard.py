import hashlib
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.main import create_app
from app.models import QuarantineEntry, TaskLock, utcnow
from app.service import FileCenterService
from app.quarantine.restore import execute_transactional_restore


def _setup_app_and_service(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir = data_dir / ".nas-file-center-trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"

    settings = Settings(
        config_dir=config_dir,
        database_path=db_path,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=trash_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    app = create_app(settings)
    client = TestClient(app)

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    assert resp.status_code == 200
    client.headers.update({"Origin": "http://testserver"})

    service: FileCenterService = app.state.service
    return client, service, settings, data_dir, trash_dir


def test_api_transactional_restore_with_no_worker_authority_fails_closed(tmp_path):
    """
    HOTFIX1 Requirement 6:
    Calling transactional restore directly via API with worker_id=None must fail closed.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    orig_path = data_dir / "api_test.txt"
    pub_path = trash_dir / "api_test.txt"
    payload = b"TEST_NO_WORKER_AUTHORITY"
    pub_path.write_bytes(payload)
    st = os.stat(pub_path)

    tx_dir = trash_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir / "anchor"
    os.link(str(pub_path), str(anchor))

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = QuarantineEntry(
            id=1,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    # Direct API restore call without worker authority MUST fail closed
    with pytest.raises((PermissionError, RuntimeError, ValueError)):
        service.restore_quarantine_entry(1, worker_id=None)


def test_custom_target_outside_allowed_roots_fails_closed(tmp_path):
    """
    HOTFIX1 Requirement 6:
    Custom destination outside allowed roots must fail closed.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    outside_dir = tmp_path / "outside_allowed"
    outside_dir.mkdir(parents=True, exist_ok=True)
    bad_target = outside_dir / "escape.txt"

    pub_path = trash_dir / "escape.txt"
    payload = b"ESCAPE_TEST"
    pub_path.write_bytes(payload)
    st = os.stat(pub_path)

    tx_dir = trash_dir / ".tx" / "entry-2" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir / "anchor"
    os.link(str(pub_path), str(anchor))

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=2,
            original_path=str(data_dir / "escape.txt"),
            quarantine_path=str(pub_path),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    with pytest.raises((ValueError, PermissionError)):
        execute_transactional_restore(
            service.SessionLocal,
            2,
            worker_id="worker-1",
            allowed_roots=settings.allowed_roots,
            custom_target=str(bad_target),
        )


def test_custom_target_symlink_escape_fails_closed(tmp_path):
    """
    HOTFIX1 Requirement 6:
    Custom destination attempting symlink escape must fail closed.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    outside_dir = tmp_path / "outside_symlink"
    outside_dir.mkdir(parents=True, exist_ok=True)
    symlink_dir = data_dir / "symlink_dir"
    os.symlink(str(outside_dir), str(symlink_dir))
    escape_target = symlink_dir / "evil.txt"

    pub_path = trash_dir / "evil.txt"
    payload = b"SYMLINK_ESCAPE"
    pub_path.write_bytes(payload)
    st = os.stat(pub_path)

    tx_dir = trash_dir / ".tx" / "entry-3" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir / "anchor"
    os.link(str(pub_path), str(anchor))

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=3,
            original_path=str(data_dir / "evil.txt"),
            quarantine_path=str(pub_path),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    with pytest.raises((ValueError, PermissionError)):
        execute_transactional_restore(
            service.SessionLocal,
            3,
            worker_id="worker-1",
            allowed_roots=settings.allowed_roots,
            custom_target=str(escape_target),
        )


def test_valid_worker_mediated_transactional_restore_succeeds(tmp_path):
    """
    HOTFIX1 Requirement 6:
    Valid worker-mediated transactional restore succeeds when lease is active
    and destination is validated.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    dest_path = data_dir / "valid_restore.txt"
    pub_path = trash_dir / "valid_restore.txt"
    payload = b"VALID_WORKER_RESTORE"
    pub_path.write_bytes(payload)
    st = os.stat(pub_path)

    tx_dir = trash_dir / ".tx" / "entry-4" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir / "anchor"
    os.link(str(pub_path), str(anchor))

    worker_id = "worker-valid"
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=4,
            original_path=str(dest_path),
            quarantine_path=str(pub_path),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    execute_transactional_restore(
        service.SessionLocal,
        4,
        worker_id=worker_id,
        allowed_roots=settings.allowed_roots,
        custom_target=str(dest_path),
    )

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, 4)
        assert entry.state == "restored"
        assert entry.tx_phase == "restored"

    assert dest_path.exists()
    assert dest_path.read_bytes() == payload
