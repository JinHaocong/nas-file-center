import hashlib
import json
import os
from pathlib import Path

import pytest

import app.planning.stale as stale_module
import app.quarantine.candidate as candidate_module
import app.service as service_module
from app.exceptions import StateConflictError
from app.planning.stale import capture_source_snapshot, verify_item_freshness
from app.quarantine.candidate import qualify_candidate_anchor_fd


class _StatWithCtime:
    def __init__(self, real_stat, ctime_delta_ns: int = 1_000):
        self._real_stat = real_stat
        self.st_ctime_ns = int(
            getattr(real_stat, "st_ctime_ns", real_stat.st_ctime * 1e9)
        ) + ctime_delta_ns
        self.st_ctime = real_stat.st_ctime + (ctime_delta_ns / 1e9)

    def __getattr__(self, name):
        return getattr(self._real_stat, name)


class _StatWithMtime:
    def __init__(self, real_stat, mtime_delta_ns: int = 1_000):
        self._real_stat = real_stat
        self.st_mtime_ns = int(
            getattr(real_stat, "st_mtime_ns", real_stat.st_mtime * 1e9)
        ) + mtime_delta_ns
        self.st_mtime = real_stat.st_mtime + (mtime_delta_ns / 1e9)

    def __getattr__(self, name):
        return getattr(self._real_stat, name)


def test_candidate_allows_read_induced_ctime_change_but_keeps_authoritative_facts(
    tmp_path: Path, monkeypatch
):
    """Real zfuse changes ctime after O_RDONLY hashing; that alone is not mutation."""
    path = tmp_path / "candidate.txt"
    payload = b"ZFUSE_CTIME_CANDIDATE"
    path.write_bytes(payload)
    st = os.stat(path)
    expected_hash = hashlib.sha256(payload).hexdigest()
    expected_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))

    real_fstat = candidate_module.os.fstat
    calls = 0

    def ctime_only_fstat(fd):
        nonlocal calls
        calls += 1
        current = real_fstat(fd)
        return _StatWithCtime(current) if calls >= 2 else current

    monkeypatch.setattr(candidate_module.os, "fstat", ctime_only_fstat)

    with open(path, "rb") as fp:
        assert qualify_candidate_anchor_fd(
            fp.fileno(),
            st.st_dev,
            st.st_ino,
            len(payload),
            expected_hash,
            expected_mtime_ns,
        ) is True


def test_candidate_still_rejects_mtime_change_during_hash(tmp_path: Path, monkeypatch):
    path = tmp_path / "candidate-mtime.txt"
    payload = b"MUST_FAIL_CLOSED_ON_MTIME"
    path.write_bytes(payload)
    st = os.stat(path)
    expected_hash = hashlib.sha256(payload).hexdigest()
    expected_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))

    real_fstat = candidate_module.os.fstat
    calls = 0

    def changed_mtime_fstat(fd):
        nonlocal calls
        calls += 1
        current = real_fstat(fd)
        return _StatWithMtime(current) if calls >= 2 else current

    monkeypatch.setattr(candidate_module.os, "fstat", changed_mtime_fstat)

    with open(path, "rb") as fp:
        assert qualify_candidate_anchor_fd(
            fp.fileno(),
            st.st_dev,
            st.st_ino,
            len(payload),
            expected_hash,
            expected_mtime_ns,
        ) is False


def test_freeze_hash_allows_ctime_only_change_during_descriptor_hash(
    tmp_path: Path, monkeypatch
):
    path = tmp_path / "freeze.txt"
    payload = b"ZFUSE_FREEZE_CTIME"
    path.write_bytes(payload)
    snapshot = capture_source_snapshot(path, [tmp_path])
    expected_hash = hashlib.sha256(payload).hexdigest()

    real_fstat = service_module.os.fstat
    calls = 0

    def ctime_only_fstat(fd):
        nonlocal calls
        calls += 1
        current = real_fstat(fd)
        return _StatWithCtime(current) if calls >= 2 else current

    monkeypatch.setattr(service_module.os, "fstat", ctime_only_fstat)

    assert service_module._freeze_capture_stable_quarantine_hash(
        path, snapshot, allowed_roots=[tmp_path]
    ) == expected_hash


def test_freeze_hash_still_rejects_mtime_change_during_descriptor_hash(
    tmp_path: Path, monkeypatch
):
    path = tmp_path / "freeze-mtime.txt"
    path.write_bytes(b"MUST_FAIL_CLOSED")
    snapshot = capture_source_snapshot(path, [tmp_path])

    real_fstat = service_module.os.fstat
    calls = 0

    def changed_mtime_fstat(fd):
        nonlocal calls
        calls += 1
        current = real_fstat(fd)
        return _StatWithMtime(current) if calls >= 2 else current

    monkeypatch.setattr(service_module.os, "fstat", changed_mtime_fstat)

    with pytest.raises(StateConflictError):
        service_module._freeze_capture_stable_quarantine_hash(
            path, snapshot, allowed_roots=[tmp_path]
        )


def test_freshness_allows_hash_read_induced_ctime_change(tmp_path: Path, monkeypatch):
    path = tmp_path / "fresh.txt"
    payload = b"ZFUSE_FRESHNESS_CTIME"
    path.write_bytes(payload)
    snapshot = capture_source_snapshot(path, [tmp_path])
    expected_hash = hashlib.sha256(payload).hexdigest()

    real_lstat = stale_module.os.lstat
    calls = 0

    def ctime_only_lstat(target):
        nonlocal calls
        calls += 1
        current = real_lstat(target)
        # verify_item_freshness performs its authoritative stat first, then the
        # pre-hash and post-hash lstat calls. Simulate zfuse changing only ctime
        # at/after the post-hash observation.
        return _StatWithCtime(current) if calls >= 3 else current

    monkeypatch.setattr(stale_module.os, "lstat", ctime_only_lstat)

    fresh, detail = verify_item_freshness(
        item_id=1,
        source_path=str(path),
        operation="quarantine",
        expected_device=snapshot["device"],
        expected_inode=snapshot["inode"],
        expected_size=snapshot["size"],
        expected_mtime_ns=snapshot["mtime_ns"],
        expected_hash=expected_hash,
        metadata_json=json.dumps({"snapshot": {**snapshot, "hash": expected_hash}}),
        allowed_roots=[tmp_path],
        check_hash=True,
    )

    assert fresh is True
    assert detail is None


def test_freshness_still_rejects_content_hash_change(tmp_path: Path):
    path = tmp_path / "fresh-hash.txt"
    payload = b"ORIGINAL_HASH_CONTENT"
    path.write_bytes(payload)
    snapshot = capture_source_snapshot(path, [tmp_path])

    fresh, detail = verify_item_freshness(
        item_id=2,
        source_path=str(path),
        operation="quarantine",
        expected_device=snapshot["device"],
        expected_inode=snapshot["inode"],
        expected_size=snapshot["size"],
        expected_mtime_ns=snapshot["mtime_ns"],
        expected_hash="0" * 64,
        metadata_json=json.dumps({"snapshot": snapshot}),
        allowed_roots=[tmp_path],
        check_hash=True,
    )

    assert fresh is False
    assert detail is not None
    assert detail.reason == "hash_changed"
