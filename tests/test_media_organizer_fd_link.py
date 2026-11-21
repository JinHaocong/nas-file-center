"""Tests for non-root inode-pinned hardlink publication."""
import errno
import os
from pathlib import Path

import pytest

from app.batch import media_organizer_fd_link as module


def test_unprivileged_proc_fd_fallback_links_the_pinned_inode(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    source.write_bytes(b"pinned-content")
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    calls = []
    actual = module._call_linkat

    def without_empty_path_capability(linkat, olddirfd, oldpath, newdirfd, newpath, flags):
        calls.append((olddirfd, oldpath, flags))
        if flags == module._AT_EMPTY_PATH:
            raise OSError(errno.ENOENT, "simulated missing CAP_DAC_READ_SEARCH")
        return actual(linkat, olddirfd, oldpath, newdirfd, newpath, flags)

    monkeypatch.setattr(module, "_call_linkat", without_empty_path_capability)
    target_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        module.link_pinned_inode_noreplace(source_fd, target_fd, "published.bin")
    finally:
        os.close(target_fd)
        os.close(source_fd)

    published = target_dir / "published.bin"
    assert published.read_bytes() == b"pinned-content"
    assert published.stat().st_ino == source.stat().st_ino
    assert calls[0] == (source_fd, b"", module._AT_EMPTY_PATH)
    assert calls[1][0] == module._AT_FDCWD
    assert calls[1][1] == f"/proc/self/fd/{source_fd}".encode()
    assert calls[1][2] == module._AT_SYMLINK_FOLLOW


def test_proc_fd_fallback_never_replaces_existing_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    source.write_bytes(b"source")
    (target_dir / "published.bin").write_bytes(b"foreign")
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    target_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    actual = module._call_linkat

    def no_empty_path(linkat, olddirfd, oldpath, newdirfd, newpath, flags):
        if flags == module._AT_EMPTY_PATH:
            raise OSError(errno.ENOENT, "simulated missing capability")
        return actual(linkat, olddirfd, oldpath, newdirfd, newpath, flags)

    monkeypatch.setattr(module, "_call_linkat", no_empty_path)
    try:
        with pytest.raises(FileExistsError):
            module.link_pinned_inode_noreplace(source_fd, target_fd, "published.bin")
    finally:
        os.close(target_fd)
        os.close(source_fd)

    assert (target_dir / "published.bin").read_bytes() == b"foreign"


def test_non_enoent_empty_path_failure_does_not_fallback(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    source.write_bytes(b"source")
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    target_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
    calls = []
    def fail(linkat, olddirfd, oldpath, newdirfd, newpath, flags):
        calls.append(flags)
        raise OSError(errno.EACCES, "not a capability-related ENOENT")
    monkeypatch.setattr(module, "_call_linkat", fail)
    try:
        with pytest.raises(PermissionError):
            module.link_pinned_inode_noreplace(source_fd, target_fd, "published.bin")
    finally:
        os.close(target_fd)
        os.close(source_fd)
    assert calls == [module._AT_EMPTY_PATH]
    assert not (target_dir / "published.bin").exists()
