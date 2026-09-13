from __future__ import annotations

import hashlib
import os
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


def test_transactional_purge_capture_moves_normal_alias_set_into_private_slots(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest, execute_transactional_purge_capture

    SessionLocal = _session_factory(tmp_path)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-normal-purge-capture"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "normal.q-1.bin"
    original = data / "normal.bin"
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
                original_path=str(original),
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
        frozen_manifest = build_purge_topology_manifest(
            entry,
            quarantine_root,
            owner_lookup=lambda _: None,
        )
        assert frozen_manifest["blockers"] == []

    execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    expected_slots = {
        "current-anchor": purge_dir / "current-anchor",
        "captured-source": purge_dir / "captured-source",
        "public-view": purge_dir / "public-view",
    }

    assert not anchor.exists()
    assert not captured_source.exists()
    assert not public_view.exists()
    assert {name: path.read_bytes() for name, path in expected_slots.items()} == {
        "current-anchor": payload,
        "captured-source": payload,
        "public-view": payload,
    }

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.active_attempt_generation == 2


def test_transactional_purge_capture_preserves_occupied_private_slot(tmp_path: Path, monkeypatch) -> None:
    import app.quarantine.purge as purge

    SessionLocal = _session_factory(tmp_path)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-occupied-slot-source"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "occupied.q-1.bin"
    original = data / "occupied.bin"
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
                original_path=str(original),
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

    original_allocate = purge._allocate_transactional_purge_attempt
    foreign_payload = b"foreign-private-slot-must-survive"
    occupied_slot: Path | None = None

    def allocate_then_occupy(*args, **kwargs):
        nonlocal occupied_slot
        result = original_allocate(*args, **kwargs)
        occupied_slot = result[2] / "current-anchor"
        occupied_slot.write_bytes(foreign_payload)
        return result

    monkeypatch.setattr(purge, "_allocate_transactional_purge_attempt", allocate_then_occupy)

    with pytest.raises(StateConflictError, match="occupied"):
        purge.execute_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )

    assert occupied_slot is not None
    assert occupied_slot.read_bytes() == foreign_payload
    assert anchor.read_bytes() == payload
    assert captured_source.read_bytes() == payload
    assert public_view.read_bytes() == payload

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.active_attempt_generation == 2


def test_transactional_purge_capture_retires_historical_conflict_candidate_into_linked_slot(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest, execute_transactional_purge_capture

    SessionLocal = _session_factory(tmp_path)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    selected_attempt = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    historical_attempt = quarantine_root / ".tx" / "entry-2" / "attempt-1"
    selected_attempt.mkdir(parents=True)
    historical_attempt.mkdir(parents=True)

    payload = b"gate6a-historical-purge-capture"
    anchor = selected_attempt / "anchor"
    captured_source = selected_attempt / "captured_source"
    public_view = quarantine_root / "selected.q-1.bin"
    historical_anchor = historical_attempt / "anchor"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    os.link(anchor, historical_anchor)
    st = anchor.stat(follow_symlinks=False)
    content_hash = hashlib.sha256(payload).hexdigest()

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
                content_hash=content_hash,
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
                content_hash=content_hash,
            )
        )
        session.commit()

    with SessionLocal() as session:
        selected = session.get(QuarantineEntry, 1)
        historical = session.get(QuarantineEntry, 2)
        assert selected is not None
        assert historical is not None
        frozen_manifest = build_purge_topology_manifest(
            selected,
            quarantine_root,
            owner_lookup=lambda owner_id: historical if owner_id == 2 else None,
        )
        assert frozen_manifest["blockers"] == []
        assert frozen_manifest["historical_conflict_entry_ids"] == [2]

    execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    linked_slot = purge_dir / "linked-conflict-2-anchor"
    assert linked_slot.read_bytes() == payload
    assert not historical_anchor.exists()

    with SessionLocal() as session:
        selected = session.get(QuarantineEntry, 1)
        historical = session.get(QuarantineEntry, 2)
        assert selected is not None
        assert historical is not None
        assert selected.state == "purging"
        assert selected.tx_phase == "purging"
        assert selected.active_attempt_generation == 2
        assert historical.state == "conflict"
        assert historical.tx_phase == "conflict"
        assert historical.authoritative_anchor_path is None
