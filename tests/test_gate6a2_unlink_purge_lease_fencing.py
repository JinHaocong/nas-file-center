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
    engine, SessionLocal = create_engine_and_session(tmp_path / "gate6a2-lease-fence.db")
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
    payload = b"gate6a2-worker-lease-fence"

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


def test_lost_worker_lease_immediately_before_unlink_fences_mutation_and_terminal_state(
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

    survivor_before = external_survivor.stat(follow_symlinks=False)

    def lose_lease(*args, **kwargs):
        raise JobLeaseLost("simulated stale worker immediately before unlink")

    def forbidden_descriptor_unlink(*args, **kwargs):
        pytest.fail("descriptor unlink must not run after worker lease is lost")

    with monkeypatch.context() as patch:
        patch.setattr(
            unlink_purge,
            "renew_and_assert_worker_lease",
            lose_lease,
            raising=False,
        )
        patch.setattr(
            unlink_purge,
            "_descriptor_unlink_frozen_path",
            forbidden_descriptor_unlink,
        )

        with pytest.raises(JobLeaseLost, match="stale worker"):
            unlink_purge.execute_journaled_unlink_purge(
                SessionLocal,
                entry_id=1,
                quarantine_root=trash,
                frozen_manifest=frozen_manifest,
                worker_id="stale-worker",
            )

    # Losing the lease at the irreversible boundary must fence every unlink.
    for path in (anchor, captured, public_view, external_survivor):
        assert path.exists()
        assert path.read_bytes() == payload

    survivor_after = external_survivor.stat(follow_symlinks=False)
    assert (survivor_after.st_dev, survivor_after.st_ino) == (
        survivor_before.st_dev,
        survivor_before.st_ino,
    )

    # Durable authority/intent may already exist, but a stale worker must never
    # publish a terminal purge state or terminal-success journal record.
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state != "purged"
        assert entry.tx_phase != "purged"
        assert entry.purged_at is None

        rows = list(
            session.scalars(
                select(OperationJournal)
                .where(OperationJournal.operation == "quarantine_unlink_purge")
                .order_by(OperationJournal.sequence.asc(), OperationJournal.id.asc())
            )
        )
        for row in rows:
            before = json.loads(row.before_json or "{}")
            after = json.loads(row.after_json or "{}")
            assert before.get("phase") != "terminal"
            assert after.get("phase") != "purged"
