from __future__ import annotations

import errno
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
        "restore_target_path",
        "restore_device",
        "restore_inode",
        "restore_mtime_ns",
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



def test_true_cross_storage_restore_copies_back_without_overwrite(tmp_path):
    from app.quarantine.cross_storage import (
        execute_cross_storage_quarantine,
        execute_cross_storage_restore,
    )

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "restore.bin"
    payload = b"restore-me-" * 32768
    source.write_bytes(payload)
    src_stat = source.stat()
    q_root = _second_filesystem_dir(tmp_path)

    try:
        target = q_root / "task-1" / "root-0" / "restore.q-1.bin"
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
        assert target.exists()

        execute_cross_storage_restore(
            SessionLocal,
            entry_id,
            worker_id,
            allowed_roots=[data_root],
            quarantine_root=q_root,
            destination=source,
        )

        assert source.read_bytes() == payload
        assert not target.exists()
        restored_stat = source.stat()
        with SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            assert entry is not None
            assert entry.state == "restored"
            assert entry.tx_phase == "restored"
            assert entry.restore_target_path == str(source.absolute())
            assert entry.restore_device == restored_stat.st_dev
            assert entry.restore_inode == restored_stat.st_ino
            assert entry.restore_mtime_ns == restored_stat.st_mtime_ns
    finally:
        shutil.rmtree(q_root, ignore_errors=True)


def test_cross_storage_restore_never_overwrites_replacement(tmp_path):
    from app.quarantine.cross_storage import (
        execute_cross_storage_quarantine,
        execute_cross_storage_restore,
    )

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "restore-collision.bin"
    payload = b"quarantined"
    source.write_bytes(payload)
    src_stat = source.stat()
    q_root = _second_filesystem_dir(tmp_path)

    try:
        target = q_root / "task-1" / "root-0" / "restore-collision.q-1.bin"
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
        source.write_bytes(b"replacement")

        with pytest.raises(FileExistsError):
            execute_cross_storage_restore(
                SessionLocal,
                entry_id,
                worker_id,
                allowed_roots=[data_root],
                quarantine_root=q_root,
                destination=source,
            )

        assert source.read_bytes() == b"replacement"
        assert target.read_bytes() == payload
    finally:
        shutil.rmtree(q_root, ignore_errors=True)


def test_cross_storage_recovery_preserves_source_path_replacement(tmp_path, monkeypatch):
    import app.quarantine.cross_storage as cross
    from app.exceptions import StateConflictError

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "aba.bin"
    payload = b"original-authority"
    source.write_bytes(payload)
    src_stat = source.stat()
    q_root = _second_filesystem_dir(tmp_path)

    try:
        target = q_root / "task-1" / "root-0" / "aba.q-1.bin"
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

        real_unlink = cross._verify_and_unlink_source
        monkeypatch.setattr(
            cross,
            "_verify_and_unlink_source",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash-before-unlink")),
        )

        with pytest.raises(RuntimeError, match="crash-before-unlink"):
            cross.execute_cross_storage_quarantine(
                SessionLocal,
                entry_id,
                worker_id,
                allowed_roots=[data_root],
                quarantine_root=q_root,
            )

        monkeypatch.setattr(cross, "_verify_and_unlink_source", real_unlink)
        assert source.exists()
        assert target.exists()

        source.unlink()
        source.write_bytes(b"replacement")

        with pytest.raises(StateConflictError, match="SOURCE_REPLACEMENT"):
            cross.reconcile_cross_storage_quarantine(
                SessionLocal,
                entry_id,
                worker_id,
                allowed_roots=[data_root],
                quarantine_root=q_root,
            )

        assert source.read_bytes() == b"replacement"
        assert target.read_bytes() == payload
        with SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            assert entry is not None
            assert entry.state == "conflict"
            assert entry.tx_phase == "conflict"
    finally:
        shutil.rmtree(q_root, ignore_errors=True)


def test_cross_storage_unlink_manifest_is_public_view_only(tmp_path):
    from app.quarantine.cross_storage import execute_cross_storage_quarantine
    from app.quarantine.unlink_purge import build_unlink_manifest, revalidate_unlink_manifest

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "purge.bin"
    payload = b"purge-cross-storage"
    source.write_bytes(payload)
    src_stat = source.stat()
    q_root = _second_filesystem_dir(tmp_path)

    try:
        target = q_root / "task-1" / "root-0" / "purge.q-1.bin"
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

        with SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            manifest = build_unlink_manifest(entry, q_root)
            assert manifest["blockers"] == []
            assert [item["role"] for item in manifest["owned_paths"]] == ["public_view"]
            assert manifest["owned_paths"][0]["device"] == entry.quarantine_device
            assert manifest["owned_paths"][0]["inode"] == entry.quarantine_inode

            validation = revalidate_unlink_manifest(entry, q_root, manifest)
            assert validation["blockers"] == []
    finally:
        shutil.rmtree(q_root, ignore_errors=True)



def test_cross_storage_unlink_v1_purges_only_public_quarantine_payload(tmp_path):
    from app.quarantine.cross_storage import execute_cross_storage_quarantine
    from app.quarantine.unlink_purge import build_unlink_manifest, execute_journaled_unlink_purge

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "purge-exec.bin"
    sibling = data_root / "keep.bin"
    payload = b"purge-exec-cross-storage"
    source.write_bytes(payload)
    sibling.write_bytes(payload)
    src_stat = source.stat()
    sibling_stat = sibling.stat()
    q_root = _second_filesystem_dir(tmp_path)

    try:
        target = q_root / "task-1" / "root-0" / "purge-exec.q-1.bin"
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

        with SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            manifest = build_unlink_manifest(entry, q_root)
            assert manifest["blockers"] == []

        result = execute_journaled_unlink_purge(
            SessionLocal,
            entry_id=entry_id,
            quarantine_root=q_root,
            frozen_manifest=manifest,
            worker_id=worker_id,
        )

        assert result["removed_roles"] == ["public_view"]
        assert not target.exists()
        assert sibling.exists()
        assert sibling.stat().st_dev == sibling_stat.st_dev
        assert sibling.stat().st_ino == sibling_stat.st_ino
        assert sibling.read_bytes() == payload

        with SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            assert entry is not None
            assert entry.state == "purged"
            assert entry.tx_phase == "purged"
    finally:
        shutil.rmtree(q_root, ignore_errors=True)


def test_same_device_exdev_falls_back_to_verified_copy_and_restores(tmp_path, monkeypatch):
    """Bind/NAS mount boundaries may return EXDEV even when st_dev is equal."""

    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    from app.quarantine import capability as cap
    from app.quarantine.cross_storage import CROSS_STORAGE_MODE
    import app.quarantine.engine as compat_engine

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    q_root = tmp_path / "quarantine"
    q_root.mkdir()

    source = data_root / "mount-boundary.bin"
    payload = b"same-device-exdev-" * 8192
    source.write_bytes(payload)
    src_stat = source.stat()
    target = q_root / "task-1" / "root-0" / "mount-boundary.q-1.bin"

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
        entry_id = int(entry.id)

    # Reproduce the production topology: the device-number probe chooses COMPAT,
    # but the first descriptor-relative hard link crosses a mount boundary.
    monkeypatch.setattr(
        cap,
        "resolve_mutation_capability",
        lambda *_args, **_kwargs: cap.MutationCapability.COMPAT_TRANSACTIONAL,
    )

    def _raise_exdev(*_args, **_kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(compat_engine.os, "link", _raise_exdev)

    quarantine_item = OperationItem(
        sequence=1,
        operation="quarantine",
        source=source,
        target=target,
        expected_size=len(payload),
        expected_mtime_ns=src_stat.st_mtime_ns,
        expected_device=src_stat.st_dev,
        expected_inode=src_stat.st_ino,
        expected_hash=_sha256(payload),
    )
    result = execute_item(
        quarantine_item,
        allowed_roots=[data_root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=q_root,
        plan_id="same-device-exdev",
        session_factory=SessionLocal,
        worker_id=worker_id,
        quarantine_entry_id=entry_id,
    )

    assert result.state == "completed"
    assert result.quarantine_identity_authoritative is True
    assert not source.exists()
    assert target.read_bytes() == payload
    assert target.stat().st_dev == src_stat.st_dev

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.transaction_mode == CROSS_STORAGE_MODE
        assert entry.quarantine_device == target.stat().st_dev

    # Persisted verified-copy mode must also control restore. A fresh st_dev
    # probe would still say COMPAT on this synthetic same-device topology.
    restore_item = OperationItem(
        sequence=1,
        operation="restore",
        source=target,
        target=source,
        expected_size=len(payload),
        expected_hash=_sha256(payload),
    )
    restored = execute_item(
        restore_item,
        allowed_roots=[data_root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=q_root,
        plan_id="same-device-exdev-restore",
        session_factory=SessionLocal,
        worker_id=worker_id,
        quarantine_entry_id=entry_id,
    )

    assert restored.state == "completed"
    assert source.read_bytes() == payload
    assert not target.exists()
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "restored"
        assert entry.tx_phase == "restored"


def test_cross_storage_publish_falls_back_to_linkat_when_rename_noreplace_is_unsupported(
    tmp_path, monkeypatch
):
    import app.quarantine.cross_storage as cross

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    q_root = tmp_path / "quarantine"
    q_root.mkdir()

    source = data_root / "rename-unsupported.bin"
    payload = b"rename-noreplace-unsupported-" * 4096
    source.write_bytes(payload)
    src_stat = source.stat()
    target = q_root / "task-1" / "root-0" / "rename-unsupported.q-1.bin"

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
        entry_id = int(entry.id)

    def _unsupported(*_args, **_kwargs):
        raise OSError(
            errno.EOPNOTSUPP,
            "Atomic no-replace renameat2 not supported by filesystem",
            "cross-storage-staging",
        )

    monkeypatch.setattr(cross, "rename_noreplace_at", _unsupported)

    cross.execute_cross_storage_quarantine(
        SessionLocal,
        entry_id,
        worker_id,
        allowed_roots=[data_root],
        quarantine_root=q_root,
    )

    assert not source.exists()
    assert target.read_bytes() == payload
    target_stat = target.stat()

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.transaction_mode == cross.CROSS_STORAGE_MODE
        assert entry.quarantine_device == target_stat.st_dev
        assert entry.quarantine_inode == target_stat.st_ino

    tx_root = q_root / ".tx" / f"entry-{entry_id}"
    assert not list(tx_root.rglob("cross-storage-staging"))


def test_cross_storage_restore_publish_falls_back_to_linkat_when_rename_noreplace_is_unsupported(
    tmp_path, monkeypatch
):
    import app.quarantine.cross_storage as cross

    worker_id = "gate6c-worker"
    _engine, SessionLocal = _session_with_worker(tmp_path, worker_id)
    data_root = tmp_path / "data"
    data_root.mkdir()
    q_root = tmp_path / "quarantine"
    q_root.mkdir()

    destination = data_root / "restore-rename-unsupported.bin"
    payload = b"restore-rename-noreplace-unsupported-" * 4096
    quarantine_path = q_root / "task-1" / "root-0" / "restore.q-1.bin"
    quarantine_path.parent.mkdir(parents=True)
    quarantine_path.write_bytes(payload)
    q_stat = quarantine_path.stat()

    with SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(destination),
            quarantine_path=str(quarantine_path),
            state="active",
            tx_phase="active",
            transaction_mode=cross.CROSS_STORAGE_MODE,
            size=len(payload),
            content_hash=_sha256(payload),
            mtime_ns=q_stat.st_mtime_ns,
            device=q_stat.st_dev,
            inode=q_stat.st_ino,
            quarantine_device=q_stat.st_dev,
            quarantine_inode=q_stat.st_ino,
            quarantine_mtime_ns=q_stat.st_mtime_ns,
        )
        session.add(entry)
        session.commit()
        entry_id = int(entry.id)

    def _unsupported(*_args, **_kwargs):
        raise OSError(
            errno.EOPNOTSUPP,
            "Atomic no-replace renameat2 not supported by filesystem",
            "cross-restore-staging",
        )

    monkeypatch.setattr(cross, "rename_noreplace_at", _unsupported)

    cross.execute_cross_storage_restore(
        SessionLocal,
        entry_id,
        worker_id,
        destination=destination,
        allowed_roots=[data_root],
        quarantine_root=q_root,
    )

    assert destination.read_bytes() == payload
    assert not quarantine_path.exists()
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "restored"
        assert entry.tx_phase == "restored"
