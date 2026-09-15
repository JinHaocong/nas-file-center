from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow


def test_descriptor_bound_destroy_preserves_replacement_in_final_path_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The irreversible payload mutation must target the qualified fd, never the pathname."""
    import app.quarantine.purge as purge

    engine, SessionLocal = create_engine_and_session(tmp_path / "descriptor-destroy.db")
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-descriptor-bound-destroy"
    foreign_payload = b"foreign-replacement-must-survive"
    anchor = attempt1 / "anchor"
    captured_source = attempt1 / "captured_source"
    public_view = quarantine_root / "descriptor.q-1.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    st = anchor.stat(follow_symlinks=False)
    digest = hashlib.sha256(payload).hexdigest()

    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path=str(data / "descriptor.bin"),
                quarantine_path=str(public_view),
                state="active",
                tx_phase="active",
                authoritative_anchor_path=str(anchor),
                active_attempt_generation=1,
                device=st.st_dev,
                inode=st.st_ino,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                content_hash=digest,
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
        frozen_manifest = dict(frozen_manifest)
        frozen_manifest["frozen_payload_identity"] = {
            "device": st.st_dev,
            "inode": st.st_ino,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "content_hash": digest,
        }

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    victim = purge_dir / "public-view"
    displaced = purge_dir / "displaced-qualified-payload"

    real_ftruncate = os.ftruncate
    injected = False

    def ftruncate_with_final_aba(fd: int, length: int) -> None:
        nonlocal injected
        if not injected:
            injected = True
            os.rename(victim, displaced)
            victim.write_bytes(foreign_payload)
        real_ftruncate(fd, length)

    monkeypatch.setattr(purge.os, "ftruncate", ftruncate_with_final_aba)

    purge._destroy_one_qualified_purge_slot(
        SessionLocal,
        "worker-1",
        victim,
        [data, quarantine_root],
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
        expected_size=st.st_size,
        expected_mtime_ns=st.st_mtime_ns,
        expected_hash=digest,
    )

    assert injected is True
    assert victim.read_bytes() == foreign_payload
    assert displaced.exists()
    assert displaced.stat(follow_symlinks=False).st_size == 0
