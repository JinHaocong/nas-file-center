import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow
from app.quarantine.engine import execute_transactional_quarantine


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_ancestor_symlink_retarget_fails_closed_in_quarantine(tmp_path, session_factory):
    """
    HOTFIX1 Requirement 7:
    Transaction operations must use safe parent dir_fd traversal (safe_open_parent_fd).
    Candidate link, public view link, and source capture must use descriptor-relative operations.
    If an ancestor directory is retargeted via symlink, safe_open_parent_fd must reject
    it with ValueError before any link/rename is issued.
    """
    data_dir = tmp_path / "data"
    sub_dir = data_dir / "subdir"
    sub_dir.mkdir(parents=True)
    src_file = sub_dir / "target.txt"
    payload = b"PAYLOAD_ANCESTOR_TEST"
    src_file.write_bytes(payload)
    st = os.stat(src_file)

    q_root = tmp_path / "quarantine"
    q_root.mkdir()
    pub_path = q_root / "entry1.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(src_file),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=0,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    # Retarget subdir to an outside directory via symlink, but with matching payload and inode!
    outside_dir = tmp_path / "outside_attacker"
    outside_dir.mkdir()
    outside_target = outside_dir / "target.txt"
    # Hardlink the genuine file to outside_target so dev/ino/hash are identical
    os.link(str(src_file), str(outside_target))

    src_file.unlink()
    sub_dir.rmdir()
    os.symlink(str(outside_dir), str(sub_dir))

    # Without descriptor-relative safe traversal, pathname open would follow the symlink
    # and succeed. With safe parent traversal, it MUST raise ValueError due to symlink ancestor.
    with pytest.raises(ValueError, match="symlink|outside"):
        execute_transactional_quarantine(
            session_factory,
            1,
            worker_id="worker-1",
            allowed_roots=[data_dir, q_root],
        )
