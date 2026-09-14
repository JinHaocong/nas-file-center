from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow


def _setup_purging_entry(tmp_path: Path, *, current_generation: int):
    engine, SessionLocal = create_engine_and_session(tmp_path / f"b11-{current_generation}.db")
    init_db(engine)
    data = tmp_path / f"data-{current_generation}"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = f"gate6a-b11-generation-{current_generation}".encode()
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "recovery.q-1.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    st = anchor.stat(follow_symlinks=False)
    digest = hashlib.sha256(payload).hexdigest()

    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path=str(data / "recovery.bin"),
                quarantine_path=str(public_view),
                state="purging",
                tx_phase="purging",
                authoritative_anchor_path=str(anchor),
                active_attempt_generation=current_generation,
                device=st.st_dev,
                inode=st.st_ino,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                content_hash=digest,
            )
        )
        session.commit()

    frozen_manifest = {
        "selected_entry_id": 1,
        "aliases": [
            {"role": "authoritative_anchor", "owner_entry_id": 1, "path": str(anchor)},
            {"role": "captured_source", "owner_entry_id": 1, "path": str(captured_source)},
            {"role": "public_view", "owner_entry_id": 1, "path": str(public_view)},
        ],
        "historical_conflict_entry_ids": [],
        "blocking_owner_entry_ids": [],
        "blockers": [],
        "frozen_payload_identity": {
            "device": st.st_dev,
            "inode": st.st_ino,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "content_hash": digest,
        },
    }
    return SessionLocal, data, quarantine_root, frozen_manifest


def _assert_capture_slots_exist(purge_dir: Path) -> None:
    assert purge_dir.is_dir()
    assert (purge_dir / "current-anchor").is_file()
    assert (purge_dir / "captured-source").is_file()
    assert (purge_dir / "public-view").is_file()


def test_recovery_resumes_when_attempt_dir_exists_but_purge_dir_was_not_created(tmp_path: Path) -> None:
    import app.quarantine.purge as purge

    SessionLocal, data, quarantine_root, frozen_manifest = _setup_purging_entry(
        tmp_path,
        current_generation=2,
    )
    attempt2 = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    attempt2.mkdir(parents=True)
    assert list(attempt2.iterdir()) == []

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    _assert_capture_slots_exist(attempt2 / "purge")
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.active_attempt_generation == 2


def test_recovery_reuses_durable_generation_after_repeated_allocation_only_crashes(tmp_path: Path) -> None:
    import app.quarantine.purge as purge

    SessionLocal, data, quarantine_root, frozen_manifest = _setup_purging_entry(
        tmp_path,
        current_generation=3,
    )
    attempt3 = quarantine_root / ".tx" / "entry-1" / "attempt-3"
    attempt4 = quarantine_root / ".tx" / "entry-1" / "attempt-4"
    assert not attempt3.exists()
    assert not attempt4.exists()

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.active_attempt_generation == 3
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
    _assert_capture_slots_exist(attempt3 / "purge")
    assert not attempt4.exists()
