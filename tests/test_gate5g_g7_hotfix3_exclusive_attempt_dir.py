import hashlib
import os
import stat
from pathlib import Path
import pytest
from sqlalchemy import text

from app.models import QuarantineEntry, utcnow, TaskLock
from app.db import create_engine_and_session, init_db
from app.quarantine.engine import execute_transactional_quarantine
from app.quarantine.tx_allocator import allocate_and_create_attempt_dir


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_preexisting_generation_directory_is_never_silently_adopted(tmp_path, session_factory):
    """
    Finding 4:
    generation N committed
    foreign/precreated attempt-N directory already exists
    → no payload syscall inside that directory
    → N+1 allocated
    → attempt-(N+1) created mode 0700 exclusively.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    source = data_dir / "test_file.txt"
    payload = b"EXCLUSIVE_ATTEMPT_DIR_PAYLOAD"
    source.write_bytes(payload)
    st = os.stat(source)
    chash = hashlib.sha256(payload).hexdigest()

    pub_path = quarantine_root / "test_file.txt"

    # Attacker or previous failed run pre-created attempt-1 with foreign permissions / contents
    attempt_1_dir = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt_1_dir.mkdir(parents=True, exist_ok=False)
    foreign_marker = attempt_1_dir / "foreign_file.bin"
    foreign_marker.write_bytes(b"MALICIOUS_OR_STALE_PAYLOAD")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase=None,
            active_attempt_generation=0,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(payload),
            content_hash=chash,
        )
        session.add(entry)
        session.commit()

    execute_transactional_quarantine(
        session_factory,
        1,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[data_dir],
    )

    # 1. attempt-1 MUST NOT have been adopted or polluted with new syscalls
    assert foreign_marker.exists()
    assert not (attempt_1_dir / "anchor").exists(), "Must never link anchor into pre-existing attempt-1 directory"
    assert not (attempt_1_dir / "captured_source").exists(), "Must never capture into pre-existing attempt-1 directory"

    # 2. attempt-2 must have been allocated and created exclusively
    attempt_2_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    assert attempt_2_dir.exists(), "Must allocate attempt-2 when attempt-1 already exists"

    # 3. Permissions on attempt-2 must be mode 0o700
    st_dir = os.stat(attempt_2_dir)
    mode = stat.S_IMODE(st_dir.st_mode)
    assert mode == 0o700, f"Attempt directory mode must be 0o700, got {oct(mode)}"

    # 4. Entry active_attempt_generation in DB must be 2
    with session_factory() as session:
        e = session.get(QuarantineEntry, 1)
        assert e.active_attempt_generation == 2
        assert e.state == "active"
