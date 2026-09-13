from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.exceptions import StateConflictError
from app.models import QuarantineEntry, TaskLock, utcnow


def _session_factory(tmp_path: Path):
    engine, SessionLocal = create_engine_and_session(tmp_path / "capture.db")
    init_db(engine)
    return SessionLocal


def _insert_entry(SessionLocal, *, state: str, tx_phase: str) -> None:
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path="/data/source.bin",
                quarantine_path="/trash/public.bin",
                state=state,
                tx_phase=tx_phase,
                active_attempt_generation=1,
            )
        )
        session.commit()


def test_transactional_purge_capture_requires_worker_authority(tmp_path: Path) -> None:
    from app.quarantine.purge import execute_transactional_purge_capture

    def unreachable_session_factory():
        raise AssertionError("capture must reject missing worker authority before DB access")

    with pytest.raises(PermissionError, match="worker authority"):
        execute_transactional_purge_capture(
            unreachable_session_factory,
            entry_id=1,
            worker_id=None,
            frozen_manifest={},
            quarantine_root=tmp_path / "trash",
            allowed_roots=[tmp_path],
        )


def test_purge_intent_rejects_restoring_entry_without_state_change(tmp_path: Path) -> None:
    from app.quarantine.purge import _begin_transactional_purge_intent

    SessionLocal = _session_factory(tmp_path)
    _insert_entry(SessionLocal, state="restoring", tx_phase="restoring")

    with pytest.raises(StateConflictError, match="active"):
        _begin_transactional_purge_intent(SessionLocal, 1, "worker-1")

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "restoring"
        assert entry.tx_phase == "restoring"
        assert entry.active_attempt_generation == 1


def test_purge_intent_commits_purging_before_capture_phase(tmp_path: Path) -> None:
    from app.quarantine.purge import _begin_transactional_purge_intent

    SessionLocal = _session_factory(tmp_path)
    _insert_entry(SessionLocal, state="active", tx_phase="active")

    _begin_transactional_purge_intent(SessionLocal, 1, "worker-1")

    # A separate session observes the state immediately, proving the short write
    # transaction was committed before any later filesystem capture phase begins.
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.active_attempt_generation == 1


def test_purge_capture_attempt_generation_is_monotonic_and_never_reuses_occupied_dir(tmp_path: Path) -> None:
    from app.quarantine.purge import _allocate_transactional_purge_attempt

    SessionLocal = _session_factory(tmp_path)
    quarantine_root = tmp_path / "trash"
    quarantine_root.mkdir()
    _insert_entry(SessionLocal, state="purging", tx_phase="purging")

    occupied_attempt = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    occupied_attempt.mkdir(parents=True)
    sentinel = occupied_attempt / "foreign-sentinel"
    sentinel.write_bytes(b"must-not-be-overwritten")

    generation, attempt_dir, purge_dir = _allocate_transactional_purge_attempt(
        SessionLocal,
        1,
        "worker-1",
        quarantine_root,
    )

    assert generation == 3
    assert attempt_dir == quarantine_root / ".tx" / "entry-1" / "attempt-3"
    assert purge_dir == attempt_dir / "purge"
    assert attempt_dir.is_dir()
    assert purge_dir.is_dir()
    assert sentinel.read_bytes() == b"must-not-be-overwritten"

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.active_attempt_generation == 3
