from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.exceptions import StateConflictError
from app.models import AuditEvent, IndexRoot, IndexedPath, QuarantineEntry, utcnow
from app.quarantine import single_unlink_purge
from app.quarantine.purge_advisory import discover_unlink_purge_advisory
from app.quarantine.service_adapter import Gate6A2FileCenterService
from app.quarantine.single_unlink_purge import purge_single_transactional_entry
from app.quarantine.unlink_purge import OPERATION_ID, build_unlink_manifest
from app.service import FileCenterService


def _settings(tmp_path: Path) -> tuple[Settings, Path, Path]:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    return settings, data, trash


def _seed_transactional_entry(
    service: FileCenterService,
    *,
    data: Path,
    trash: Path,
    label: str,
) -> tuple[int, Path, Path, Path]:
    payload = f"gate6a2-review-{label}".encode()
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / f"{label}.bin"),
            quarantine_path=str(trash / f"pending-{label}.bin"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()
        entry_id = int(entry.id)

        attempt = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"{label}.q-{entry_id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.device = st.st_dev
        entry.inode = st.st_ino
        entry.size = st.st_size
        entry.mtime_ns = st.st_mtime_ns
        session.commit()

    return entry_id, anchor, captured, public_view


def test_single_clear_legacy_entry_fails_closed_without_using_legacy_delete_path(
    tmp_path: Path,
) -> None:
    settings, data, trash = _settings(tmp_path)
    service = Gate6A2FileCenterService(settings)
    legacy_path = trash / "legacy.bin"
    payload = b"gate6a2-legacy-must-not-delete"
    legacy_path.write_bytes(payload)
    st = legacy_path.stat(follow_symlinks=False)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "legacy.bin"),
            quarantine_path=str(legacy_path),
            state="active",
            tx_phase=None,
            active_attempt_generation=0,
            authoritative_anchor_path=None,
            device=st.st_dev,
            inode=st.st_ino,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            content_hash=hashlib.sha256(payload).hexdigest(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = int(entry.id)

    with pytest.raises(StateConflictError):
        service.purge_quarantine_entry(
            entry_id,
            confirmation="DELETE",
            is_admin=True,
        )

    assert legacy_path.exists()
    assert legacy_path.read_bytes() == payload
    with service.SessionLocal() as session:
        persisted = session.get(QuarantineEntry, entry_id)
        assert persisted is not None
        assert persisted.state == "active"


def test_single_clear_retry_repairs_post_terminal_audit_gap_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, data, trash = _settings(tmp_path)
    service = FileCenterService(settings)
    entry_id, anchor, captured, public_view = _seed_transactional_entry(
        service,
        data=data,
        trash=trash,
        label="terminal-audit-gap",
    )

    real_advisory = single_unlink_purge._fresh_survivor_advisory

    def crash_after_terminal_commit(*args, **kwargs):
        raise RuntimeError("injected crash after unlink terminal commit")

    monkeypatch.setattr(
        single_unlink_purge,
        "_fresh_survivor_advisory",
        crash_after_terminal_commit,
    )
    with pytest.raises(RuntimeError, match="injected crash"):
        purge_single_transactional_entry(
            service,
            entry_id,
            confirmation="DELETE",
            is_admin=True,
        )

    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        first_audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.operation == OPERATION_ID)
            )
        )
        assert first_audits == []

    monkeypatch.setattr(
        single_unlink_purge,
        "_fresh_survivor_advisory",
        real_advisory,
    )
    recovered = purge_single_transactional_entry(
        service,
        entry_id,
        confirmation="DELETE",
        is_admin=True,
    )
    assert recovered["state"] == "purged"
    assert recovered["purge_semantics"] == "unlink_v1"

    repeated = purge_single_transactional_entry(
        service,
        entry_id,
        confirmation="DELETE",
        is_admin=True,
    )
    assert repeated["state"] == "purged"

    with service.SessionLocal() as session:
        audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.operation == OPERATION_ID)
            )
        )
        assert len(audits) == 1
        assert audits[0].result == "purged"


def test_missing_live_index_candidate_marks_advisory_incomplete(
    tmp_path: Path,
) -> None:
    settings, data, trash = _settings(tmp_path)
    service = FileCenterService(settings)
    entry_id, _, _, _ = _seed_transactional_entry(
        service,
        data=data,
        trash=trash,
        label="missing-live-candidate",
    )
    indexed_root = data / "indexed"
    indexed_root.mkdir(parents=True)
    stale = indexed_root / "stale-hardlink.bin"

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        manifest = build_unlink_manifest(entry, trash)
        assert manifest["blockers"] == []

        root_key = str(indexed_root)
        session.add(IndexRoot(root=root_key, last_indexed_at=utcnow()))
        session.add(
            IndexedPath(
                root_key=root_key,
                absolute_path=str(stale),
                relative_path=stale.name,
                basename=stale.name,
                stem=stale.stem,
                suffix=stale.suffix,
                size=int(entry.size),
                mtime_ns=int(entry.mtime_ns),
                device=int(entry.device),
                inode=int(entry.inode),
                is_dir=False,
                scan_generation="gate6a2-review",
            )
        )
        session.commit()

        advisory = discover_unlink_purge_advisory(session, entry, manifest)

    assert advisory["status"] == "incomplete"
    assert advisory["hardlink_survivors"] == []
    assert str(stale) in advisory["stale_candidates"]
