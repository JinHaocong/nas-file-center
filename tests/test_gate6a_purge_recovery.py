from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow
from app.tasks.state_machine import JobLeaseLost


def _setup_recovery_entry(tmp_path: Path, payload: bytes, db_name: str):
    engine, SessionLocal = create_engine_and_session(tmp_path / db_name)
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "recovery.q-1.bin"
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
                original_path=str(data / "recovery.bin"),
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

    return SessionLocal, data, quarantine_root, anchor, captured_source, public_view


def _frozen_manifest(purge, SessionLocal, quarantine_root: Path):
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        manifest = purge.build_purge_topology_manifest(
            entry,
            quarantine_root,
            owner_lookup=lambda _: None,
        )
        assert manifest["blockers"] == []
        return manifest


def _private_slots(purge_dir: Path) -> list[Path]:
    return [
        purge_dir / "current-anchor",
        purge_dir / "captured-source",
        purge_dir / "public-view",
    ]


def _assert_original_payload(paths: list[Path], expected_size: int) -> None:
    assert all(path.exists() for path in paths)
    assert all(path.stat(follow_symlinks=False).st_size == expected_size for path in paths)


def _assert_zero_tombstones(paths: list[Path], expected_inode: int) -> None:
    assert all(path.exists() for path in paths)
    assert all(path.stat(follow_symlinks=False).st_ino == expected_inode for path in paths)
    assert all(path.stat(follow_symlinks=False).st_size == 0 for path in paths)


def test_transactional_purge_resumes_after_marker_before_descriptor_zeroization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A durable marker with untouched captures resumes; absence is never treated as proof."""
    import app.quarantine.purge as purge

    payload = b"gate6a-marker-before-zeroization-recovery"
    SessionLocal, data, quarantine_root, anchor, captured_source, public_view = _setup_recovery_entry(
        tmp_path,
        payload,
        "recovery.db",
    )
    frozen_manifest = _frozen_manifest(purge, SessionLocal, quarantine_root)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        expected_inode = int(entry.inode)

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    slots = _private_slots(purge_dir)
    source_aliases = [anchor, captured_source, public_view]
    _assert_original_payload(slots + source_aliases, len(payload))
    assert not (purge_dir / "destroy-intent.json").exists()

    original_renew = purge.renew_and_assert_worker_lease
    fence_calls = 0

    def crash_at_zeroization_fence(*args, **kwargs):
        nonlocal fence_calls
        fence_calls += 1
        result = original_renew(*args, **kwargs)
        if fence_calls == 2:
            raise RuntimeError("simulated crash before descriptor zeroization")
        return result

    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", crash_at_zeroization_fence)
    with pytest.raises(RuntimeError, match="before descriptor zeroization"):
        purge.destroy_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )
    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", original_renew)

    assert (purge_dir / "destroy-intent.json").is_file()
    _assert_original_payload(slots + source_aliases, len(payload))
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.purged_at is None
        assert entry.active_attempt_generation == 2

    purge.destroy_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    assert (purge_dir / "destroy-intent.json").is_file()
    _assert_zero_tombstones(slots + source_aliases, expected_inode)
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
        assert entry.active_attempt_generation == 2


def test_transactional_purge_resumes_after_zeroization_before_terminal_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Marker + complete zero tombstones prove success without a second destructive syscall."""
    import app.quarantine.purge as purge

    payload = b"gate6a-terminal-commit-recovery"
    SessionLocal, data, quarantine_root, anchor, captured_source, public_view = _setup_recovery_entry(
        tmp_path,
        payload,
        "terminal-recovery.db",
    )
    frozen_manifest = _frozen_manifest(purge, SessionLocal, quarantine_root)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        expected_inode = int(entry.inode)

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    slots = _private_slots(purge_dir)
    source_aliases = [anchor, captured_source, public_view]
    original_assert = purge.assert_active_worker_lease
    assert_calls = 0

    def crash_before_terminal_commit(*args, **kwargs):
        nonlocal assert_calls
        assert_calls += 1
        result = original_assert(*args, **kwargs)
        if assert_calls == 3:
            raise RuntimeError("simulated crash before terminal purge commit")
        return result

    monkeypatch.setattr(purge, "assert_active_worker_lease", crash_before_terminal_commit)
    with pytest.raises(RuntimeError, match="terminal purge commit"):
        purge.destroy_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )
    monkeypatch.setattr(purge, "assert_active_worker_lease", original_assert)

    assert (purge_dir / "destroy-intent.json").is_file()
    _assert_zero_tombstones(slots + source_aliases, expected_inode)
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.purged_at is None
        assert entry.active_attempt_generation == 2

    def destructive_retry_is_forbidden(*args, **kwargs):
        raise AssertionError("recovery must not ftruncate an already-zeroized transaction")

    monkeypatch.setattr(purge.os, "ftruncate", destructive_retry_is_forbidden)
    purge.destroy_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    _assert_zero_tombstones(slots + source_aliases, expected_inode)
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
        assert entry.active_attempt_generation == 2


def test_stale_worker_is_rejected_before_descriptor_zeroization_and_new_worker_resumes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Lease takeover at the destructive fence leaves payload intact for the new owner."""
    import app.quarantine.purge as purge

    payload = b"gate6a-worker-takeover-recovery"
    SessionLocal, data, quarantine_root, anchor, captured_source, public_view = _setup_recovery_entry(
        tmp_path,
        payload,
        "takeover-recovery.db",
    )
    frozen_manifest = _frozen_manifest(purge, SessionLocal, quarantine_root)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        expected_inode = int(entry.inode)

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )
    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    slots = _private_slots(purge_dir)
    source_aliases = [anchor, captured_source, public_view]
    _assert_original_payload(slots + source_aliases, len(payload))

    original_renew = purge.renew_and_assert_worker_lease
    fence_calls = 0

    def takeover_at_zeroization_fence(session_factory, worker_id, *args, **kwargs):
        nonlocal fence_calls
        fence_calls += 1
        if fence_calls == 2:
            with SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                lock = session.get(TaskLock, 1)
                assert lock is not None
                lock.owner = "worker-2"
                lock.acquired_at = utcnow()
                session.commit()
        return original_renew(session_factory, worker_id, *args, **kwargs)

    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", takeover_at_zeroization_fence)
    with pytest.raises(JobLeaseLost, match="lost exclusive lease"):
        purge.destroy_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )
    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", original_renew)

    assert (purge_dir / "destroy-intent.json").is_file()
    _assert_original_payload(slots + source_aliases, len(payload))
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.purged_at is None

    purge.destroy_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-2",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    _assert_zero_tombstones(slots + source_aliases, expected_inode)
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
        assert entry.active_attempt_generation == 2
