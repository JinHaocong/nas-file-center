from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
import app.execution.executor as executor_module
import app.fs_ops as fs_ops
from app.batch.plans import OperationItem
from app.execution.executor import execute_item


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _strict_directory_rename(real_rename):
    def fake(src, dst, *args, src_dir_fd=None, dst_dir_fd=None, **kwargs):
        try:
            os.stat(dst, dir_fd=dst_dir_fd, follow_symlinks=False)
            target_exists = True
        except FileNotFoundError:
            target_exists = False
        if target_exists:
            raise FileExistsError(errno.EEXIST, "simulated zfuse strict directory rename", os.fspath(dst))
        return real_rename(
            src,
            dst,
            *args,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            **kwargs,
        )
    return fake


def test_directory_compat_probe_accepts_ordinary_rename_only_when_existing_target_is_preserved(
    tmp_path,
    monkeypatch,
):
    source_parent = tmp_path / "source"
    target_parent = tmp_path / "target"
    source_parent.mkdir()
    target_parent.mkdir()

    real_rename = os.rename
    monkeypatch.setattr(fs_ops.os, "rename", _strict_directory_rename(real_rename))

    source_fd = _open_dir(source_parent)
    target_fd = _open_dir(target_parent)
    try:
        assert fs_ops.probe_directory_rename_noreplace_compat_at(source_fd, target_fd) is True
    finally:
        os.close(source_fd)
        os.close(target_fd)

    assert list(source_parent.iterdir()) == []
    assert list(target_parent.iterdir()) == []


def test_directory_compat_probe_rejects_posix_replace_semantics_and_leaves_no_residue(tmp_path):
    source_parent = tmp_path / "source"
    target_parent = tmp_path / "target"
    source_parent.mkdir()
    target_parent.mkdir()

    source_fd = _open_dir(source_parent)
    target_fd = _open_dir(target_parent)
    try:
        assert fs_ops.probe_directory_rename_noreplace_compat_at(source_fd, target_fd) is False
    finally:
        os.close(source_fd)
        os.close(target_fd)

    assert list(source_parent.iterdir()) == []
    assert list(target_parent.iterdir()) == []


def test_directory_discovery_becomes_ready_when_native_noreplace_is_missing_but_strict_rename_is_proven(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B" / "C").mkdir(parents=True)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: True,
    )

    decisions = single_child_wrapper_module.discover_single_child_wrappers(str(root), str(root))
    decision = next(d for d in decisions if Path(d.wrapper_path).name == "B")

    assert decision.state == "READY"
    assert decision.selectable is True
    assert decision.child_object_type == "directory"


def test_directory_discovery_still_fails_closed_when_both_native_and_compat_capabilities_are_unproven(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B" / "C").mkdir(parents=True)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: None,
    )

    decisions = single_child_wrapper_module.discover_single_child_wrappers(str(root), str(root))
    decision = next(d for d in decisions if Path(d.wrapper_path).name == "B")

    assert decision.state == "UNSUPPORTED_FILESYSTEM"
    assert decision.selectable is False


def test_executor_directory_move_uses_proven_strict_ordinary_rename_without_overwrite(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    wrapper = root / "B"
    source = wrapper / "C"
    target = root / "C"
    source.mkdir(parents=True)
    marker = source / "payload.txt"
    marker.write_text("payload", encoding="utf-8")

    def no_native(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "simulated zfuse no RENAME_NOREPLACE")

    real_rename = os.rename
    strict_rename = _strict_directory_rename(real_rename)
    monkeypatch.setattr(fs_ops, "rename_noreplace", no_native)
    monkeypatch.setattr(fs_ops, "probe_directory_rename_noreplace_compat_at", lambda *_a, **_k: True)
    monkeypatch.setattr(executor_module.os, "rename", strict_rename)

    st = os.lstat(source)
    result = execute_item(
        OperationItem(
            sequence=1,
            operation="move",
            source=source,
            target=target,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
        ),
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=root / ".trash",
        plan_id="zfuse-compat",
    )

    assert result.state == "completed"
    assert not source.exists()
    assert target.is_dir()
    assert (target / "payload.txt").read_text(encoding="utf-8") == "payload"


def test_executor_directory_compat_collision_preserves_both_namespaces(tmp_path, monkeypatch):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    source.mkdir(parents=True)
    (source / "source.txt").write_text("source", encoding="utf-8")
    target.mkdir()
    (target / "foreign.txt").write_text("foreign", encoding="utf-8")

    def no_native(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "simulated zfuse no RENAME_NOREPLACE")

    real_rename = os.rename
    monkeypatch.setattr(fs_ops, "rename_noreplace", no_native)
    monkeypatch.setattr(fs_ops, "probe_directory_rename_noreplace_compat_at", lambda *_a, **_k: True)
    monkeypatch.setattr(executor_module.os, "rename", _strict_directory_rename(real_rename))

    result = execute_item(
        OperationItem(sequence=1, operation="move", source=source, target=target),
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=root / ".trash",
        plan_id="zfuse-collision",
    )

    assert result.state == "skipped"
    assert result.reason == "target already exists"
    assert (source / "source.txt").read_text(encoding="utf-8") == "source"
    assert (target / "foreign.txt").read_text(encoding="utf-8") == "foreign"
