from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
import app.execution.executor as executor_module
import app.execution.directory_transplant as transplant_module
import app.fs_ops as fs_ops
from app.batch.plans import OperationItem
from app.execution.directory_transplant import (
    cleanup_directory_transplant_state,
    directory_transplant_preflight,
    directory_transplant_reconciles_completed,
    move_directory_tree_noreplace,
)
from app.execution.executor import execute_item


def test_directory_transplant_preflight_accepts_regular_nested_tree(tmp_path: Path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "file.txt").write_text("alpha", encoding="utf-8")
    (source / "nested" / "child.txt").write_text("beta", encoding="utf-8")
    os.symlink("file.txt", source / "link")

    assert directory_transplant_preflight(source) is True


def test_directory_transplant_moves_nested_tree_without_overwrite(tmp_path: Path):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    quarantine = tmp_path / "quarantine"
    (source / "nested").mkdir(parents=True)
    (source / "file.txt").write_text("alpha", encoding="utf-8")
    (source / "nested" / "child.txt").write_text("beta", encoding="utf-8")
    os.symlink("file.txt", source / "link")

    st = os.lstat(source)
    move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine,
        plan_id="plan-1",
        sequence=1,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    assert not source.exists()
    assert (target / "file.txt").read_text(encoding="utf-8") == "alpha"
    assert (target / "nested" / "child.txt").read_text(encoding="utf-8") == "beta"
    assert os.readlink(target / "link") == "file.txt"
    assert directory_transplant_reconciles_completed(
        quarantine,
        "plan-1",
        1,
        source=source,
        target=target,
    ) is True

    cleanup_directory_transplant_state(quarantine, "plan-1", 1)
    assert directory_transplant_reconciles_completed(
        quarantine,
        "plan-1",
        1,
        source=source,
        target=target,
    ) is False


def test_directory_transplant_rejects_foreign_target_root(tmp_path: Path):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    quarantine = tmp_path / "quarantine"
    source.mkdir(parents=True)
    (source / "source.txt").write_text("source", encoding="utf-8")
    target.mkdir()
    (target / "foreign.txt").write_text("foreign", encoding="utf-8")

    st = os.lstat(source)
    with pytest.raises(FileExistsError):
        move_directory_tree_noreplace(
            source,
            target,
            quarantine_root=quarantine,
            plan_id="plan-2",
            sequence=1,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
        )

    assert (source / "source.txt").read_text(encoding="utf-8") == "source"
    assert (target / "foreign.txt").read_text(encoding="utf-8") == "foreign"


def test_directory_transplant_resumes_after_link_publication_crash(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    quarantine = tmp_path / "quarantine"
    source.mkdir(parents=True)
    (source / "file.txt").write_text("payload", encoding="utf-8")

    st = os.lstat(source)
    real_unlink = transplant_module.os.unlink
    crashed = {"done": False}

    def crash_once(path, *args, **kwargs):
        if not crashed["done"] and path == "file.txt":
            crashed["done"] = True
            raise RuntimeError("simulated process crash after hard-link publication")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(transplant_module.os, "unlink", crash_once)
    with pytest.raises(RuntimeError):
        move_directory_tree_noreplace(
            source,
            target,
            quarantine_root=quarantine,
            plan_id="plan-3",
            sequence=1,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
        )

    assert (source / "file.txt").exists()
    assert (target / "file.txt").exists()
    assert os.lstat(source / "file.txt").st_ino == os.lstat(target / "file.txt").st_ino

    monkeypatch.setattr(transplant_module.os, "unlink", real_unlink)
    move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine,
        plan_id="plan-3",
        sequence=1,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    assert not source.exists()
    assert (target / "file.txt").read_text(encoding="utf-8") == "payload"


def test_discovery_uses_transplant_when_both_rename_noreplace_paths_are_unavailable(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "root"
    (root / "B" / "C" / "nested").mkdir(parents=True)
    (root / "B" / "C" / "nested" / "file.txt").write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: False,
    )

    decisions = single_child_wrapper_module.discover_single_child_wrappers(str(root), str(root))
    decision = next(d for d in decisions if Path(d.wrapper_path).name == "B")

    assert decision.state == "READY"
    assert decision.selectable is True
    assert decision.capability_reason == "UTILITY_MOVE_COMPAT_DIRECTORY_TRANSPLANT"


def test_executor_falls_back_to_directory_transplant_on_standard_posix_rename(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    quarantine = root / ".nas-file-center-trash"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "payload.txt").write_text("payload", encoding="utf-8")

    def no_native(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "native NOREPLACE unavailable")

    def no_plain_compat(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "plain rename no-clobber unavailable")

    monkeypatch.setattr(fs_ops, "rename_noreplace", no_native)
    monkeypatch.setattr(fs_ops, "rename_directory_noreplace_compat", no_plain_compat)

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
        quarantine_root=quarantine,
        plan_id="plan-4",
    )

    assert result.state == "completed"
    assert not source.exists()
    assert (target / "nested" / "payload.txt").read_text(encoding="utf-8") == "payload"
