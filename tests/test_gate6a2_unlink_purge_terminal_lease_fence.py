from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import create_engine_and_session, init_db
from app.models import OperationJournal, QuarantineEntry
from app.tasks.state_machine import JobLeaseLost


def _setup_entry(tmp_path: Path):
    engine, SessionLocal = create_engine_and_session(tmp_path / "gate6a2-terminal-lease-fence.db")
    init_db(engine)

    data = tmp_path / "data"
    indexed = data / "indexed"
    indexed.mkdir(parents=True)
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "selected.q-1.bin"
    external_survivor = indexed / "external-hardlink.bin"
    payload = b"gate6a2-terminal-lease-fence"

    anchor.write_bytes(payload)
    os.link(anchor, captured)
    os.link(anchor, public_view)
    os.link(anchor, external_survivor)
    st = anchor.stat(follow_symlinks=False)

    with SessionLocal() as session:
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
                content_hash=hashlib.sha256(payload).hexdigest(),
            )
        )
        session.commit()

    return SessionLocal, trash, anchor, captured, public_view, external_survivor, payload


def test_worker_losing_lease_after_last_unlink_cannot_publish_terminal_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.quarantine.unlink_purge as unlink_purge

    (
        SessionLocal,
        trash,
        anchor,
        captured,
        public_view,
        external_survivor,
        payload,
    ) = _setup_entry(tmp_path)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        frozen_manifest = unlink_purge.build_unlink_manifest(entry, trash)
        assert frozen_manifest["blockers"] == []

    lease_checks = 0

    def lose_lease_at_terminal_boundary(*args, **kwargs):
        nonlocal lease_checks
        lease_checks += 1
        if lease_checks == 4:
            raise JobLeaseLost("simulated stale worker before terminal purge commit")

    monkeypatch.setattr(
        unlink_purge,
        "renew_and_assert_worker_lease",
        lose_lease_at_terminal_boundary,
    )

    with pytest.raises(JobLeaseLost, match="terminal purge commit"):
        unlink_purge.execute_journaled_unlink_purge(
            SessionLocal,
            entry_id=1,
            quarantine_root=trash,
            frozen_manifest=frozen_manifest,
            worker_id="worker-loses-lease-after-unlinks",
        )

    assert lease_checks == 4

    # The three exact NFC-owned paths may already be gone, but the external
    # hardlink must remain byte-for-byte intact and the stale worker must not
    # publish terminal success.
    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()
    assert external_survivor.read_bytes() == payload

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
        assert entry.purged_at is None

        rows = list(
            session.scalars(
                select(OperationJournal)
                .where(OperationJournal.operation == "quarantine_unlink_purge")
                .order_by(OperationJournal.sequence.asc(), OperationJournal.id.asc())
            )
        )
        assert rows
        for row in rows:
            before = json.loads(row.before_json or "{}")
            after = json.loads(row.after_json or "{}")
            assert before.get("phase") != "terminal"
            assert after.get("phase") != "purged"
