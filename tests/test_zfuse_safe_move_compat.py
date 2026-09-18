from __future__ import annotations

import errno
import os
from pathlib import Path

import app.batch_utilities.single_child_wrapper as wrapper_module
import app.fs_ops as fs_ops
from app.batch.plans import OperationItem
from app.batch_utilities.single_child_wrapper import discover_single_child_wrappers
from app.execution.executor import execute_item


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def test_plain_directory_rename_probe_positive_only_when_existing_targets_are_never_replaced(
    tmp_path,
    monkeypatch,
):
    source_parent = tmp_path / "wrapper"
    target_parent = tmp_path / "scope"
    source_parent.mkdir()
    target_parent.mkdir()

    real_rename = os.rename

    def no_clobber_rename(src, dst, *args, src_dir_fd=None, dst_dir_fd=None, **kwargs):
        try:
            os.stat(dst, dir_fd=dst_dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return real_rename(
                src,
                dst,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )
        raise OSError(errno.EEXIST, "simulated zfuse no-clobber plain rename")

    monkeypatch.setattr(fs_ops.os, "rename", no_clobber_rename)

    src_fd = _open_dir(source_parent)
    dst_fd = _open_dir(target_parent)
    try:
        assert fs_ops.probe_directory_rename_noreplace_compat_at(src_fd, dst_fd) is True
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert list(source_parent.iterdir()) == []
    assert list(target_parent.iterdir()) == []


def test_plain_directory_rename_probe_rejects_posix_replace_semantics(tmp_path):
    source_parent = tmp_path / "wrapper"
    target_parent = tmp_path / "scope"
    source_parent.mkdir()
    target_parent.mkdir()

    src_fd = _open_dir(source_parent)
    dst_fd = _open_dir(target_parent)
    try:
        assert fs_ops.probe_directory_rename_noreplace_compat_at(src_fd, dst_fd) is False
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert list(source_parent.iterdir()) == []
    assert list(target_parent.iterdir()) == []


def test_directory_candidate_becomes_ready_when_native_noreplace_is_missing_but_plain_rename_is_proven_noclobber(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B" / "C").mkdir(parents=True)

    monkeypatch.setattr(
        wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        wrapper_module,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: True,
        raising=False,
    )

    [decision] = discover_single_child_wrappers(str(root), str(root))
    assert decision.state == "READY"
    assert decision.selectable is True
    assert decision.capability_reason == "UTILITY_MOVE_COMPAT_PLAIN_RENAME_NOCLOBBER"


def test_directory_execution_uses_positive_probed_plain_rename_compat_when_native_is_unsupported(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    source.mkdir(parents=True)
    (source / "movie.mkv").write_text("payload", encoding="utf-8")

    def no_native(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "native noreplace unavailable")

    called = []

    def compat(source_path, target_path):
        called.append((Path(source_path), Path(target_path)))
        os.rename(source_path, target_path)

    monkeypatch.setattr(fs_ops, "rename_noreplace", no_native)
    monkeypatch.setattr(
        fs_ops,
        "rename_directory_noreplace_compat",
        compat,
        raising=False,
    )

    item = OperationItem(
        sequence=1,
        operation="move",
        source=source,
        target=target,
        expected_size=0,
        expected_hash=None,
        state="validated",
    )
    result = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=root / ".nas-file-center-trash",
        plan_id="1",
    )

    assert result.state == "completed"
    assert called == [(source, target)]
    assert target.is_dir()
    assert (target / "movie.mkv").read_text(encoding="utf-8") == "payload"
    assert not source.exists()


def test_directory_compat_execution_still_fails_closed_when_runtime_probe_is_not_positive(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    source.mkdir(parents=True)

    monkeypatch.setattr(
        fs_ops,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: False,
        raising=False,
    )

    try:
        fs_ops.rename_directory_noreplace_compat(source, target)
    except OSError as exc:
        assert exc.errno == errno.EOPNOTSUPP
    else:
        raise AssertionError("compat directory MOVE must fail closed without positive runtime proof")

    assert source.is_dir()
    assert not target.exists()
