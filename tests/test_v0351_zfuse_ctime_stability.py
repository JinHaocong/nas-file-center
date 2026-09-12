from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest

import app.planning.stale as stale_module
import app.service as service_module
from app.exceptions import StateConflictError
from app.planning.stale import capture_source_snapshot, verify_item_freshness


def _touch_ctime_only(path):
    """Advance ctime without changing content, size, inode, or mtime."""
    before = os.lstat(path)
    os.chmod(path, stat.S_IMODE(before.st_mode), follow_symlinks=False)
    after = os.lstat(path)
    assert after.st_dev == before.st_dev
    assert after.st_ino == before.st_ino
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ctime_ns != before.st_ctime_ns


def test_freeze_hash_allows_ctime_only_change_during_descriptor_hash(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    src = root / "sample.txt"
    payload = b"ZFUSE_READ_CTIME_PAYLOAD"
    src.write_bytes(payload)
    snap = capture_source_snapshot(src, [root])
    expected = hashlib.sha256(payload).hexdigest()

    real_hash = service_module._descriptor_sha256

    def hash_then_advance_ctime(fd):
        result = real_hash(fd)
        _touch_ctime_only(src)
        return result

    monkeypatch.setattr(service_module, "_descriptor_sha256", hash_then_advance_ctime)

    assert service_module._freeze_capture_stable_quarantine_hash(src, snap, [root]) == expected


def test_freeze_hash_still_rejects_mtime_change_during_descriptor_hash(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    src = root / "sample.txt"
    src.write_bytes(b"MUTATION_GUARD")
    snap = capture_source_snapshot(src, [root])

    real_hash = service_module._descriptor_sha256

    def hash_then_change_mtime(fd):
        result = real_hash(fd)
        st = os.lstat(src)
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000), follow_symlinks=False)
        return result

    monkeypatch.setattr(service_module, "_descriptor_sha256", hash_then_change_mtime)

    with pytest.raises(StateConflictError):
        service_module._freeze_capture_stable_quarantine_hash(src, snap, [root])


def test_freshness_allows_ctime_only_change_when_sha256_is_authoritative(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    src = root / "sample.txt"
    payload = b"STABLE_CONTENT"
    src.write_bytes(payload)

    snap = capture_source_snapshot(src, [root])
    expected_hash = hashlib.sha256(payload).hexdigest()

    real_sha256 = stale_module.hashlib.sha256
    advanced = False

    class HashProxy:
        def __init__(self):
            self.inner = real_sha256()

        def update(self, chunk):
            nonlocal advanced
            self.inner.update(chunk)
            if not advanced:
                advanced = True
                _touch_ctime_only(src)

        def hexdigest(self):
            return self.inner.hexdigest()

    monkeypatch.setattr(stale_module.hashlib, "sha256", HashProxy)

    ok, detail = verify_item_freshness(
        item_id=1,
        source_path=str(src),
        operation="quarantine",
        expected_device=snap["device"],
        expected_inode=snap["inode"],
        expected_size=snap["size"],
        expected_mtime_ns=snap["mtime_ns"],
        expected_hash=expected_hash,
        metadata_json=json.dumps({"snapshot": snap}),
        allowed_roots=[root],
        check_hash=True,
    )

    assert advanced is True
    assert ok is True
    assert detail is None


def test_freshness_still_rejects_same_size_same_mtime_content_change(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    src = root / "sample.txt"
    original = b"ORIGINAL"
    tampered = b"TAMPERED"
    assert len(original) == len(tampered)
    src.write_bytes(original)

    snap = capture_source_snapshot(src, [root])
    expected_hash = hashlib.sha256(original).hexdigest()

    src.write_bytes(tampered)
    st = os.lstat(src)
    os.utime(src, ns=(st.st_atime_ns, snap["mtime_ns"]), follow_symlinks=False)

    ok, detail = verify_item_freshness(
        item_id=1,
        source_path=str(src),
        operation="quarantine",
        expected_device=snap["device"],
        expected_inode=snap["inode"],
        expected_size=snap["size"],
        expected_mtime_ns=snap["mtime_ns"],
        expected_hash=expected_hash,
        metadata_json=json.dumps({"snapshot": snap}),
        allowed_roots=[root],
        check_hash=True,
    )

    assert ok is False
    assert detail is not None
    assert detail.reason == "hash_changed"
