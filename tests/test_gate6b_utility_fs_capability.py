from __future__ import annotations

import ctypes
import errno
import os

import app.fs_ops as fs_ops


def _open_dir(path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def test_probe_eexist_means_native_support_and_does_not_change_namespace(tmp_path, monkeypatch):
    child = tmp_path / "C"
    child.mkdir()
    before = os.lstat(child)

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        assert source_fd == target_fd
        assert source_name == b"C"
        assert target_name == b"C"
        ctypes.set_errno(errno.EEXIST)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)

    after = os.lstat(child)
    assert result is True
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )
    assert sorted(entry.name for entry in os.scandir(tmp_path)) == ["C"]


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
