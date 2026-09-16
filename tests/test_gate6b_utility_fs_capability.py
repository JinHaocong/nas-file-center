from __future__ import annotations

import ctypes
import errno
import os

import app.fs_ops as fs_ops


def _open_dir(path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def test_probe_eexist_plus_cross_name_support_means_native_support_and_does_not_change_namespace(
    tmp_path,
    monkeypatch,
):
    child = tmp_path / "C"
    child.mkdir()
    before = os.lstat(child)
    confirmation_calls: list[int] = []

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        assert source_fd == target_fd
        assert source_name == b"C"
        assert target_name == b"C"
        ctypes.set_errno(errno.EEXIST)
        return -1

    def fake_cross_name_probe(*, dir_fd=None, **kwargs):
        assert dir_fd is not None
        confirmation_calls.append(dir_fd)
        return True

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    monkeypatch.setattr(fs_ops, "_probe_rename_noreplace_supported", fake_cross_name_probe)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)

    after = os.lstat(child)
    assert result is True
    assert len(confirmation_calls) == 1
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )
    assert sorted(entry.name for entry in os.scandir(tmp_path)) == ["C"]


def test_probe_same_entry_eexist_fails_closed_when_cross_name_probe_is_unsupported(
    tmp_path,
    monkeypatch,
):
    """Regression for real zfuse/fuseblk: same-entry EEXIST is not proof of MOVE support."""
    child = tmp_path / "C"
    child.mkdir()
    before = os.lstat(child)
    confirmation_calls: list[int] = []

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        assert source_fd == target_fd
        assert source_name == b"C"
        assert target_name == b"C"
        ctypes.set_errno(errno.EEXIST)
        return -1

    def fake_cross_name_probe(*, dir_fd=None, **kwargs):
        assert dir_fd is not None
        confirmation_calls.append(dir_fd)
        return False

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    monkeypatch.setattr(fs_ops, "_probe_rename_noreplace_supported", fake_cross_name_probe)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)

    after = os.lstat(child)
    assert result is False
    assert len(confirmation_calls) == 1
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )
    assert sorted(entry.name for entry in os.scandir(tmp_path)) == ["C"]


def test_probe_does_not_grant_support_when_cross_name_probe_cleanup_is_unresolved(
    tmp_path,
    monkeypatch,
):
    """A disposable probe that cannot be cleaned up must never grant Utility mutation authority."""
    child = tmp_path / "C"
    child.mkdir()
    child_before = os.lstat(child)

    token_bytes = b"gate6b!!"
    token = token_bytes.hex()
    probe_src_name = f".__probe_noreplace_src_{token}"
    probe_dst_name = f".__probe_noreplace_dst_{token}"
    real_unlink = os.unlink

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        if source_name == target_name == b"C":
            ctypes.set_errno(errno.EEXIST)
            return -1

        assert source_fd == target_fd
        assert source_name == os.fsencode(probe_src_name)
        assert target_name == os.fsencode(probe_dst_name)
        os.rename(
            source_name,
            target_name,
            src_dir_fd=source_fd,
            dst_dir_fd=target_fd,
        )
        return 0

    def fake_unlink(path, *args, **kwargs):
        if os.fspath(path) == probe_dst_name:
            raise OSError(errno.EIO, "simulated unresolved probe cleanup")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    monkeypatch.setattr(fs_ops.os, "urandom", lambda _n: token_bytes)
    monkeypatch.setattr(fs_ops.os, "unlink", fake_unlink)

    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)

    child_after = os.lstat(child)
    assert result is None
    assert (child_after.st_dev, child_after.st_ino, child_after.st_mode) == (
        child_before.st_dev,
        child_before.st_ino,
        child_before.st_mode,
    )
    assert not (tmp_path / probe_src_name).exists()
    assert (tmp_path / probe_dst_name).exists()


def test_probe_eopnotsupp_means_unsupported(tmp_path, monkeypatch):
    (tmp_path / "C").mkdir()

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        ctypes.set_errno(errno.EOPNOTSUPP)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)

    assert result is False


def test_probe_unknown_errno_returns_none(tmp_path, monkeypatch):
    (tmp_path / "C").mkdir()

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        ctypes.set_errno(errno.EIO)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)

    assert result is None
