from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.exceptions import StateConflictError
from app.models import QuarantineEntry, TaskLock, utcnow


def test_qualified_capture_is_zeroized_before_terminal_purged_commit(tmp_path: Path) -> None:
    import app.quarantine.purge as purge

    engine, SessionLocal = create_engine_and_session(tmp_path / "destroy.db")
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-qualified-destroy"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "destroy.q-1.bin"
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
                original_path=str(data / "destroy.bin"),
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
    known_slots = [
        purge_dir / "current-anchor",
        purge_dir / "captured-source",
        purge_dir / "public-view",
    ]
    assert all(path.exists() for path in known_slots)

    purge.destroy_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    # Gate6-A COMPAT destruction is descriptor-bound zeroization, not pathname
    # unlink. The exact private leaves remain as durable same-transaction
    # tombstone evidence and all NFC-owned aliases of the inode read as empty.
    assert all(path.exists() for path in known_slots)
    assert all(path.stat(follow_symlinks=False).st_ino == st.st_ino for path in known_slots)
    assert all(path.stat(follow_symlinks=False).st_size == 0 for path in known_slots)
    assert (purge_dir / "destroy-intent.json").is_file()
    assert anchor.stat(follow_symlinks=False).st_size == 0
    assert captured_source.stat(follow_symlinks=False).st_size == 0
    assert public_view.stat(follow_symlinks=False).st_size == 0

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None


def test_destroy_preserves_foreign_replacement_after_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A captured pathname replaced after qualification must never be unlinked blindly."""
    import app.quarantine.purge as purge

    engine, SessionLocal = create_engine_and_session(tmp_path / "destroy-race.db")
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-qualified-destroy-race"
    foreign_payload = b"foreign-object-must-survive"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "destroy-race.q-1.bin"
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
                original_path=str(data / "destroy-race.bin"),
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
    victim = purge_dir / "public-view"
    original_qualify = purge.qualify_transactional_purge_capture

    def qualify_then_replace(*args: object, **kwargs: object) -> list[Path]:
        qualified = original_qualify(*args, **kwargs)
        os.unlink(victim)
        victim.write_bytes(foreign_payload)
        return qualified

    monkeypatch.setattr(purge, "qualify_transactional_purge_capture", qualify_then_replace)

    with pytest.raises(StateConflictError, match="PURGE_DESTRUCTION_FAILED"):
        purge.destroy_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )

    assert victim.exists()
    assert victim.read_bytes() == foreign_payload
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.purged_at is None
