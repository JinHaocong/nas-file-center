from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import create_engine_and_session, init_db
from app.exceptions import StateConflictError
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

def _rewrite_as_next_generation(
    SessionLocal,
    trash: Path,
    *,
    entry_id: int,
    payload: bytes,
) -> tuple[Path, Path, Path]:
    attempt = trash / ".tx" / f"entry-{entry_id}" / "attempt-2"
    attempt.mkdir(parents=True, exist_ok=False)
    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / f"generation-2.q-{entry_id}.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured)
    os.link(anchor, public_view)
    st = anchor.stat(follow_symlinks=False)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        entry.original_path = str(trash.parent / "generation-2-source.bin")
        entry.quarantine_path = str(public_view)
        entry.state = "active"
        entry.tx_phase = "active"
        entry.active_attempt_generation = 2
        entry.authoritative_anchor_path = str(anchor)
        entry.device = st.st_dev
        entry.inode = st.st_ino
        entry.size = st.st_size
        entry.mtime_ns = st.st_mtime_ns
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.purged_at = None
        entry.last_error = None
        session.commit()

    return anchor, captured, public_view


def test_completed_prior_generation_journal_does_not_poison_reused_entry_id(
    tmp_path: Path,
) -> None:
    import app.quarantine.unlink_purge as unlink_purge

    (
        SessionLocal,
        trash,
        _old_anchor,
        _old_captured,
        _old_public_view,
        external_survivor,
        old_payload,
    ) = _setup_recovery_entry(tmp_path)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        first_manifest = unlink_purge.build_unlink_manifest(entry, trash)

    first = unlink_purge.execute_journaled_unlink_purge(
        SessionLocal,
        entry_id=1,
        quarantine_root=trash,
        frozen_manifest=first_manifest,
    )
    assert first["purge_semantics"] == "unlink_v1"
    assert external_survivor.read_bytes() == old_payload

    new_payload = b"gate6a2-generation-two-real-nas-regression"
    anchor, captured, public_view = _rewrite_as_next_generation(
        SessionLocal,
        trash,
        entry_id=1,
        payload=new_payload,
    )

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        second_manifest = unlink_purge.build_unlink_manifest(entry, trash)
        assert second_manifest["active_attempt_generation"] == 2

    second = unlink_purge.execute_journaled_unlink_purge(
        SessionLocal,
        entry_id=1,
        quarantine_root=trash,
        frozen_manifest=second_manifest,
    )

    assert second["purge_semantics"] == "unlink_v1"
    assert second["removed_count"] == 3
    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()
    assert external_survivor.read_bytes() == old_payload

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        authorities = []
        generations = []
        rows = list(
            session.scalars(
                select(OperationJournal)
                .where(OperationJournal.operation == "quarantine_unlink_purge")
                .order_by(OperationJournal.id.asc())
            )
        )
        for row in rows:
            before = json.loads(row.before_json or "{}")
            if before.get("entry_id") == 1 and before.get("phase") == "authority":
                authorities.append(before)
                generations.append(before["manifest"]["active_attempt_generation"])
        assert generations == [1, 2]


def test_same_generation_prior_journal_still_fails_closed(
    tmp_path: Path,
) -> None:
    import app.quarantine.unlink_purge as unlink_purge

    (
        SessionLocal,
        trash,
        _anchor,
        _captured,
        _public_view,
        _external_survivor,
        _payload,
    ) = _setup_recovery_entry(tmp_path)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        manifest = unlink_purge.build_unlink_manifest(entry, trash)
        session.add(
            OperationJournal(
                operation="quarantine_unlink_purge",
                sequence=0,
                before_json=json.dumps(
                    {
                        "phase": "authority",
                        "purge_semantics": "unlink_v1",
                        "entry_id": 1,
                        "manifest": manifest,
                    }
                ),
                after_json="{}",
                metadata_before_json="{}",
                metadata_after_json="{}",
            )
        )
        session.commit()

    with pytest.raises(
        StateConflictError,
        match=r"unexpected prior Gate6-A2 journal.*generation #1",
    ):
        unlink_purge.execute_journaled_unlink_purge(
            SessionLocal,
            entry_id=1,
            quarantine_root=trash,
            frozen_manifest=manifest,
        )


def test_legacy_generationless_intents_recover_from_authority_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.quarantine.unlink_purge as unlink_purge

    (
        SessionLocal,
        trash,
        anchor,
        _captured,
        _public_view,
        _external_survivor,
        _payload,
    ) = _setup_recovery_entry(tmp_path)

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        manifest = unlink_purge.build_unlink_manifest(entry, trash)

    real_unlink = unlink_purge.os.unlink
    calls = 0

    def crash_once(path, *args, **kwargs):
        nonlocal calls
        result = real_unlink(path, *args, **kwargs)
        calls += 1
        if calls == 1:
            raise RuntimeError("legacy epoch crash")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(unlink_purge.os, "unlink", crash_once)
        with pytest.raises(RuntimeError, match="legacy epoch crash"):
            unlink_purge.execute_journaled_unlink_purge(
                SessionLocal,
                entry_id=1,
                quarantine_root=trash,
                frozen_manifest=manifest,
            )

    assert not anchor.exists()

    # Simulate journal rows written by the pre-fix unlink_v1 implementation:
    # authority manifest contains the generation, but intent rows do not.
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(OperationJournal).where(
                    OperationJournal.operation == "quarantine_unlink_purge"
                )
            )
        )
        for row in rows:
            before = json.loads(row.before_json or "{}")
            after = json.loads(row.after_json or "{}")
            before.pop("active_attempt_generation", None)
            after.pop("active_attempt_generation", None)
            row.before_json = json.dumps(before)
            row.after_json = json.dumps(after)
        session.commit()

    recovered = unlink_purge.execute_journaled_unlink_purge(
        SessionLocal,
        entry_id=1,
        quarantine_root=trash,
        frozen_manifest=None,
    )
    assert recovered["purge_semantics"] == "unlink_v1"
    assert "authoritative_anchor" in recovered["recovered_missing_roles"]

