from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason='Gate6-A v0.3.6 COMPAT permanent purge release path is deferred after B10; dormant purge-core safety is covered by direct transactional/recovery tests')

import hashlib
import os
from pathlib import Path

from sqlalchemy import text

from app.batch.plans import OperationItem
from app.db import create_engine_and_session, init_db
from app.execution.executor import execute_item
from app.models import QuarantineEntry, TaskLock, utcnow
from app.quarantine.purge import build_purge_topology_manifest


def test_quarantine_purge_executor_rejects_missing_worker_authority(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    quarantine_root.mkdir()
    source = quarantine_root / "entry.q-1.bin"
    source.write_bytes(b"gate6a-purge-executor")

    result = execute_item(
        OperationItem(sequence=1, operation="quarantine_purge", source=source),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge",
    )

    assert result.state == "failed"
    assert "worker authority" in result.reason.lower()
    assert source.exists()


def test_quarantine_purge_executor_routes_authorized_transaction_to_terminal_purge(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    attempt = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    payload = b"gate6a-purge-executor-authorized"
    anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = quarantine_root / "entry.q-1.bin"
    original = data / "original.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    st = anchor.stat(follow_symlinks=False)

    engine, SessionLocal = create_engine_and_session(tmp_path / "executor.db")
    init_db(engine)
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

    result = execute_item(
        OperationItem(
            sequence=1,
            operation="quarantine_purge",
            source=public_view,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=st.st_size,
            expected_mtime_ns=st.st_mtime_ns,
            expected_hash=hashlib.sha256(payload).hexdigest(),
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge-authorized",
        session_factory=SessionLocal,
        worker_id="worker-1",
        quarantine_entry_id=1,
        purge_manifest=frozen_manifest,
    )

    assert result.state == "completed"
    assert result.reason == "purged"
    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    marker = purge_dir / "destroy-intent.json"
    assert marker.is_file()
    for tombstone in (
        anchor,
        captured_source,
        public_view,
        purge_dir / "current-anchor",
        purge_dir / "captured-source",
        purge_dir / "public-view",
    ):
        tombstone_st = tombstone.stat(follow_symlinks=False)
        assert tombstone_st.st_size == 0
        assert (tombstone_st.st_dev, tombstone_st.st_ino) == (st.st_dev, st.st_ino)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None


def test_quarantine_purge_executor_revalidates_historical_owner_before_capture(tmp_path: Path) -> None:
    """An alias owner that becomes active after Validate must block Execute without mutation."""
    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    selected_attempt = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    historical_attempt = quarantine_root / ".tx" / "entry-2" / "attempt-1"
    selected_attempt.mkdir(parents=True)
    historical_attempt.mkdir(parents=True)

    payload = b"gate6a-purge-execute-owner-race"
    anchor = selected_attempt / "anchor"
    captured_source = selected_attempt / "captured_source"
    public_view = quarantine_root / "entry.q-1.bin"
    historical_candidate = historical_attempt / "anchor"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    os.link(anchor, historical_candidate)
    st = anchor.stat(follow_symlinks=False)
    payload_hash = hashlib.sha256(payload).hexdigest()

    engine, SessionLocal = create_engine_and_session(tmp_path / "executor-owner-race.db")
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
                content_hash=payload_hash,
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
                content_hash=payload_hash,
            )
        )
        session.commit()

    with SessionLocal() as session:
        selected = session.get(QuarantineEntry, 1)
        assert selected is not None
        frozen_manifest = build_purge_topology_manifest(
            selected,
            quarantine_root,
            owner_lookup=lambda owner_id: session.get(QuarantineEntry, owner_id),
        )
        assert frozen_manifest["blockers"] == []
        assert frozen_manifest["historical_conflict_entry_ids"] == [2]

    # Simulate the owner changing after plan Validate but before Worker Execute.
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        owner = session.get(QuarantineEntry, 2)
        assert owner is not None
        owner.state = "active"
        owner.tx_phase = "active"
        session.commit()

    result = execute_item(
        OperationItem(
            sequence=1,
            operation="quarantine_purge",
            source=public_view,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=st.st_size,
            expected_mtime_ns=st.st_mtime_ns,
            expected_hash=payload_hash,
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge-owner-race",
        session_factory=SessionLocal,
        worker_id="worker-1",
        quarantine_entry_id=1,
        purge_manifest=frozen_manifest,
    )

    assert result.state == "failed"
    assert "SHARED_ACTIVE_PAYLOAD" in result.reason or "PURGE_TOPOLOGY_CHANGED" in result.reason
    assert anchor.exists()
    assert captured_source.exists()
    assert public_view.exists()
    assert historical_candidate.exists()

    with SessionLocal() as session:
        selected = session.get(QuarantineEntry, 1)
        owner = session.get(QuarantineEntry, 2)
        assert selected is not None and owner is not None
        assert selected.state == "active"
        assert selected.tx_phase == "active"
        assert selected.purged_at is None
        assert owner.state == "active"
        assert owner.tx_phase == "active"


def test_quarantine_purge_executor_rejects_frozen_identity_drift_before_capture(tmp_path: Path) -> None:
    """Execute must bind purge authority to the identity frozen into the plan item."""
    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    attempt = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    payload = b"gate6a-purge-frozen-identity"
    payload_hash = hashlib.sha256(payload).hexdigest()
    anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = quarantine_root / "frozen-identity.q-1.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    st = anchor.stat(follow_symlinks=False)

    engine, SessionLocal = create_engine_and_session(tmp_path / "executor-frozen-identity.db")
    init_db(engine)
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path=str(data / "frozen-identity.bin"),
                quarantine_path=str(public_view),
                state="active",
                tx_phase="active",
                authoritative_anchor_path=str(anchor),
                active_attempt_generation=1,
                device=st.st_dev,
                inode=st.st_ino,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                content_hash=payload_hash,
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

    # Simulate DB identity drift after plan Validate while the frozen filesystem
    # payload itself remains unchanged. Execute must reject before entering purging
    # or renaming any source into a private purge slot.
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        entry.content_hash = hashlib.sha256(b"different-authority").hexdigest()
        session.commit()

    result = execute_item(
        OperationItem(
            sequence=1,
            operation="quarantine_purge",
            source=public_view,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=st.st_size,
            expected_mtime_ns=st.st_mtime_ns,
            expected_hash=payload_hash,
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge-frozen-identity",
        session_factory=SessionLocal,
        worker_id="worker-1",
        quarantine_entry_id=1,
        purge_manifest=frozen_manifest,
    )

    assert result.state == "failed"
    assert "PURGE_FROZEN_IDENTITY_CHANGED" in result.reason
    assert anchor.exists()
    assert captured_source.exists()
    assert public_view.exists()
    assert not (quarantine_root / ".tx" / "entry-1" / "attempt-2").exists()

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.purged_at is None
