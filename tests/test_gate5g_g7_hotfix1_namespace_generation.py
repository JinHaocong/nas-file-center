import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow
from app.quarantine.tx_allocator import allocate_next_generation
from app.quarantine.reconcile import reconcile_quarantine_transaction


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_transaction_namespace_derived_from_quarantine_root_not_nested_path(tmp_path, session_factory):
    """
    HOTFIX1 Requirement 8:
    Private tx namespace must be exactly <quarantine_root>/.tx/entry-<id>/attempt-<gen>/.
    Must NOT be derived from Path(entry.quarantine_path).parent / ".tx".
    """
    q_root = tmp_path / "trash_root"
    q_root.mkdir()

    # Highly nested public quarantine path
    nested_pub = q_root / "2026" / "09" / "plan-42" / "file.txt"
    orig_path = tmp_path / "data" / "file.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(orig_path),
            quarantine_path=str(nested_pub),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=0,
            size=10,
            content_hash="dummy",
            device=1,
            inode=1,
            mtime_ns=1,
        )
        session.add(entry)
        session.commit()

    gen, attempt_dir = allocate_next_generation(
        session_factory,
        1,
        worker_id="worker-1",
        quarantine_root=q_root,
    )

    # Must be exactly <q_root>/.tx/entry-1/attempt-1
    expected_dir = q_root / ".tx" / "entry-1" / f"attempt-{gen}"
    assert attempt_dir == expected_dir, f"Expected {expected_dir}, got {attempt_dir}"


def test_reconcile_variant1_missing_attempt_dir_unpacks_correctly(tmp_path, session_factory):
    """
    HOTFIX1 Requirement 8:
    Reconciler Variant 1: attempt directory does not exist.
    Must allocate new generation (fixing tuple unpack bug) and create attempt dir with mode 0700.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_root = tmp_path / "trash"
    q_root.mkdir()

    orig_file = data_dir / "v1.txt"
    payload = b"VARIANT1_TEST"
    orig_file.write_bytes(payload)
    st = os.stat(orig_file)

    pub_path = q_root / "v1.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(orig_file),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=1,  # Attempt 1 dir does NOT exist
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1", quarantine_root=q_root)

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        # Should have incremented generation from 1 to 2
        assert entry.active_attempt_generation == 2
        # And attempt-2 directory must exist with mode 0700
        attempt_dir = q_root / ".tx" / "entry-1" / "attempt-2"
        assert attempt_dir.exists()
        # Verify mode is 0700
        assert (os.stat(attempt_dir).st_mode & 0o777) == 0o700
        # Must NOT create an attempt-(2, ...) directory!
        for p in (q_root / ".tx" / "entry-1").iterdir():
            assert not p.name.startswith("attempt-("), f"Found tuple name: {p.name}"
