import hashlib
import os
import stat
import pytest
from app.quarantine.candidate import qualify_candidate_anchor_fd


def test_candidate_allows_legitimate_post_link_ctime_change_from_source_snapshot(tmp_path):
    f = tmp_path / "candidate.txt"
    content = b"GENUINE_DATA_PAYLOAD"
    f.write_bytes(content)
    h = hashlib.sha256(content).hexdigest()
    st = os.stat(f)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    with open(f, "rb") as fp:
        assert qualify_candidate_anchor_fd(fp.fileno(), st.st_dev, st.st_ino, len(content), h, mtime_ns) is True


def test_candidate_rejects_ctime_change_during_hash(tmp_path, monkeypatch):
    f = tmp_path / "candidate.txt"
    content = b"DATA" * 1024
    f.write_bytes(content)
    h = hashlib.sha256(content).hexdigest()
    st = os.stat(f)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))

    original_fstat = os.fstat
    fstat_call_count = 0

    def mock_fstat(fd):
        nonlocal fstat_call_count
        fstat_call_count += 1
        real_st = original_fstat(fd)
        if fstat_call_count > 1:
            # Simulate ctime mutation after hash
            class FakeStat:
                st_mode = real_st.st_mode
                st_dev = real_st.st_dev
                st_ino = real_st.st_ino
                st_size = real_st.st_size
                st_mtime_ns = getattr(real_st, "st_mtime_ns", int(real_st.st_mtime * 1e9))
                st_ctime_ns = getattr(real_st, "st_ctime_ns", int(real_st.st_ctime * 1e9)) + 1000
                st_mtime = real_st.st_mtime
                st_ctime = real_st.st_ctime + 0.001
            return FakeStat()
        return real_st

    monkeypatch.setattr(os, "fstat", mock_fstat)

    with open(f, "rb") as fp:
        assert qualify_candidate_anchor_fd(fp.fileno(), st.st_dev, st.st_ino, len(content), h, mtime_ns) is False


def test_candidate_rejects_identity_mismatches(tmp_path):
    f = tmp_path / "candidate.txt"
    content = b"GENUINE_DATA"
    f.write_bytes(content)
    h = hashlib.sha256(content).hexdigest()
    st = os.stat(f)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))

    with open(f, "rb") as fp:
        fd = fp.fileno()
        # Wrong dev
        assert qualify_candidate_anchor_fd(fd, st.st_dev + 1, st.st_ino, len(content), h, mtime_ns) is False
        # Wrong ino
        assert qualify_candidate_anchor_fd(fd, st.st_dev, st.st_ino + 1, len(content), h, mtime_ns) is False
        # Wrong size
        assert qualify_candidate_anchor_fd(fd, st.st_dev, st.st_ino, len(content) + 1, h, mtime_ns) is False
        # Wrong hash
        assert qualify_candidate_anchor_fd(fd, st.st_dev, st.st_ino, len(content), "badhash", mtime_ns) is False
        # Wrong mtime
        assert qualify_candidate_anchor_fd(fd, st.st_dev, st.st_ino, len(content), h, mtime_ns + 1000) is False
