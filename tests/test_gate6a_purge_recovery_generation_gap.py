from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow


def _setup_entry(tmp_path: Path):
    engine, SessionLocal = create_engine_and_session(tmp_path / "b11-recovery.db")
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-b11-generation-recovery"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "b11.q-1.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    st = anchor.stat(follow_symlinks=False)

    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path=str(data / "b11.bin"),
                quarantine_path=str(public_view),
                state="active",
                tx_phase="active",
                authoritative_anchor_path=str(anchor),
                active_attempt_generation=1,
                device=st.st_dev,
                inode=st.st_ino,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                content_hash=hashlib.sha256(payload).hexdigest(),
            )
        )
        session.commit()

    return SessionLocal, data, quarantine_root, st


def _frozen_manifest(purge, SessionLocal, quarantine_root: Path):
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        manifest = purge.build_purge_topology_manifest(
            entry,
            quarantine_root,
            owner_lookup=lambda _: None,
            include_payload_identity=True,
        )
        assert manifest["blockers"] == []
        return manifest


def _assert_capture_slots(purge_dir: Path, expected_inode: int, expected_size: int) -> None:
    for name in ("current-anchor", "captured-source", "public-view"):
        path = purge_dir / name
        assert path.is_file()
        st = path.stat(follow_symlinks=False)
        assert st.st_ino == expected_inode
        assert st.st_size == expected_size


def test_recovery_resumes_attempt_directory_created_before_purge_subdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crash after mkdir(attempt-N) but before mkdir(attempt-N/purge) must be resumable."""
    import app.quarantine.purge as purge

    SessionLocal, data, quarantine_root, frozen_st = _setup_entry(tmp_path)
    manifest = _frozen_manifest(purge, SessionLocal, quarantine_root)
    attempt2 = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    purge2 = attempt2 / "purge"

    real_mkdir = os.mkdir
    crashed = False

    def crash_before_purge_subdir(path, mode=0o777, *, dir_fd=None):
        nonlocal crashed
        path_text = os.fspath(path)
        if not crashed and dir_fd is None and Path(path_text) == purge2:
            crashed = True
            raise RuntimeError("simulated crash after attempt mkdir before purge mkdir")
        if dir_fd is None:
            return real_mkdir(path_text, mode)
        return real_mkdir(path_text, mode, dir_fd=dir_fd)

    monkeypatch.setattr(purge.os, "mkdir", crash_before_purge_subdir)
    with pytest.raises(RuntimeError, match="after attempt mkdir"):
        purge.execute_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )
    monkeypatch.setattr(purge.os, "mkdir", real_mkdir)

    assert crashed is True
    assert attempt2.is_dir()
    assert not purge2.exists()
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert (entry.state, entry.tx_phase, entry.active_attempt_generation) == ("purging", "purging", 2)

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    assert purge2.is_dir()
    _assert_capture_slots(purge2, frozen_st.st_ino, frozen_st.st_size)
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.active_attempt_generation == 2
        assert (entry.state, entry.tx_phase) == ("purging", "purging")


def test_recovery_uses_current_durable_generation_after_repeated_pre_directory_crashes(
    tmp_path: Path,
) -> None:
    """Recovery must recreate the durable current generation, never advance it."""
    import app.quarantine.purge as purge

    SessionLocal, data, quarantine_root, frozen_st = _setup_entry(tmp_path)
    manifest = _frozen_manifest(purge, SessionLocal, quarantine_root)

    purge._begin_transactional_purge_intent(
        SessionLocal,
        1,
        "worker-1",
        manifest,
        quarantine_root,
    )

    # Model repeated legal allocation-before-mkdir crashes from older recovery behavior:
    # generation 2 was allocated and its empty attempt directory exists; generation 3
    # was then durably allocated but its attempt directory was never created. Recovery
    # must honor durable generation 3 rather than allocating generation 4.
    attempt2 = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    attempt2.mkdir(mode=0o700)
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        entry.active_attempt_generation = 3
        session.commit()

    attempt3 = quarantine_root / ".tx" / "entry-1" / "attempt-3"
    attempt4 = quarantine_root / ".tx" / "entry-1" / "attempt-4"
    assert not attempt3.exists()
    assert not attempt4.exists()

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge3 = attempt3 / "purge"
    assert purge3.is_dir()
    assert not attempt4.exists()
    _assert_capture_slots(purge3, frozen_st.st_ino, frozen_st.st_size)
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.active_attempt_generation == 3
        assert (entry.state, entry.tx_phase) == ("purging", "purging")
