from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.exceptions import StateConflictError
from app.models import QuarantineEntry, TaskLock, utcnow


def test_purge_recovery_preserves_unknown_private_object_and_fails_closed(tmp_path: Path) -> None:
    import app.quarantine.purge as purge

    engine, SessionLocal = create_engine_and_session(tmp_path / "foreign-recovery.db")
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-foreign-recovery"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "foreign-recovery.q-1.bin"
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
                original_path=str(data / "foreign-recovery.bin"),
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
            include_payload_identity=True,
        )
        assert frozen_manifest["blockers"] == []

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    expected_slots = {
        purge_dir / "current-anchor",
        purge_dir / "captured-source",
        purge_dir / "public-view",
    }
    assert all(path.exists() for path in expected_slots)

    foreign = purge_dir / "foreign-sentinel"
    foreign.write_bytes(b"unknown-object-must-survive")

    with pytest.raises(StateConflictError, match="UNKNOWN_PURGE_SLOT"):
        purge.destroy_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )

    assert foreign.read_bytes() == b"unknown-object-must-survive"
    assert all(path.exists() for path in expected_slots)
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.purged_at is None
