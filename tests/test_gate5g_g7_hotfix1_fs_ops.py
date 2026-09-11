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
    rename_noreplace must safely fall back to strict no-replace and succeed.
    """
    src = tmp_path / "zfuse_src.txt"
    src.write_text("ZFUSE_COMPAT_PAYLOAD", encoding="utf-8")
    dst = tmp_path / "zfuse_dst.txt"

    st_before = os.stat(src)
    h_before = hashlib.sha256(src.read_bytes()).hexdigest()

    # Simulate filesystem returning EINVAL for RENAME_NOREPLACE (like zfuse.zfsv3)
    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    # Forbid naive os.rename fallback!
    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Naive os.rename was called as fallback!")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    rename_noreplace(src, dst)

    assert not src.exists(), "Source file must be moved/unlinked"
    assert dst.exists(), "Destination file must exist"
    assert dst.read_text(encoding="utf-8") == "ZFUSE_COMPAT_PAYLOAD"

    st_after = os.stat(dst)
    assert st_after.st_ino == st_before.st_ino, "Physical inode identity must be preserved"
    assert st_after.st_dev == st_before.st_dev, "Filesystem device must be preserved"
    assert st_after.st_size == st_before.st_size, "File size must match"
    assert hashlib.sha256(dst.read_bytes()).hexdigest() == h_before, "Content SHA256 must match"


def test_zfuse_compatibility_path_destination_collision_fails_safe(tmp_path: Path, monkeypatch):
    """
    When renameat2 returns EINVAL, destination collision must raise FileExistsError
    and NEVER overwrite target, leaving source intact.
    """
    src = tmp_path / "coll_src.txt"
    src.write_text("SOURCE_MUST_SURVIVE", encoding="utf-8")
    dst = tmp_path / "coll_dst.txt"
    dst.write_text("EXISTING_CANNOT_BE_OVERWRITTEN", encoding="utf-8")

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Naive os.rename was called as fallback!")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    with pytest.raises(FileExistsError):
        rename_noreplace(src, dst)

    assert src.exists()
    assert src.read_text(encoding="utf-8") == "SOURCE_MUST_SURVIVE"
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == "EXISTING_CANNOT_BE_OVERWRITTEN"


def test_zfuse_compatibility_concurrent_target_creation_race_safe(tmp_path: Path, monkeypatch):
    """
    Concurrent racing calls to rename_noreplace targeting the same destination
    under zfuse compatibility mode must never overwrite each other.
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

    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Naive os.rename was called as fallback!")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    def try_move(src_p: Path):
        try:
            rename_noreplace(src_p, common_target)
            return True, None
        except Exception as e:
            return False, e

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(try_move, src1)
        f2 = pool.submit(try_move, src2)
        r1 = f1.result()
        r2 = f2.result()

    successes = [r for r in (r1, r2) if r[0]]
    failures = [r for r in (r1, r2) if not r[0]]

    assert len(successes) == 1, "Exactly one thread must succeed"
    assert len(failures) == 1, "Exactly one thread must fail"
    assert isinstance(failures[0][1], FileExistsError), "Failing thread must receive FileExistsError"

    target_content = common_target.read_text(encoding="utf-8")
    if target_content == "RACE_CONTENT_1":
        assert not src1.exists()
        assert src2.exists()
        assert src2.read_text(encoding="utf-8") == "RACE_CONTENT_2"
    else:
        assert target_content == "RACE_CONTENT_2"
        assert not src2.exists()
        assert src1.exists()
        assert src1.read_text(encoding="utf-8") == "RACE_CONTENT_1"


def test_zfuse_compatibility_source_missing_raises_file_not_found(tmp_path: Path, monkeypatch):
    """When source does not exist, rename_noreplace raises FileNotFoundError."""
    src = tmp_path / "nonexistent.txt"
    dst = tmp_path / "dst.txt"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    with pytest.raises(FileNotFoundError):
        rename_noreplace(src, dst)


def test_zfuse_compatibility_exdev_raises_exdev(tmp_path: Path, monkeypatch):
    """Cross-device move must fail with EXDEV and never mutate."""
    src = tmp_path / "src_exdev.txt"
    src.write_text("EXDEV_DATA", encoding="utf-8")
    dst = tmp_path / "dst_exdev.txt"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    # Mock os.link to raise EXDEV
    def mock_link_exdev(s, d, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", mock_link_exdev)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)
    assert exc_info.value.errno == errno.EXDEV
    assert src.exists()
    assert not dst.exists()


def test_zfuse_compatibility_directory_fails_closed(tmp_path: Path, monkeypatch):
    """
    Directory moves on filesystems without RENAME_NOREPLACE cannot be guaranteed
    race-free against empty-directory overwrite, so they MUST fail closed with EOPNOTSUPP.
    """
    src_dir = tmp_path / "dir_src"
    src_dir.mkdir()
    (src_dir / "child.txt").write_text("CHILD", encoding="utf-8")
    dst_dir = tmp_path / "dir_dst"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Naive os.rename was called as fallback!")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src_dir, dst_dir)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP), errno.EPERM)
    assert src_dir.exists(), "Source directory must not be removed"
    assert not dst_dir.exists(), "Destination directory must not exist"


def test_zfuse_compatibility_symlink_success_and_safety(tmp_path: Path, monkeypatch):
    """Symlink move under zfuse compatibility must preserve symlink referent without overwrite."""
    target_file = tmp_path / "referent.txt"
    target_file.write_text("REFERENT_CONTENT", encoding="utf-8")

    src_link = tmp_path / "symlink_src.dat"
    os.symlink(str(target_file), str(src_link))
    dst_link = tmp_path / "symlink_dst.dat"

    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Naive os.rename was called as fallback!")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    rename_noreplace(src_link, dst_link)

    assert not src_link.exists(follow_symlinks=False)
    assert dst_link.is_symlink()
    assert os.readlink(str(dst_link)) == str(target_file)
    assert target_file.read_text(encoding="utf-8") == "REFERENT_CONTENT"


def test_rename_noreplace_at_zfuse_compatibility(tmp_path: Path, monkeypatch):
    """rename_noreplace_at must also support zfuse compatibility path."""
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
        rename_noreplace_at(sfd, "item.txt", dfd, "item_moved.txt")
    finally:
        os.close(sfd)
        os.close(dfd)

    assert not f_src.exists()
    assert (d_dst / "item_moved.txt").read_text(encoding="utf-8") == "PAYLOAD_AT"


def test_quarantine_execute_and_restore_under_zfuse_compatibility(tmp_path: Path, monkeypatch):
    """
    Simulates the entire Quarantine Execute and Restore sequence where the filesystem
    returns EINVAL for renameat2 (like zfuse), verifying:
    1. Source file moves to quarantine target.
    2. Keep file remains intact.
    3. Target exists with exact content and SHA256.
    4. Restore moves quarantine target back to original destination.
    5. Quarantine source is removed after restore.
    6. Restored SHA256 and size match original baseline.
    """
    data_dir = tmp_path / "data"
    quarantine_dir = tmp_path / "quarantine"
    data_dir.mkdir()
    quarantine_dir.mkdir()

    source_file = data_dir / "group1_fileA.dat"
    source_file.write_text("BYTE_IDENTICAL_DUPLICATE_PAYLOAD", encoding="utf-8")
    keep_file = data_dir / "group1_fileB.dat"
    keep_file.write_text("BYTE_IDENTICAL_DUPLICATE_PAYLOAD", encoding="utf-8")

    orig_sha256 = hashlib.sha256(source_file.read_bytes()).hexdigest()
    orig_size = source_file.stat().st_size

    q_target = quarantine_dir / "group1_fileA.q-1.dat"

    # Simulate filesystem returning EINVAL for RENAME_NOREPLACE (zfuse)
    def mock_zfuse_einval(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse_einval)

    # Forbid naive os.rename!
    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Naive os.rename called!")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    # Execute quarantine (app/execution/executor.py pattern)
    rename_noreplace(source_file, q_target)

    assert not source_file.exists(), "Quarantined source must no longer exist in data dir"
    assert keep_file.exists(), "Protected keep file must remain in data dir"
    assert q_target.exists(), "Quarantine target file must exist"
    assert hashlib.sha256(q_target.read_bytes()).hexdigest() == orig_sha256
    assert q_target.stat().st_size == orig_size

    # Execute restore (app/service.py restore pattern)
    rename_noreplace(q_target, source_file)

    assert source_file.exists(), "Restored file must exist at original destination"
    assert not q_target.exists(), "Quarantined source must be removed after restore"
    assert hashlib.sha256(source_file.read_bytes()).hexdigest() == orig_sha256
    assert source_file.stat().st_size == orig_size
    assert keep_file.read_text(encoding="utf-8") == "BYTE_IDENTICAL_DUPLICATE_PAYLOAD"



def test_einval_genuine_semantic_error_is_not_swallowed(tmp_path: Path, monkeypatch):
    """
    If the filesystem DOES support RENAME_NOREPLACE, a genuine EINVAL (e.g. invalid arguments)
    must NOT trigger fallback and must raise OSError(EINVAL).
    """
    src = tmp_path / "src_real_einval.txt"
    src.write_text("DATA", encoding="utf-8")
    dst = tmp_path / "dst_real_einval.txt"

    call_count = 0

    def mock_native_with_genuine_einval(s, d):
        nonlocal call_count
        call_count += 1
        s_str = os.fsdecode(s)
        # Real operation on src_real_einval.txt returns EINVAL (genuine error)
        if "src_real_einval" in s_str:
            ctypes.set_errno(errno.EINVAL)
            return -1
        # Probe call on disposable probe file returns 0 (capability supported)
        return 0

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_native_with_genuine_einval)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno == errno.EINVAL, f"Expected EINVAL, got {exc_info.value}"


def test_false_positive_enoent_probe_regression(tmp_path: Path, monkeypatch):
    """
    REGRESSION: Confirmed real-NAS defect where:
    - Real operation on existing source returns EINVAL (zfuse lacks FUSE_RENAME2)
    - Probing with a nonexistent source returns ENOENT (Linux VFS dcache lookup fails before rename2)
    Old probe incorrectly interpreted ENOENT as 'capability supported', skipping fallback and re-raising EINVAL.
    New probe must NOT conclude capability supported from ENOENT, must detect unsupported flag on existing disposable file,
    and must safely enter fallback and succeed.
    """
    src = tmp_path / "real_file.dat"
    src.write_text("IMPORTANT_USER_PAYLOAD", encoding="utf-8")
    dst = tmp_path / "quarantine_target.dat"

    # Simulate real Linux VFS + zfuse behavior:
    # If path does not exist on disk, VFS returns ENOENT before rename2 is called.
    # If path DOES exist on disk, zfuse returns EINVAL on renameat2 flags=1.
    def mock_vfs_zfuse_rename(s, d):
        src_path = os.fsdecode(s)
        if not os.path.exists(src_path):
            ctypes.set_errno(errno.ENOENT)
            return -1
        ctypes.set_errno(errno.EINVAL)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_vfs_zfuse_rename)

    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Naive os.rename called as fallback!")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    # Under old probe: raises OSError: [Errno 22] Invalid argument
    # Under new probe: must detect lack of support and safely enter fallback!
    rename_noreplace(src, dst)

    assert not src.exists(), "Source file must be moved"
    assert dst.exists(), "Destination file must exist"
    assert dst.read_text(encoding="utf-8") == "IMPORTANT_USER_PAYLOAD"


def test_rename_noreplace_at_false_positive_enoent_probe_regression(tmp_path: Path, monkeypatch):
    """
    REGRESSION for rename_noreplace_at with realistic VFS + zfuse behavior.
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
        rename_noreplace_at(sfd, "item.txt", dfd, "item_moved.txt")
    finally:
        os.close(sfd)
        os.close(dfd)

    assert not f_src.exists()
    assert (d_dst / "item_moved.txt").read_text(encoding="utf-8") == "PAYLOAD_AT_ZFUSE"


def test_probe_temporary_files_are_always_cleaned_up(tmp_path: Path, monkeypatch):
    """Probe must clean up all temporary files in both supported and unsupported outcomes."""
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

    rename_noreplace(src, dst)

    # Check no leftover probe files in tmp_path
    leftovers = [f.name for f in tmp_path.iterdir() if f.name.startswith(".__probe_noreplace_")]
    assert len(leftovers) == 0, f"Leftover probe files found: {leftovers}"


def test_supported_native_rename_uses_native_path_and_not_fallback(tmp_path: Path, monkeypatch):
    """When native renameat2 succeeds (returns 0), fallback must NOT be used."""
    src = tmp_path / "src.txt"
    src.write_text("NATIVE_CONTENT", encoding="utf-8")
    dst = tmp_path / "dst.txt"

    fallback_called = False

    def mock_fallback(*args, **kwargs):
        nonlocal fallback_called
        fallback_called = True
        raise AssertionError("Fallback should not be called when native rename succeeds!")

    monkeypatch.setattr(fs_ops_mod, "_execute_safe_noreplace_fallback", mock_fallback)

    rename_noreplace(src, dst)
    assert not fallback_called
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

    # Force probe file creation to fail (e.g. permission error / unwritable target directory)
    monkeypatch.setattr(fs_ops_mod, "_probe_rename_noreplace_supported", lambda *args, **kwargs: None)

    fallback_called = False
    def mock_fallback(*args, **kwargs):
        nonlocal fallback_called
        fallback_called = True
    monkeypatch.setattr(fs_ops_mod, "_execute_safe_noreplace_fallback", mock_fallback)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno == errno.EINVAL
    assert not fallback_called, "Uncertain capability must fail closed and not enter fallback"


def test_rollback_replacement_race_does_not_delete_unrelated_target(tmp_path: Path, monkeypatch):
    """
    BLOCKER A: If source unlink fails, and before rollback another actor replaced target
    with unrelated third-party content, the implementation MUST NOT unlink the replacement target!
    """
    src = tmp_path / "src_important.txt"
    src.write_text("ORIGINAL_USER_DATA", encoding="utf-8")
    dst = tmp_path / "dst_target.txt"

    def mock_zfuse(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse)

    real_unlink = os.unlink

    def hooked_unlink(path, *args, **kwargs):
        p_str = str(path)
        if "src_important" in p_str:
            # Simulate race: another actor removes dst and creates third-party file before unlink fails
            real_unlink(dst)
            dst.write_text("THIRD_PARTY_REPLACEMENT_CONTENT", encoding="utf-8")
            raise OSError(errno.EIO, "Simulated I/O error unlinking source")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", hooked_unlink)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno == errno.EIO
    assert src.exists(), "Source file must remain intact"
    assert src.read_text(encoding="utf-8") == "ORIGINAL_USER_DATA"
    assert dst.exists(), "Third-party replacement target must NOT be deleted by fallback rollback!"
    assert dst.read_text(encoding="utf-8") == "THIRD_PARTY_REPLACEMENT_CONTENT"


def test_ordinary_source_unlink_failure_preserves_both_and_propagates(tmp_path: Path, monkeypatch):
    """
    BLOCKER A: On source unlink failure without replacement, source data is preserved,
    destination is NOT deleted (preserving dual-link for safety over cosmetic rollback),
    and failure is propagated.
    """
    src = tmp_path / "src_keep.txt"
    src.write_text("CRITICAL_PAYLOAD", encoding="utf-8")
    dst = tmp_path / "dst_keep.txt"

    def mock_zfuse(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse)

    real_unlink = os.unlink

    def hooked_unlink(path, *args, **kwargs):
        if "src_keep" in str(path):
            raise OSError(errno.EACCES, "Permission denied unlinking source")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", hooked_unlink)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno == errno.EACCES
    assert src.exists(), "Source must be preserved"
    assert src.read_text(encoding="utf-8") == "CRITICAL_PAYLOAD"
    assert dst.exists(), "Destination must not be cosmetically deleted"
    assert dst.read_text(encoding="utf-8") == "CRITICAL_PAYLOAD"


def test_success_path_destination_replacement_race(tmp_path: Path, monkeypatch):
    """
    BLOCKER B: If target is replaced after link() but before source-removal stage,
    the implementation:
    - MUST NOT unlink source (preventing original source data loss)
    - MUST NOT return false success
    - MUST NOT delete the unrelated replacement target
    - MUST raise an OSError (e.g. ESTALE)
    """
    src = tmp_path / "src_original.txt"
    src.write_text("ORIGINAL_PAYLOAD", encoding="utf-8")
    dst = tmp_path / "dst_target.txt"

    def mock_zfuse(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse)

    real_link = os.link
    real_unlink = os.unlink

    def hooked_link(s, d, *args, **kwargs):
        res = real_link(s, d, *args, **kwargs)
        # Immediately after link succeeds, simulate another actor replacing dst with unrelated file!
        real_unlink(dst)
        dst.write_text("UNRELATED_THIRD_PARTY_OBJECT", encoding="utf-8")
        return res

    monkeypatch.setattr(os, "link", hooked_link)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(src, dst)

    assert exc_info.value.errno in (errno.ESTALE, errno.EIO, errno.EBUSY)
    assert src.exists(), "Original source must NOT be unlinked when destination was replaced!"
    assert src.read_text(encoding="utf-8") == "ORIGINAL_PAYLOAD"
    assert dst.exists(), "Replacement destination must remain untouched"
    assert dst.read_text(encoding="utf-8") == "UNRELATED_THIRD_PARTY_OBJECT"


def test_rename_noreplace_at_rollback_replacement_race(tmp_path: Path, monkeypatch):
    """BLOCKER A for rename_noreplace_at: does not delete replaced destination on rollback."""
    d_src = tmp_path / "dir_src"
    d_src.mkdir()
    d_dst = tmp_path / "dir_dst"
    d_dst.mkdir()

    f_src = d_src / "item_src.txt"
    f_src.write_text("AT_ORIGINAL", encoding="utf-8")

    sfd = os.open(str(d_src), os.O_RDONLY | os.O_DIRECTORY)
    dfd = os.open(str(d_dst), os.O_RDONLY | os.O_DIRECTORY)

    def mock_at_einval(s_fd, s, d_fd, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_AT_IMPL", mock_at_einval)

    real_unlink = os.unlink

    def hooked_unlink(path, *args, **kwargs):
        if "item_src" in str(path):
            real_unlink("item_dst.txt", dir_fd=dfd)
            (d_dst / "item_dst.txt").write_text("AT_REPLACED_CONTENT", encoding="utf-8")
            raise OSError(errno.EIO, "I/O error on source unlink")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", hooked_unlink)

    try:
        with pytest.raises(OSError) as exc_info:
            rename_noreplace_at(sfd, "item_src.txt", dfd, "item_dst.txt")
        assert exc_info.value.errno == errno.EIO
        assert f_src.exists()
        assert (d_dst / "item_dst.txt").exists()
        assert (d_dst / "item_dst.txt").read_text(encoding="utf-8") == "AT_REPLACED_CONTENT"
    finally:
        os.close(sfd)
        os.close(dfd)


def test_rename_noreplace_at_success_path_destination_replacement_race(tmp_path: Path, monkeypatch):
    """BLOCKER B for rename_noreplace_at: prevents source deletion if destination was replaced."""
    d_src = tmp_path / "dir_src"
    d_src.mkdir()
    d_dst = tmp_path / "dir_dst"
    d_dst.mkdir()

    f_src = d_src / "item_src.txt"
    f_src.write_text("AT_PAYLOAD_SAFE", encoding="utf-8")

    sfd = os.open(str(d_src), os.O_RDONLY | os.O_DIRECTORY)
    dfd = os.open(str(d_dst), os.O_RDONLY | os.O_DIRECTORY)

    def mock_at_einval(s_fd, s, d_fd, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_AT_IMPL", mock_at_einval)

    real_link = os.link
    real_unlink = os.unlink

    def hooked_link(s, d, *args, **kwargs):
        res = real_link(s, d, *args, **kwargs)
        real_unlink("item_dst.txt", dir_fd=dfd)
        (d_dst / "item_dst.txt").write_text("AT_UNRELATED_THIRD_PARTY", encoding="utf-8")
        return res

    monkeypatch.setattr(os, "link", hooked_link)

    try:
        with pytest.raises(OSError) as exc_info:
            rename_noreplace_at(sfd, "item_src.txt", dfd, "item_dst.txt")
        assert exc_info.value.errno in (errno.ESTALE, errno.EIO)
        assert f_src.exists()
        assert f_src.read_text(encoding="utf-8") == "AT_PAYLOAD_SAFE"
        assert (d_dst / "item_dst.txt").read_text(encoding="utf-8") == "AT_UNRELATED_THIRD_PARTY"
    finally:
        os.close(sfd)
        os.close(dfd)


def test_symlink_replacement_and_rollback_safety(tmp_path: Path, monkeypatch):
    """Symlink fallback must not delete replaced target on rollback and must detect replacement."""
    referent = tmp_path / "ref.txt"
    referent.write_text("REFERENT", encoding="utf-8")
    src_sym = tmp_path / "sym_src"
    os.symlink(str(referent), str(src_sym))
    dst_sym = tmp_path / "sym_dst"

    def mock_zfuse(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse)

    real_unlink = os.unlink

    def hooked_unlink(path, *args, **kwargs):
        if "sym_src" in str(path):
            real_unlink(dst_sym)
            dst_sym.write_text("REPLACED_TARGET_NOT_SYMLINK", encoding="utf-8")
            raise OSError(errno.EIO, "Failed to unlink sym_src")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", hooked_unlink)

    with pytest.raises(OSError):
        rename_noreplace(src_sym, dst_sym)

    assert src_sym.is_symlink(), "Source symlink must be preserved"
    assert dst_sym.exists(), "Replaced target must not be deleted by rollback"
    assert dst_sym.read_text(encoding="utf-8") == "REPLACED_TARGET_NOT_SYMLINK"


def test_special_inode_fifo_fails_closed(tmp_path: Path, monkeypatch):
    """Special inode types (FIFO, socket, device) must fail closed with EOPNOTSUPP."""
    fifo_path = tmp_path / "test_pipe.fifo"
    try:
        os.mkfifo(str(fifo_path))
    except (OSError, AttributeError):
        pytest.skip("mkfifo not supported on this filesystem/platform")

    dst = tmp_path / "dst_pipe.fifo"

    def mock_zfuse(s, d):
        ctypes.set_errno(errno.EINVAL)
        return -1
    monkeypatch.setattr(fs_ops_mod, "_RENAME_IMPL", mock_zfuse)

    with pytest.raises(OSError) as exc_info:
        rename_noreplace(fifo_path, dst)

    assert exc_info.value.errno in (errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP))
    assert fifo_path.exists(), "Special inode must not be removed"
    assert not dst.exists()



