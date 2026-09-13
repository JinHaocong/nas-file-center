from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow


def test_transactional_purge_resumes_after_one_qualified_slot_was_destroyed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.quarantine.purge as purge

    engine, SessionLocal = create_engine_and_session(tmp_path / "recovery.db")
    init_db(engine)
    data = tmp_path / "data"
    quarantine_root = data / ".nas-file-center-trash"
    attempt1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt1.mkdir(parents=True)

    payload = b"gate6a-partial-destruction-recovery"
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

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        frozen_manifest = purge.build_purge_topology_manifest(
            entry,
            quarantine_root,
            owner_lookup=lambda _: None,
        )
        assert frozen_manifest["blockers"] == []

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    purge_dir = quarantine_root / ".tx" / "entry-1" / "attempt-2" / "purge"
    assert len(list(purge_dir.iterdir())) == 3

    original_renew = purge.renew_and_assert_worker_lease
    fence_calls = 0

    def crash_before_second_destruction(*args, **kwargs):
        nonlocal fence_calls
        fence_calls += 1
        result = original_renew(*args, **kwargs)
        if fence_calls == 2:
            raise RuntimeError("simulated crash after first qualified destruction")
        return result

    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", crash_before_second_destruction)
    with pytest.raises(RuntimeError, match="simulated crash"):
        purge.destroy_transactional_purge_capture(
            SessionLocal,
            entry_id=1,
            worker_id="worker-1",
            frozen_manifest=frozen_manifest,
            quarantine_root=quarantine_root,
            allowed_roots=[data],
        )
    monkeypatch.setattr(purge, "renew_and_assert_worker_lease", original_renew)

    assert len(list(purge_dir.iterdir())) == 2
    assert not anchor.exists()
    assert not captured_source.exists()
    assert not public_view.exists()

    purge.execute_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )
    purge.destroy_transactional_purge_capture(
        SessionLocal,
        entry_id=1,
        worker_id="worker-1",
        frozen_manifest=frozen_manifest,
        quarantine_root=quarantine_root,
        allowed_roots=[data],
    )

    assert list(purge_dir.iterdir()) == []
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
        assert entry.purged_at is not None
        assert entry.active_attempt_generation == 2
