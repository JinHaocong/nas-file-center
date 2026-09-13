from __future__ import annotations

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
        OperationItem(sequence=1, operation="quarantine_purge", source=public_view),
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
    assert "purged" in result.reason.lower()
    assert not anchor.exists()
    assert not captured_source.exists()
    assert not public_view.exists()

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
