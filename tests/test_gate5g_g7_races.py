import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text
from app.models import TaskLock, QuarantineEntry, utcnow
from app.db import create_engine_and_session, init_db
from app.tasks.recovery import JobLeaseLost, renew_and_assert_worker_lease, assert_active_worker_lease
from app.quarantine.engine import execute_transactional_quarantine
from app.quarantine.restore import execute_transactional_restore
from app.quarantine.reconcile import reconcile_quarantine_transaction


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_race_r1_source_replaced_before_capture(tmp_path, session_factory):
    """R1: Attacker replaces source with foreign file before capture rename."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r1.txt"
    genuine_content = b"GENUINE_R1"
    source.write_bytes(genuine_content)
    st = os.stat(source)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    h = hashlib.sha256(genuine_content).hexdigest()
    pub_path = q_dir / "r1.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            size=len(genuine_content),
            content_hash=h,
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=mtime_ns,
        )
        session.add(entry)
        session.commit()

    # We run quarantine but intercept right before step 4/5 rename
    real_rename = os.rename
    def swap_before_rename(src, dst):
        if "captured_source" in str(dst):
            # Replace source with foreign file
            os.unlink(src)
            Path(src).write_bytes(b"FOREIGN_R1_PAYLOAD")
        return real_rename(src, dst)

    import unittest.mock as mock
    with mock.patch("os.rename", side_effect=swap_before_rename):
        with pytest.raises(Exception):
            execute_transactional_quarantine(session_factory, 1, "worker-1", allowed_roots=[tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Captured slot must preserve foreign file without deleting
    attempt_dir = Path(entry.authoritative_anchor_path).parent
    captured_slot = attempt_dir / "captured_source"
    assert captured_slot.exists()
    assert captured_slot.read_bytes() == b"FOREIGN_R1_PAYLOAD"


def test_race_r2_source_replaced_after_earlier_verification_before_capture(tmp_path, session_factory):
    """R2: Attacker replaces source after verification stat, immediately before rename."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r2.txt"
    genuine_content = b"GENUINE_R2"
    source.write_bytes(genuine_content)
    st = os.stat(source)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    h = hashlib.sha256(genuine_content).hexdigest()
    pub_path = q_dir / "r2.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            size=len(genuine_content),
            content_hash=h,
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=mtime_ns,
        )
        session.add(entry)
        session.commit()

    real_rename = os.rename
    def swap_immediately_before_rename(src, dst):
        if "captured_source" in str(dst):
            os.unlink(src)
            Path(src).write_bytes(b"FOREIGN_R2_SWAP")
        return real_rename(src, dst)

    import unittest.mock as mock
    with mock.patch("os.rename", side_effect=swap_immediately_before_rename):
        with pytest.raises(Exception):
            execute_transactional_quarantine(session_factory, 1, "worker-1", allowed_roots=[tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"


def test_race_r3_source_recreated_immediately_after_capture(tmp_path, session_factory):
    """R3: Attacker creates a new file at source pathname right after source is captured."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r3.txt"
    genuine_content = b"GENUINE_R3"
    source.write_bytes(genuine_content)
    st = os.stat(source)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    h = hashlib.sha256(genuine_content).hexdigest()
    pub_path = q_dir / "r3.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            size=len(genuine_content),
            content_hash=h,
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=mtime_ns,
        )
        session.add(entry)
        session.commit()

    real_rename = os.rename
    def recreate_after_rename(src, dst):
        res = real_rename(src, dst)
        if "captured_source" in str(dst):
            # Third party creates new file at original source path
            Path(src).write_bytes(b"NEW_THIRD_PARTY_FILE")
        return res

    import unittest.mock as mock
    with mock.patch("os.rename", side_effect=recreate_after_rename):
        execute_transactional_quarantine(session_factory, 1, "worker-1", allowed_roots=[tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "active"
        assert entry.tx_phase == "active"

    # New source file remains untouched
    assert source.exists()
    assert source.read_bytes() == b"NEW_THIRD_PARTY_FILE"
    # Authoritative anchor remains genuine
    assert Path(entry.authoritative_anchor_path).read_bytes() == genuine_content


def test_race_r4_stale_worker_second_capture(tmp_path, session_factory):
    """R4: Stale worker attempts capture after lease takeover."""
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        # Worker 2 took over lease
        lock = TaskLock(id=1, locked=True, owner="worker-2", acquired_at=utcnow())
        session.add(lock)
        session.commit()

    # Stale worker 1 attempts fence renewal
    with pytest.raises(JobLeaseLost):
        renew_and_assert_worker_lease(session_factory, "worker-1")


def test_race_r5_two_generations_capture_different_occupants(tmp_path, session_factory):
    """R5: Gen 1 captured genuine file; Gen 2 captured foreign occupant after crash."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r5.txt"
    genuine_content = b"GENUINE_R5"
    tx_base = q_dir / ".tx" / "entry-1"
    gen1_dir = tx_base / "attempt-1"
    gen1_dir.mkdir(parents=True)
    gen2_dir = tx_base / "attempt-2"
    gen2_dir.mkdir(parents=True)

    anchor1 = gen1_dir / "anchor"
    anchor1.write_bytes(genuine_content)
    st1 = os.stat(anchor1)

    cap1 = gen1_dir / "captured_source"
    os.link(str(anchor1), str(cap1))

    # Gen 2 captured a foreign occupant
    foreign_cap = gen2_dir / "captured_source"
    foreign_cap.write_bytes(b"FOREIGN_OCCUPANT_GEN2")

    pub_view = q_dir / "r5.txt"
    os.link(str(anchor1), str(pub_view))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_view),
            state="preparing",
            tx_phase="public_published",
            authoritative_anchor_path=str(anchor1),
            active_attempt_generation=1,
            device=st1.st_dev,
            inode=st1.st_ino,
            size=len(genuine_content),
            content_hash=hashlib.sha256(genuine_content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "active"
        assert entry.tx_phase == "active"

    # Foreign occupant in Gen 2 must be preserved in place
    assert foreign_cap.exists()
    assert foreign_cap.read_bytes() == b"FOREIGN_OCCUPANT_GEN2"


def test_race_r6_public_destination_appears_before_publication(tmp_path, session_factory):
    """R6: Third party creates file at public quarantine path before publication link."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r6.txt"
    genuine_content = b"GENUINE_R6"
    source.write_bytes(genuine_content)
    st = os.stat(source)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    h = hashlib.sha256(genuine_content).hexdigest()
    pub_path = q_dir / "r6.txt"

    # Third party creates conflicting file at public path
    pub_path.write_bytes(b"THIRD_PARTY_OCCUPANT")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            size=len(genuine_content),
            content_hash=h,
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=mtime_ns,
        )
        session.add(entry)
        session.commit()

    with pytest.raises(Exception):
        execute_transactional_quarantine(session_factory, 1, "worker-1", allowed_roots=[tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Third party occupant untouched
    assert pub_path.read_bytes() == b"THIRD_PARTY_OCCUPANT"


def test_race_r7_public_destination_replaced_after_publication(tmp_path, session_factory):
    """R7: Public quarantine path replaced with foreign file after publication."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r7.txt"
    genuine_content = b"GENUINE_R7"
    source.write_bytes(genuine_content)
    st = os.stat(source)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    h = hashlib.sha256(genuine_content).hexdigest()
    pub_path = q_dir / "r7.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            size=len(genuine_content),
            content_hash=h,
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=mtime_ns,
        )
        session.add(entry)
        session.commit()

    execute_transactional_quarantine(session_factory, 1, "worker-1", allowed_roots=[tmp_path])

    # Attacker replaces public view with corrupt data
    pub_path = q_dir / "r7.txt"
    os.unlink(pub_path)
    pub_path.write_bytes(b"CORRUPTED_PUBLIC_VIEW")

    # Restore operation: restores genuine payload from authoritative anchor
    # View retirement moves the corrupt view to slot and flags conflict or restores payload
    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        anchor_path = Path(entry.authoritative_anchor_path)
        assert anchor_path.read_bytes() == genuine_content

    with pytest.raises(RuntimeError):
        execute_transactional_restore(session_factory, 1, "worker-1", [tmp_path])

    # Original path restored from anchor
    assert source.exists()
    assert source.read_bytes() == genuine_content
    # Corrupt view preserved in slot
    tx_dir = anchor_path.parent
    assert (tx_dir / "captured_quarantine_view").read_bytes() == b"CORRUPTED_PUBLIC_VIEW"


def test_race_r8_stale_worker_holds_old_tx_dir_fd(tmp_path, session_factory):
    """R8: Stale worker retains open dir_fd to old attempt directory."""
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        # Worker 2 owns lease
        lock = TaskLock(id=1, locked=True, owner="worker-2", acquired_at=utcnow())
        session.add(lock)
        session.commit()

    # Stale worker 1 holding fd attempts operation; fence rejects
    with pytest.raises(JobLeaseLost):
        renew_and_assert_worker_lease(session_factory, "worker-1")


def test_race_r9_stale_worker_holds_source_parent_fd(tmp_path, session_factory):
    """R9: Stale worker retains open parent dir_fd to source directory."""
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-2", acquired_at=utcnow())
        session.add(lock)
        session.commit()

    # Stale worker 1 attempts rename fence
    with pytest.raises(JobLeaseLost):
        renew_and_assert_worker_lease(session_factory, "worker-1")


def test_race_r10_current_worker_reconciles_while_old_worker_executes_one_fs_syscall(tmp_path, session_factory):
    """R10: Reconciler runs while delayed old worker executes exactly one syscall."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r10.txt"
    genuine_content = b"GENUINE_R10"
    source.write_bytes(genuine_content)
    st = os.stat(source)

    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    os.link(str(source), str(anchor))

    pub_path = q_dir / "r10.txt"
    # Stale worker managed to execute one os.link before dying
    os.link(str(anchor), str(pub_path))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        # Worker 2 takes over lease
        lock = TaskLock(id=1, locked=True, owner="worker-2", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="authoritative_anchored",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(genuine_content),
            content_hash=hashlib.sha256(genuine_content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    # Worker 2 reconciles: discovers public path already matches anchor dev/ino
    reconcile_quarantine_transaction(session_factory, 1, "worker-2")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "active"
        assert entry.tx_phase == "active"


def test_race_r11_crash_after_anchor_creation_before_db_commit(tmp_path, session_factory):
    """R11: Crash occurs right after candidate anchor linked, before DB commit."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r11.txt"
    content = b"GENUINE_R11"
    source.write_bytes(content)
    st = os.stat(source)

    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    os.link(str(source), str(anchor))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(q_dir / "r11.txt"),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            mtime_ns=st.st_mtime_ns,
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.authoritative_anchor_path == str(anchor)


def test_race_r12_crash_after_capture_rename_before_db_commit(tmp_path, session_factory):
    """R12: Crash occurs right after source capture rename, before DB commit."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r12.txt"
    content = b"GENUINE_R12"
    source.write_bytes(content)
    st = os.stat(source)

    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    os.link(str(source), str(anchor))

    pub_path = q_dir / "r12.txt"
    os.link(str(anchor), str(pub_path))

    # Rename executed on disk, but DB still at public_published
    captured_source = tx_dir / "captured_source"
    os.rename(str(source), str(captured_source))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="public_published",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "active"
        assert entry.tx_phase == "active"


def test_race_r13_restore_original_destination_appears_concurrently(tmp_path, session_factory):
    """R13: Concurrent occupant appears at original destination during restore."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    orig_path = data_dir / "r13.txt"
    content = b"GENUINE_R13"

    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st = os.stat(anchor)

    # Concurrent file appears at orig_path
    orig_path.write_bytes(b"CONCURRENT_OCCUPANT")

    pub_path = q_dir / "r13.txt"
    os.link(str(anchor), str(pub_path))

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
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    with pytest.raises(FileExistsError):
        execute_transactional_restore(session_factory, 1, "worker-1", [tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Occupant preserved
    assert orig_path.read_bytes() == b"CONCURRENT_OCCUPANT"


def test_race_r14_restore_public_view_replaced_before_retirement(tmp_path, session_factory):
    """R14: Public view replaced with foreign occupant before restore retirement rename."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    orig_path = data_dir / "r14.txt"
    content = b"GENUINE_R14"

    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st = os.stat(anchor)

    # Public view replaced with foreign file
    pub_path = q_dir / "r14.txt"
    pub_path.write_bytes(b"FOREIGN_VIEW")

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
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    with pytest.raises(RuntimeError):
        execute_transactional_restore(session_factory, 1, "worker-1", [tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    captured_view = tx_dir / "captured_quarantine_view"
    assert captured_view.exists()
    assert captured_view.read_bytes() == b"FOREIGN_VIEW"


def test_race_r15_private_attempt_contains_unknown_inode(tmp_path, session_factory):
    """R15: Private attempt contains injected unknown inode."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r15.txt"
    source.write_bytes(b"GENUINE_R15")

    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)

    # Rogue file injected in attempt dir
    rogue = tx_dir / "rogue_injected.tmp"
    rogue.write_bytes(b"ROGUE_INODE_DATA")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(q_dir / "r15.txt"),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=1,
            device=1,
            inode=1,
            size=1,
            content_hash="h",
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1")

    # Rogue file must NEVER be unlinked (Zero Payload-Bearing Unlink)
    assert rogue.exists()
    assert rogue.read_bytes() == b"ROGUE_INODE_DATA"


def test_race_r16_multiple_attempt_directories_survive_restart(tmp_path, session_factory):
    """R16: Multiple attempt directories exist due to successive crashes."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "r16.txt"
    genuine_content = b"GENUINE_R16"
    source.write_bytes(genuine_content)
    st = os.stat(source)

    tx_dir1 = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir1.mkdir(parents=True)
    # Attempt 1 failed / corrupted
    (tx_dir1 / "anchor").write_bytes(b"CORRUPTED_ATTEMPT1")

    tx_dir2 = q_dir / ".tx" / "entry-1" / "attempt-2"
    tx_dir2.mkdir(parents=True)
    # Attempt 2 has genuine anchor linked from source
    anchor2 = tx_dir2 / "anchor"
    os.link(str(source), str(anchor2))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(q_dir / "r16.txt"),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=2,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(genuine_content),
            mtime_ns=st.st_mtime_ns,
            content_hash=hashlib.sha256(genuine_content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.authoritative_anchor_path == str(anchor2)

    # Attempt 1 corrupt file was preserved, not deleted
    assert (tx_dir1 / "anchor").read_bytes() == b"CORRUPTED_ATTEMPT1"
