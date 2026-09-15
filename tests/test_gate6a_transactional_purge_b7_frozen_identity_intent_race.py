from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow


def test_frozen_selected_identity_is_rechecked_inside_irreversible_intent_transaction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.quarantine.purge as purge

    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    attempt = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    frozen_payload = b"gate6a-b7-frozen-x"
    replacement_payload = b"gate6a-b7-replacement-y"

    anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = quarantine_root / "b7.q-1.bin"
    frozen_control = data / "frozen-x-control.bin"
    replacement_control = data / "replacement-y-control.bin"

    anchor.write_bytes(frozen_payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    os.link(anchor, frozen_control)
    frozen_st = anchor.stat(follow_symlinks=False)
    frozen_hash = hashlib.sha256(frozen_payload).hexdigest()

    replacement_control.write_bytes(replacement_payload)
    replacement_st = replacement_control.stat(follow_symlinks=False)
    replacement_hash = hashlib.sha256(replacement_payload).hexdigest()

    engine, SessionLocal = create_engine_and_session(tmp_path / "b7-intent-race.db")
    init_db(engine)
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path=str(data / "original.bin"),
                quarantine_path=str(public_view),
                state="active",
                tx_phase="active",
                authoritative_anchor_path=str(anchor),
                active_attempt_generation=1,
                device=frozen_st.st_dev,
                inode=frozen_st.st_ino,
                size=frozen_st.st_size,
                mtime_ns=frozen_st.st_mtime_ns,
                content_hash=frozen_hash,
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

    real_begin = purge._begin_transactional_purge_intent
    injected = False

    def begin_after_selected_identity_drift(session_factory, entry_id, worker_id, *args, **kwargs):
        nonlocal injected
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            entry = session.get(QuarantineEntry, entry_id)
            assert entry is not None
            entry.device = replacement_st.st_dev
            entry.inode = replacement_st.st_ino
            entry.size = replacement_st.st_size
            entry.mtime_ns = replacement_st.st_mtime_ns
            entry.content_hash = replacement_hash
            session.commit()

        for path in (anchor, captured_source, public_view):
            os.unlink(path)
            os.link(replacement_control, path)

        injected = True
        return real_begin(session_factory, entry_id, worker_id, *args, **kwargs)

    monkeypatch.setattr(purge, "_begin_transactional_purge_intent", begin_after_selected_identity_drift)

    with pytest.raises(Exception, match="PURGE_FROZEN_IDENTITY_CHANGED"):
        purge.execute_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )

    assert injected is True
    assert frozen_control.read_bytes() == frozen_payload
    assert replacement_control.read_bytes() == replacement_payload
    assert anchor.read_bytes() == replacement_payload
    assert captured_source.read_bytes() == replacement_payload
    assert public_view.read_bytes() == replacement_payload
    assert not (quarantine_root / ".tx" / "entry-1" / "attempt-2").exists()

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.purged_at is None
