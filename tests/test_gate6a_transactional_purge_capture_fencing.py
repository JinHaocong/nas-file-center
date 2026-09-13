from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow


def test_transactional_purge_capture_fences_each_rename_without_open_write_transaction(
    tmp_path: Path, monkeypatch
) -> None:
    import app.quarantine.purge as purge

    engine, SessionLocal = create_engine_and_session(tmp_path / "capture-fencing.db")
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-capture-fencing"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "fencing.q-1.bin"
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
                original_path=str(data / "fencing.bin"),
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

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        frozen_manifest = purge.build_purge_topology_manifest(
            entry,
            quarantine_root,
            owner_lookup=lambda _: None,
        )
        assert frozen_manifest["blockers"] == []

    original_renew = purge.renew_and_assert_worker_lease
    original_rename = os.rename
    events: list[str] = []

    def fenced_renew(session_factory, worker_id):
        result = original_renew(session_factory, worker_id)
        events.append("fence")
        return result

    def observed_rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        assert events and events[-1] == "fence"
        # A separate BEGIN IMMEDIATE must succeed here. If the capture path held
        # a SQLite write transaction across the filesystem syscall, this would lock.
        with SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            session.rollback()
        events.append("rename")
        return original_rename(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", fenced_renew)
    monkeypatch.setattr(purge.os, "rename", observed_rename)

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    assert events[-6:] == ["fence", "rename", "fence", "rename", "fence", "rename"]
