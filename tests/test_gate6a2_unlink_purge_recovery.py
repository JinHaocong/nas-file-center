from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import create_engine_and_session, init_db
from app.models import OperationJournal, QuarantineEntry


def _setup_recovery_entry(tmp_path: Path):
    engine, SessionLocal = create_engine_and_session(tmp_path / "gate6a2-unlink-recovery.db")
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
    payload = b"gate6a2-partial-unlink-recovery"

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


def test_partial_unlink_crash_resumes_only_from_durable_exact_path_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.quarantine.unlink_purge as unlink_purge

    try:
        execute = unlink_purge.execute_journaled_unlink_purge
    except AttributeError as exc:
        pytest.fail(f"Gate6-A2 journaled unlink recovery is not implemented yet: {exc}")

    (
        SessionLocal,
        trash,
        anchor,
        captured,
        public_view,
        external_survivor,
        payload,
    ) = _setup_recovery_entry(tmp_path)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        frozen_manifest = unlink_purge.build_unlink_manifest(entry, trash)
        assert frozen_manifest["blockers"] == []

    survivor_before = external_survivor.stat(follow_symlinks=False)
    real_unlink = unlink_purge.os.unlink
    unlink_calls = 0

    def crash_after_first_authorized_unlink(path, *args, **kwargs):
        nonlocal unlink_calls
        result = real_unlink(path, *args, **kwargs)
        unlink_calls += 1
        if unlink_calls == 1:
            raise RuntimeError("simulated crash immediately after first unlink")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(unlink_purge.os, "unlink", crash_after_first_authorized_unlink)
        with pytest.raises(RuntimeError, match="immediately after first unlink"):
            execute(
                SessionLocal,
                entry_id=1,
                quarantine_root=trash,
                frozen_manifest=frozen_manifest,
            )

    # Canonical order starts with the selected entry's authoritative anchor. The
    # process died after that unlink returned, before a completion checkpoint.
    assert not anchor.exists()
    assert captured.exists()
    assert public_view.exists()
    assert external_survivor.exists()
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
        assert rows, "irreversible unlink must have durable new-operation evidence"

        durable_records = [json.loads(row.before_json or "{}") for row in rows]
        assert any(
            record.get("purge_semantics") == "unlink_v1"
            and record.get("phase") == "unlink_intent"
            and record.get("role") == "authoritative_anchor"
            and record.get("path") == str(anchor)
            for record in durable_records
        ), "the exact missing pathname must have durable intent before its unlink"

    def forbidden_ftruncate(*args, **kwargs):
        pytest.fail("Gate6-A2 recovery must never fall through to ftruncate purge")

    with monkeypatch.context() as patch:
        patch.setattr(unlink_purge.os, "ftruncate", forbidden_ftruncate)
        result = execute(
            SessionLocal,
            entry_id=1,
            quarantine_root=trash,
            frozen_manifest=None,
        )

    # Restart recovered authority from durable Gate6-A2 records. Only the exact
    # journaled missing anchor is accepted idempotently; remaining frozen paths
    # are revalidated and removed. Same-inode external data is untouched.
    assert result["purge_semantics"] == "unlink_v1"
    assert "authoritative_anchor" in result["recovered_missing_roles"]
    assert not captured.exists()
    assert not public_view.exists()

    survivor_after = external_survivor.stat(follow_symlinks=False)
    assert external_survivor.read_bytes() == payload
    assert (survivor_after.st_dev, survivor_after.st_ino) == (
        survivor_before.st_dev,
        survivor_before.st_ino,
    )

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
