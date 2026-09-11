import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text

from app.models import QuarantineEntry, utcnow, TaskLock
from app.db import create_engine_and_session, init_db
from app.quarantine.engine import execute_transactional_quarantine
from app.quarantine.reconcile import reconcile_quarantine_transaction


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_engine_candidate_qualification_does_not_reopen_absolute_path(tmp_path, session_factory, monkeypatch):
    """
    HOTFIX2 Item 3:
    Candidate qualification must open the candidate through the already validated
    attempt parent dir_fd (or reacquire with safe descriptor traversal):
    os.open(candidate_leaf, ..., dir_fd=attempt_dfd)
    qualify_candidate_anchor_fd(fd, ...)
    NO absolute pathname reopen (os.open(str(candidate_path), ...)).
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    source = allowed_root / "test.txt"
    payload = b"GENUINE_QUALIFICATION_PAYLOAD"
    source.write_bytes(payload)
    st = os.stat(source)

    pub_path = quarantine_root / "test.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    real_os_open = os.open
    opened_paths: list[tuple[str, int | None]] = []

    def tracking_open(path, flags, *args, dir_fd=None, **kwargs):
        opened_paths.append((str(path), dir_fd))
        return real_os_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(os, "open", tracking_open)

    execute_transactional_quarantine(
        session_factory,
        entry_id=1,
        worker_id="worker-1",
        allowed_roots=[allowed_root],
        quarantine_root=quarantine_root,
    )

    # Check that candidate anchor "anchor" was opened with a non-None dir_fd,
    # NOT opened via its absolute path string "/.../anchor" without dir_fd!
    candidate_absolute_opens = [
        p for p, dfd in opened_paths
        if "anchor" in p and os.path.isabs(p) and dfd is None
    ]
    assert len(candidate_absolute_opens) == 0, f"Candidate anchor was reopened by absolute path: {candidate_absolute_opens}"


def test_reconciliation_ancestor_symlink_retarget_fails_closed(tmp_path, session_factory):
    """
    HOTFIX2 Item 2:
    Reconciler must be descriptor-relative via safe_open_parent_fd.
    If an ancestor directory in the quarantine path is retargeted / replaced
    with a symlink pointing outside allowed roots, reconciliation must fail closed.
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    outside_dir = tmp_path / "outside_attacker"
    outside_dir.mkdir(parents=True, exist_ok=True)
    sensitive_file = outside_dir / "sensitive.txt"
    sensitive_file.write_bytes(b"SENSITIVE")

    source = allowed_root / "test_recon.txt"
    source.write_bytes(b"DATA")
    st = os.stat(source)

    # Legitimate subfolder
    sub_folder = quarantine_root / "subfolder"
    sub_folder.mkdir(parents=True, exist_ok=True)
    pub_path = sub_folder / "pub.txt"

    tx_dir = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = tx_dir / "anchor"
    anchor_path.write_bytes(b"DATA")
    st_anchor = os.stat(anchor_path)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="authoritative_anchored",
            authoritative_anchor_path=str(anchor_path),
            active_attempt_generation=1,
            device=st_anchor.st_dev,
            inode=st_anchor.st_ino,
            size=len(b"DATA"),
            content_hash=hashlib.sha256(b"DATA").hexdigest(),
        )
        session.add(entry)
        session.commit()

    # Attacker swaps subfolder for a symlink pointing outside allowed roots!
    sub_folder.rmdir()
    os.symlink(str(outside_dir), str(sub_folder))

    # Reconciler attempting to link anchor to pub_path must encounter
    # ancestor symlink escape and fail closed (state -> conflict)
    reconcile_quarantine_transaction(
        session_factory,
        1,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[allowed_root],
    )

    # Must NOT link into outside_attacker!
    assert not (outside_dir / "pub.txt").exists()

    with session_factory() as session:
        e = session.get(QuarantineEntry, 1)
        assert e.state == "conflict"
        assert e.tx_phase == "conflict"
