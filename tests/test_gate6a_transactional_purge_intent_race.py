from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.exceptions import StateConflictError
from app.models import QuarantineEntry, TaskLock, utcnow


def test_owner_change_between_execute_revalidation_and_purge_intent_is_blocked_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.quarantine.purge as purge

    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    selected_attempt = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    historical_attempt = quarantine_root / ".tx" / "entry-2" / "attempt-1"
    selected_attempt.mkdir(parents=True)
    historical_attempt.mkdir(parents=True)

    payload = b"gate6a-owner-change-at-intent-boundary"
    anchor = selected_attempt / "anchor"
    captured_source = selected_attempt / "captured_source"
    public_view = quarantine_root / "selected.q-1.bin"
    historical_anchor = historical_attempt / "anchor"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    os.link(anchor, historical_anchor)
    st = anchor.stat(follow_symlinks=False)
    digest = hashlib.sha256(payload).hexdigest()

    engine, SessionLocal = create_engine_and_session(tmp_path / "intent-owner-race.db")
    init_db(engine)
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path=str(data / "selected.bin"),
                quarantine_path=str(public_view),
                state="active",
                tx_phase="active",
                authoritative_anchor_path=str(anchor),
                active_attempt_generation=1,
                device=st.st_dev,
                inode=st.st_ino,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                content_hash=digest,
            )
        )
        session.add(
            QuarantineEntry(
                id=2,
                original_path=str(data / "historical.bin"),
                quarantine_path=str(quarantine_root / "historical.q-2.bin"),
                state="conflict",
                tx_phase="conflict",
                authoritative_anchor_path=None,
                active_attempt_generation=1,
                device=st.st_dev,
                inode=st.st_ino,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                content_hash=digest,
            )
        )
        session.commit()

    with SessionLocal() as session:
        selected = session.get(QuarantineEntry, 1)
        historical = session.get(QuarantineEntry, 2)
        assert selected is not None
        assert historical is not None
        frozen_manifest = purge.build_purge_topology_manifest(
            selected,
            quarantine_root,
            owner_lookup=lambda owner_id: historical if owner_id == 2 else None,
            include_payload_identity=True,
        )
        assert frozen_manifest["blockers"] == []
        assert frozen_manifest["historical_conflict_entry_ids"] == [2]

    real_begin = purge._begin_transactional_purge_intent
    injected = False

    def begin_after_owner_becomes_active(session_factory, entry_id, worker_id, *args, **kwargs):
        nonlocal injected
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            owner = session.get(QuarantineEntry, 2)
            assert owner is not None
            owner.state = "active"
            owner.tx_phase = "active"
            session.commit()
        injected = True
        return real_begin(session_factory, entry_id, worker_id, *args, **kwargs)

    monkeypatch.setattr(purge, "_begin_transactional_purge_intent", begin_after_owner_becomes_active)

    with pytest.raises(StateConflictError, match="SHARED_ACTIVE_PAYLOAD"):
        purge.execute_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )

    assert injected is True
    assert anchor.read_bytes() == payload
    assert captured_source.read_bytes() == payload
    assert public_view.read_bytes() == payload
    assert historical_anchor.read_bytes() == payload

    with SessionLocal() as session:
        selected = session.get(QuarantineEntry, 1)
        owner = session.get(QuarantineEntry, 2)
        assert selected is not None
        assert owner is not None
        assert selected.state == "active"
        assert selected.tx_phase == "active"
        assert selected.active_attempt_generation == 1
        assert owner.state == "active"
        assert owner.tx_phase == "active"
