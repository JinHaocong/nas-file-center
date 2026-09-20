from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile

import pytest
from sqlalchemy import inspect

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _session_with_worker(tmp_path: Path, worker_id: str = "gate6c-worker"):
    db_path = tmp_path / "gate6c.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=tmp_path / "backups")
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()
        session.commit()
    return engine, SessionLocal


def _second_filesystem_dir(tmp_path: Path) -> Path:
    shm = Path("/dev/shm")
    if not shm.exists() or not shm.is_dir():
        pytest.skip("/dev/shm is unavailable; true cross-filesystem test cannot run")
    if os.stat(shm).st_dev == os.stat(tmp_path).st_dev:
        pytest.skip("/dev/shm is not a distinct filesystem on this runner")
    return Path(tempfile.mkdtemp(prefix="nfc-gate6c-", dir=str(shm)))


def test_gate6c_schema_columns_are_created(tmp_path):
    engine, _SessionLocal = _session_with_worker(tmp_path)
    cols = {c["name"] for c in inspect(engine).get_columns("quarantine_entries")}
    assert {
        "transaction_mode",
        "quarantine_device",
        "quarantine_inode",
        "quarantine_mtime_ns",
    }.issubset(cols)


def test_capability_classifies_true_cross_storage(tmp_path, monkeypatch):
    from app.quarantine import capability as cap

    source_root = tmp_path / "data"
    source_root.mkdir()
    source = source_root / "x.bin"
    source.write_bytes(b"x")
    q_root = _second_filesystem_dir(tmp_path)
    try:
        target_dir = q_root / "target"
        target_dir.mkdir()

        monkeypatch.setattr(cap, "_probe_rename_noreplace_supported", lambda **_kwargs: True)
        result = cap.resolve_mutation_capability(
            source,
            target_dir,
            q_root,
            [source_root, q_root],
        )
        assert result == cap.MutationCapability.CROSS_STORAGE_TRANSACTIONAL
    finally:
        shutil.rmtree(q_root, ignore_errors=True)


def test_executor_allows_quarantine_root_outside_allowed_roots_and_routes_cross_storage(
    tmp_path, monkeypatch
):
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    from app.quarantine import capability as cap
    import app.quarantine.cross_storage as cross

    data_root = tmp_path / "data"
    data_root.mkdir()
    q_root = tmp_path / "quarantine"
    q_root.mkdir()
    source = data_root / "x.bin"
    payload = b"payload"
    source.write_bytes(payload)
    st = source.stat()

    monkeypatch.setattr(
        cap,
        "resolve_mutation_capability",
        lambda *_args, **_kwargs: cap.MutationCapability.CROSS_STORAGE_TRANSACTIONAL,
    )
    calls = []
    monkeypatch.setattr(
        cross,
        "execute_cross_storage_quarantine",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    target = q_root / "task-1" / "root-0" / "x.q-1.bin"
    item = OperationItem(
        sequence=1,
        operation="quarantine",
        source=source,
        target=target,
        expected_size=len(payload),
        expected_mtime_ns=st.st_mtime_ns,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
        expected_hash=_sha256(payload),
    )
    result = execute_item(
        item,
        allowed_roots=[data_root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=q_root,
        plan_id="gate6c",
        session_factory=object(),
        worker_id="worker",
        quarantine_entry_id=1,
    )

    assert result.state == "completed"
    assert result.result_path == target
    assert result.quarantine_identity_authoritative is True
    assert len(calls) == 1


def test_true_cross_storage_quarantine_copies_verifies_publishes_then_unlinks_source(tmp_path):
    from app.quarantine.cross_storage import CROSS_STORAGE_MODE, execute_cross_storage_quarantine

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "movie.bin"
    payload = (b"gate6c-cross-storage-" * 65536) + b"tail"
    source.write_bytes(payload)
    src_stat = source.stat()
    q_root = _second_filesystem_dir(tmp_path)

    try:
        target = q_root / "task-1" / "root-0" / "movie.q-1.bin"
        with SessionLocal() as session:
            entry = QuarantineEntry(
                original_path=str(source),
                quarantine_path=str(target),
                state="preparing",
                size=len(payload),
                content_hash=_sha256(payload),
                mtime_ns=src_stat.st_mtime_ns,
                device=src_stat.st_dev,
                inode=src_stat.st_ino,
            )
            session.add(entry)
            session.commit()
            entry_id = entry.id

        execute_cross_storage_quarantine(
            SessionLocal,
            entry_id,
            worker_id,
            allowed_roots=[data_root],
            quarantine_root=q_root,
        )

        assert not source.exists()
        assert target.read_bytes() == payload
        target_stat = target.stat()
        assert target_stat.st_dev != src_stat.st_dev

        with SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            assert entry is not None
            assert entry.state == "active"
            assert entry.tx_phase == "active"
            assert entry.transaction_mode == CROSS_STORAGE_MODE
            assert entry.device == src_stat.st_dev
            assert entry.inode == src_stat.st_ino
            assert entry.quarantine_device == target_stat.st_dev
            assert entry.quarantine_inode == target_stat.st_ino
            assert entry.quarantine_mtime_ns == target_stat.st_mtime_ns
    finally:
        shutil.rmtree(q_root, ignore_errors=True)


def test_cross_storage_target_collision_preserves_source(tmp_path):
    from app.quarantine.cross_storage import execute_cross_storage_quarantine

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "x.bin"
    payload = b"source-authority"
    source.write_bytes(payload)
    src_stat = source.stat()
    q_root = _second_filesystem_dir(tmp_path)

    try:
        target = q_root / "task-1" / "root-0" / "x.q-1.bin"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"foreign")

        with SessionLocal() as session:
            entry = QuarantineEntry(
                original_path=str(source),
                quarantine_path=str(target),
                state="preparing",
                size=len(payload),
                content_hash=_sha256(payload),
                mtime_ns=src_stat.st_mtime_ns,
                device=src_stat.st_dev,
                inode=src_stat.st_ino,
            )
            session.add(entry)
            session.commit()
            entry_id = entry.id

        with pytest.raises(FileExistsError):
            execute_cross_storage_quarantine(
                SessionLocal,
                entry_id,
                worker_id,
                allowed_roots=[data_root],
                quarantine_root=q_root,
            )

        assert source.read_bytes() == payload
        assert target.read_bytes() == b"foreign"
        with SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            assert entry is not None
            assert entry.state == "conflict"
            assert entry.tx_phase == "conflict"
    finally:
        shutil.rmtree(q_root, ignore_errors=True)
