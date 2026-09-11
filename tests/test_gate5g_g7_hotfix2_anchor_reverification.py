import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text

from app.models import QuarantineEntry, utcnow, TaskLock
from app.db import create_engine_and_session, init_db
from app.quarantine.restore import execute_transactional_restore
from app.quarantine.reconcile import reconcile_quarantine_transaction


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_restore_rejects_replaced_authoritative_anchor(tmp_path, session_factory):
    """
    HOTFIX2 Item 4 Test A:
    Replace authoritative anchor pathname with foreign regular file before restore
    → original path MUST NOT receive foreign payload
    → entry transitions to conflict / conflict
    → foreign anchor file preserved in place
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    orig_path = allowed_root / "document.txt"
    pub_path = quarantine_root / "document.txt"

    genuine_payload = b"GENUINE_ANCHOR_CONTENT"
    foreign_payload = b"ATTACKER_FOREIGN_ANCHOR_PAYLOAD"

    tx_dir = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = tx_dir / "anchor"

    # Setup DB with genuine Gate3 metadata
    expected_size = len(genuine_payload)
    expected_hash = hashlib.sha256(genuine_payload).hexdigest()
    # Write genuine temporarily to obtain expected dev/ino
    anchor_path.write_bytes(genuine_payload)
    st_genuine = os.stat(anchor_path)
    expected_dev = st_genuine.st_dev
    expected_ino = st_genuine.st_ino
    expected_mtime_ns = getattr(st_genuine, "st_mtime_ns", int(st_genuine.st_mtime * 1e9))

    # Now replace anchor pathname with foreign file (different content, different inode)
    anchor_path.unlink()
    anchor_path.write_bytes(foreign_payload)

    # Public view also exists
    pub_path.write_bytes(genuine_payload)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor_path),
            active_attempt_generation=1,
            device=expected_dev,
            inode=expected_ino,
            size=expected_size,
            content_hash=expected_hash,
            mtime_ns=expected_mtime_ns,
        )
        session.add(entry)
        session.commit()

    # Execute transactional restore: MUST FAIL CLOSED
    with pytest.raises(Exception):
        execute_transactional_restore(
            session_factory,
            entry_id=1,
            worker_id="worker-1",
            allowed_roots=[allowed_root],
            quarantine_root=quarantine_root,
        )

    # 1. Original destination MUST NOT receive foreign payload
    assert not orig_path.exists(), "Original path must not receive foreign payload"

    # 2. Entry must transition to conflict / conflict
    with session_factory() as session:
        e = session.get(QuarantineEntry, 1)
        assert e.state == "conflict"
        assert e.tx_phase == "conflict"

    # 3. Foreign anchor file preserved in place
    assert anchor_path.exists()
    assert anchor_path.read_bytes() == foreign_payload


def test_reconciliation_rejects_replaced_authoritative_anchor(tmp_path, session_factory):
    """
    HOTFIX2 Item 4 Test B:
    Replace authoritative anchor pathname with foreign regular file before reconciliation publication
    → public quarantine path MUST NOT receive foreign payload
    → entry transitions to conflict / conflict
    → foreign anchor file preserved in place
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    orig_path = allowed_root / "data.txt"
    pub_path = quarantine_root / "data.txt"

    genuine_payload = b"GENUINE_RECONCILE_PAYLOAD"
    foreign_payload = b"FOREIGN_RECONCILE_PAYLOAD"

    tx_dir = quarantine_root / ".tx" / "entry-2" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = tx_dir / "anchor"

    anchor_path.write_bytes(genuine_payload)
    st_genuine = os.stat(anchor_path)
    expected_dev = st_genuine.st_dev
    expected_ino = st_genuine.st_ino
    expected_size = len(genuine_payload)
    expected_hash = hashlib.sha256(genuine_payload).hexdigest()
    expected_mtime_ns = getattr(st_genuine, "st_mtime_ns", int(st_genuine.st_mtime * 1e9))

    # Replace anchor with foreign file
    anchor_path.unlink()
    anchor_path.write_bytes(foreign_payload)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=2,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="authoritative_anchored",
            authoritative_anchor_path=str(anchor_path),
            active_attempt_generation=1,
            device=expected_dev,
            inode=expected_ino,
            size=expected_size,
            content_hash=expected_hash,
            mtime_ns=expected_mtime_ns,
        )
        session.add(entry)
        session.commit()

    # Reconcile: MUST FAIL CLOSED to conflict
    reconcile_quarantine_transaction(
        session_factory,
        2,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[allowed_root],
    )

    # 1. Public path MUST NOT receive foreign payload
    assert not pub_path.exists(), "Public path must not receive foreign payload"

    # 2. Entry must transition to conflict / conflict
    with session_factory() as session:
        e = session.get(QuarantineEntry, 2)
        assert e.state == "conflict"
        assert e.tx_phase == "conflict"

    # 3. Foreign anchor preserved in place
    assert anchor_path.exists()
    assert anchor_path.read_bytes() == foreign_payload
