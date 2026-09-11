from __future__ import annotations

import concurrent.futures
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import stat
import sys

import pytest

import app.fs_ops as fs_ops_mod
from app.fs_ops import rename_noreplace, rename_noreplace_at


def test_native_path_regular_file(tmp_path: Path):
    """Native path succeeds for regular files when supported."""
    src = tmp_path / "src.txt"
    src.write_text("NATIVE_CONTENT", encoding="utf-8")
    dst = tmp_path / "dst.txt"

    rename_noreplace(src, dst)
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "NATIVE_CONTENT"


def test_native_path_existing_destination_raises_file_exists(tmp_path: Path):
    """Native path raises FileExistsError and does not overwrite existing destination."""
    src = tmp_path / "src.txt"
    src.write_text("SOURCE_DATA", encoding="utf-8")
    dst = tmp_path / "dst.txt"
    dst.write_text("EXISTING_DATA", encoding="utf-8")

    with pytest.raises(FileExistsError):
        rename_noreplace(src, dst)

    assert src.read_text(encoding="utf-8") == "SOURCE_DATA"
    assert dst.read_text(encoding="utf-8") == "EXISTING_DATA"


def test_zfuse_compatibility_path_regular_file_success(tmp_path: Path, monkeypatch):
    """
    When renameat2/renamex_np returns EINVAL (unsupported flag/filesystem on zfuse),
    rename_noreplace must fail closed with EOPNOTSUPP and strictly ZERO fallback.
    """
    src = tmp_path / "zfuse_src.txt"
    src.write_text("ZFUSE_COMPAT_PAYLOAD", encoding="utf-8")
    dst = tmp_path / "zfuse_dst.txt"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    assert src.exists(), "Source file must remain intact with zero fallback"
    assert not dst.exists(), "Destination file must not be created"


def test_zfuse_compatibility_path_destination_collision_fails_safe(tmp_path: Path, monkeypatch):
    """
    When renameat2 returns EINVAL, unsupported filesystem raises EOPNOTSUPP
    leaving both source and existing destination intact.
    """
    src = tmp_path / "coll_src.txt"
    src.write_text("SOURCE_MUST_SURVIVE", encoding="utf-8")
    dst = tmp_path / "coll_dst.txt"
    dst.write_text("EXISTING_CANNOT_BE_OVERWRITTEN", encoding="utf-8")

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "SOURCE_MUST_SURVIVE"
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == "EXISTING_CANNOT_BE_OVERWRITTEN"


def test_zfuse_compatibility_concurrent_target_creation_race_safe(tmp_path: Path, monkeypatch):
    """
    Concurrent calls on unsupported filesystem both fail closed with EOPNOTSUPP.
    """
    src1 = tmp_path / "race_src1.txt"
    src1.write_text("RACE_CONTENT_1", encoding="utf-8")
    src2 = tmp_path / "race_src2.txt"
    src2.write_text("RACE_CONTENT_2", encoding="utf-8")
    common_target = tmp_path / "race_target.txt"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    for s in (src1, src2):
        with pytest.raises(OSError) as exc_info:
            rename_noreplace(s, common_target)
        assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))

    assert src1.exists()
    assert src2.exists()
    assert not common_target.exists()


def test_zfuse_compatibility_source_missing_raises_file_not_found(tmp_path: Path, monkeypatch):
    """When source does not exist, rename_noreplace raises FileNotFoundError."""
    src = tmp_path / "nonexistent.txt"
    dst = tmp_path / "dst.txt"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.ENOENT)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    with pytest.raises(FileNotFoundError):
        rename_noreplace(src, dst)


def test_zfuse_compatibility_exdev_raises_exdev(tmp_path: Path, monkeypatch):
    """Cross-device move must fail with EXDEV and never mutate."""
    src = tmp_path / "src_exdev.txt"
    src.write_text("EXDEV_DATA", encoding="utf-8")
    dst = tmp_path / "dst_exdev.txt"

    def mock_zfuse_exdev(s, d):
        ctypes.set_errno(errno.EXDEV)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_exdev)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)
    assert exc_info.value.errno == errno.EXDEV
    assert src.exists()
    assert not dst.exists()


def test_zfuse_compatibility_directory_fails_closed(tmp_path: Path, monkeypatch):
    """
    Directory moves on filesystems without RENAME_NOREPLACE strictly fail closed with EOPNOTSUPP.
    """
    src_dir = tmp_path / "dir_src"
    src_dir.mkdir()
    (src_dir / "child.txt").write_text("CHILD", encoding="utf-8")
    dst_dir = tmp_path / "dir_dst"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src_dir, dst_dir)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    assert src_dir.exists()
    assert not dst_dir.exists()


def test_zfuse_compatibility_symlink_fails_closed(tmp_path: Path, monkeypatch):
    """Symlink move on filesystems without RENAME_NOREPLACE fails closed with EOPNOTSUPP."""
    target_file = tmp_path / "referent.txt"
    target_file.write_text("REFERENT_CONTENT", encoding="utf-8")

    src_link = tmp_path / "symlink_src.dat"
    os.symlink(str(target_file), str(src_link))
    dst_link = tmp_path / "symlink_dst.dat"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src_link, dst_link)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    assert src_link.is_symlink()
    assert not dst_link.exists(follow_symlinks=False)


def test_rename_noreplace_at_zfuse_compatibility_fails_closed(tmp_path: Path, monkeypatch):
    """rename_noreplace_at fails closed with EOPNOTSUPP when unsupported."""
    d_src = tmp_path / "dir_src"
    d_src.mkdir()
    d_dst = tmp_path / "dir_dst"
    d_dst.mkdir()

    f_src = d_src / "item.txt"
    f_src.write_text("PAYLOAD_AT", encoding="utf-8")

    sfd = os.open(str(d_src), os.O_RDONLY | os.O_DIRECTORY)
    dfd = os.open(str(d_dst), os.O_RDONLY | os.O_DIRECTORY)

    def mock_at_einval(s_fd, s, d_fd, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_AT_IMPL", mock_at_einval)

    try:
        with pytest.raises(OSError) as exc_info:
            rename_noreplace_at(sfd, "item.txt", dfd, "item_moved.txt")
        assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    finally:
        os.close(sfd)
        os.close(dfd)

    assert f_src.exists()
    assert not (d_dst / "item_moved.txt").exists()


def test_einval_genuine_semantic_error_is_not_swallowed(tmp_path: Path, monkeypatch):
    """
    If the filesystem DOES support RENAME_NOREPLACE, a genuine EINVAL
    must raise OSError(EINVAL).
    """
    src = tmp_path / "src_real_einval.txt"
    src.write_text("DATA", encoding="utf-8")
    dst = tmp_path / "dst_real_einval.txt"

    def mock_native_with_genuine_einval(s, d):
        s_str = os.fsdecode(s)
        if "src_real_einval" in s_str:
            ctypes.set_errno(errno.EINVAL)
            return -1
        return 0

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_native_with_genuine_einval)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno == errno.EINVAL


def test_false_positive_enoent_probe_regression(tmp_path: Path, monkeypatch):
    """
    REGRESSION: When native returns EINVAL and probe detects unsupported capability,
    rename_noreplace raises EOPNOTSUPP without any check-then-unlink fallback.
    """
    src = tmp_path / "real_file.dat"
    src.write_text("IMPORTANT_USER_PAYLOAD", encoding="utf-8")
    dst = tmp_path / "quarantine_target.dat"

    def mock_vfs_zfuse_rename(s, d):
        src_path = os.fsdecode(s)
        if not os.path.exists(src_path):
            ctypes.set_errno(errno.ENOENT)
            return -1
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_vfs_zfuse_rename)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    assert src.exists()
    assert not dst.exists()


def test_rename_noreplace_at_false_positive_enoent_probe_regression(tmp_path: Path, monkeypatch):
    """
    REGRESSION for rename_noreplace_at with unsupported capability raises EOPNOTSUPP.
    """
    d_src = tmp_path / "dir_src"
    d_src.mkdir()
    d_dst = tmp_path / "dir_dst"
    d_dst.mkdir()

    f_src = d_src / "item.txt"
    f_src.write_text("PAYLOAD_AT_ZFUSE", encoding="utf-8")

    sfd = os.open(str(d_src), os.O_RDONLY | os.O_DIRECTORY)
    dfd = os.open(str(d_dst), os.O_RDONLY | os.O_DIRECTORY)

    def mock_vfs_zfuse_rename_at(s_fd, s, d_fd, d):
        s_name = os.fsdecode(s)
        try:
            os.stat(s_name, dir_fd=s_fd)
        except OSError:
            ctypes.set_errno(errno.ENOENT)
            return -1
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_AT_IMPL", mock_vfs_zfuse_rename_at)

    try:
        with pytest.raises(OSError) as exc_info:
            rename_noreplace_at(sfd, "item.txt", dfd, "item_moved.txt")
        assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    finally:
        os.close(sfd)
        os.close(dfd)

    assert f_src.exists()
    assert not (d_dst / "item_moved.txt").exists()


def test_probe_temporary_files_are_always_cleaned_up(tmp_path: Path, monkeypatch):
    """Probe must clean up all temporary files."""
    src = tmp_path / "src.txt"
    src.write_text("DATA", encoding="utf-8")
    dst = tmp_path / "dst.txt"

    def mock_vfs_zfuse(s, d):
        if not os.path.exists(os.fsdecode(s)):
            ctypes.set_errno(errno.ENOENT)
            return -1
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_vfs_zfuse)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    leftovers = [f.name for f in tmp_path.iterdir() if f.name.startswith(".__probe_noreplace_")]
    assert len(leftovers) == 0, f"Leftover probe files found: {leftovers}"


def test_supported_native_rename_uses_native_path_and_not_fallback(tmp_path: Path):
    """When native renameat2 succeeds, it succeeds without raising."""
    src = tmp_path / "src.txt"
    src.write_text("NATIVE_CONTENT", encoding="utf-8")
    dst = tmp_path / "dst.txt"

    rename_noreplace(src, dst)
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "NATIVE_CONTENT"


def test_probe_fails_closed_when_capability_cannot_be_safely_determined(tmp_path: Path, monkeypatch):
    """If capability probe fails to determine capability safely, it must fail closed and raise original error."""
    src = tmp_path / "src.txt"
    src.write_text("DATA", encoding="utf-8")
    dst = tmp_path / "dst.txt"

    def mock_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_einval)
    monkeypatch.setattr(fs_ops_mod, "_probe_rename_noreplace_supported", lambda *args, **kwargs: None)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno == errno.EINVAL
