from __future__ import annotations

import errno
import os
from pathlib import Path

from app.storage_optimization.capability import (
    FICLONE,
    StorageOptimizationCapability,
    probe_hardlink_capability,
    probe_reflink_capability,
)


def _probe_residue(root: Path) -> list[str]:
    return sorted(
        path.name
        for path in root.iterdir()
        if path.name.startswith(".__nfc_hardlink_probe_")
        or path.name.startswith(".__nfc_reflink_probe_")
    )


def test_hardlink_probe_positive_and_zero_residue(tmp_path: Path):
    result = probe_hardlink_capability(tmp_path, [tmp_path])

    assert result.capability is StorageOptimizationCapability.SUPPORTED
    assert result.supported is True
    assert result.reason == "hardlink_probe_pass"
    assert result.parent_device is not None
    assert result.parent_inode is not None
    assert _probe_residue(tmp_path) == []


def test_hardlink_probe_cross_filesystem_style_failure_is_unsupported(monkeypatch, tmp_path: Path):
    def fail_link(*_args, **_kwargs):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr("app.storage_optimization.capability.os.link", fail_link)

    result = probe_hardlink_capability(tmp_path, [tmp_path])

    assert result.capability is StorageOptimizationCapability.UNSUPPORTED
    assert "hardlink_probe_failed" in result.reason
    assert _probe_residue(tmp_path) == []


def test_hardlink_probe_outside_allowed_roots_is_unknown(tmp_path: Path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    result = probe_hardlink_capability(outside, [allowed])

    assert result.capability is StorageOptimizationCapability.UNKNOWN
    assert result.supported is False
    assert "parent_probe_failed" in result.reason
    assert _probe_residue(outside) == []


def test_reflink_probe_positive_proves_independent_inode_and_cow(monkeypatch, tmp_path: Path):
    def emulate_ficlone(dst_fd: int, request: int, src_fd: int):
        assert request == FICLONE
        src_pos = os.lseek(src_fd, 0, os.SEEK_CUR)
        dst_pos = os.lseek(dst_fd, 0, os.SEEK_CUR)
        try:
            os.lseek(src_fd, 0, os.SEEK_SET)
            payload = os.read(src_fd, 1024 * 1024)
            os.ftruncate(dst_fd, 0)
            os.lseek(dst_fd, 0, os.SEEK_SET)
            os.write(dst_fd, payload)
        finally:
            os.lseek(src_fd, src_pos, os.SEEK_SET)
            os.lseek(dst_fd, dst_pos, os.SEEK_SET)
        return 0

    monkeypatch.setattr("app.storage_optimization.capability.fcntl.ioctl", emulate_ficlone)

    result = probe_reflink_capability(tmp_path, [tmp_path])

    assert result.capability is StorageOptimizationCapability.SUPPORTED
    assert result.reason == "reflink_probe_pass"
    assert _probe_residue(tmp_path) == []


def test_reflink_probe_unsupported_ioctl_is_fail_closed(monkeypatch, tmp_path: Path):
    def unsupported(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "operation not supported")

    monkeypatch.setattr("app.storage_optimization.capability.fcntl.ioctl", unsupported)

    result = probe_reflink_capability(tmp_path, [tmp_path])

    assert result.capability is StorageOptimizationCapability.UNSUPPORTED
    assert "reflink_probe_failed" in result.reason
    assert _probe_residue(tmp_path) == []


def test_reflink_probe_ioctl_success_without_clone_is_unknown(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "app.storage_optimization.capability.fcntl.ioctl",
        lambda *_args, **_kwargs: 0,
    )

    result = probe_reflink_capability(tmp_path, [tmp_path])

    assert result.capability is StorageOptimizationCapability.UNKNOWN
    assert result.reason == "reflink_probe_identity_or_content_mismatch"
    assert _probe_residue(tmp_path) == []
