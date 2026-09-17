from __future__ import annotations

import errno
from pathlib import Path

import pytest

import app.fs_ops as fs_ops
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import IndexRoot
from app.workflows.compiler import WorkflowCompiler
from app.workflows.errors import WorkflowValidationError
from app.workflows.schema import (
    SingleChildWrapperCollapseStep,
    WorkflowDefinition,
)


def _setup_compiler(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    root = data / "root"
    scope = root / "A"
    (scope / "B" / "C").mkdir(parents=True)

    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        database_path=config / "app.db",
        allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
    )
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    with SessionLocal() as session:
        index_root = IndexRoot(root=str(root))
        session.add(index_root)
        session.commit()
        root_id = index_root.id

    definition = WorkflowDefinition(
        schema_version=1,
        mode="utility",
        steps=[
            SingleChildWrapperCollapseStep(
                id="collapse",
                type="single_child_wrapper_collapse",
                root_id=root_id,
                subpath="A",
            )
        ],
    )
    return data, root, SessionLocal, definition


def _cleanup_but_report_failure(real_cleanup):
    def _fail(path: str, *, dir_fd: int | None = None) -> bool:
        # Keep the test namespace clean while modeling an unresolved cleanup
        # result that must not be downgraded to ordinary unsupported capability.
        real_cleanup(path, dir_fd=dir_fd)
        return False

    return _fail


def test_cross_name_probe_cleanup_failure_raises_safety_error(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "C"
    child.mkdir()

    real_cleanup = fs_ops._cleanup_probe_name
    monkeypatch.setattr(
        fs_ops,
        "_cleanup_probe_name",
        _cleanup_but_report_failure(real_cleanup),
    )

    fd = fs_ops.os.open(parent, fs_ops.os.O_RDONLY | fs_ops.os.O_DIRECTORY)
    try:
        with pytest.raises(RuntimeError, match="probe cleanup"):
            fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        fs_ops.os.close(fd)

    assert sorted(entry.name for entry in parent.iterdir()) == ["C"]


def test_cross_name_probe_close_failure_after_create_is_safety_error_and_cleans(
    tmp_path,
    monkeypatch,
):
    parent = tmp_path / "parent"
    parent.mkdir()

    token_bytes = b"closefd!"
    token = token_bytes.hex()
    probe_src_name = f".__probe_noreplace_src_{token}"
    probe_dst_name = f".__probe_noreplace_dst_{token}"
    real_close = fs_ops.os.close

    monkeypatch.setattr(fs_ops.os, "urandom", lambda _n: token_bytes)
    dir_fd = fs_ops.os.open(parent, fs_ops.os.O_RDONLY | fs_ops.os.O_DIRECTORY)

    def close_then_raise(fd):
        real_close(fd)
        raise OSError(errno.EIO, "simulated probe close failure")

    monkeypatch.setattr(fs_ops.os, "close", close_then_raise)
    try:
        with pytest.raises(fs_ops.NoreplaceProbeCleanupError, match="probe cleanup"):
            fs_ops._probe_rename_noreplace_supported(dir_fd=dir_fd)
    finally:
        monkeypatch.setattr(fs_ops.os, "close", real_close)
        real_close(dir_fd)

    assert not (parent / probe_src_name).exists()
    assert not (parent / probe_dst_name).exists()


def test_path_probe_close_failure_after_create_is_safety_error_and_cleans(
    tmp_path,
    monkeypatch,
):
    parent = tmp_path / "parent"
    parent.mkdir()

    token_bytes = b"pathfd!!"
    token = token_bytes.hex()
    probe_src = parent / f".__probe_noreplace_src_{token}"
    probe_dst = parent / f".__probe_noreplace_dst_{token}"
    real_close = fs_ops.os.close

    monkeypatch.setattr(fs_ops.os, "urandom", lambda _n: token_bytes)

    def close_then_raise(fd):
        real_close(fd)
        raise OSError(errno.EIO, "simulated probe close failure")

    monkeypatch.setattr(fs_ops.os, "close", close_then_raise)
    try:
        with pytest.raises(fs_ops.NoreplaceProbeCleanupError, match="probe cleanup"):
            fs_ops._probe_rename_noreplace_supported(parent / "candidate")
    finally:
        monkeypatch.setattr(fs_ops.os, "close", real_close)

    assert not probe_src.exists()
    assert not probe_dst.exists()


def test_workflow_compile_surfaces_probe_cleanup_failure_as_safety_error(tmp_path, monkeypatch):
    data, _root, SessionLocal, definition = _setup_compiler(tmp_path)

    real_cleanup = fs_ops._cleanup_probe_name
    monkeypatch.setattr(
        fs_ops,
        "_cleanup_probe_name",
        _cleanup_but_report_failure(real_cleanup),
    )

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[data],
            quarantine_root=data / ".trash",
        )
        with pytest.raises(WorkflowValidationError) as exc:
            compiler.compile(definition)

    assert exc.value.code == "UTILITY_CAPABILITY_PROBE_SAFETY_ERROR"
    assert exc.value.status_code == 422
    assert exc.value.details["reason"] == "probe_cleanup_failed"
    assert exc.value.details["scope_path"].endswith("/root/A")


def test_workflow_compile_surfaces_post_create_close_failure_as_safety_error(
    tmp_path,
    monkeypatch,
):
    data, _root, SessionLocal, definition = _setup_compiler(tmp_path)

    real_open = fs_ops.os.open
    real_close = fs_ops.os.close
    probe_fds: set[int] = set()

    def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if str(path).startswith(".__probe_noreplace_src_"):
            probe_fds.add(fd)
        return fd

    def close_probe_then_raise(fd):
        if fd in probe_fds:
            probe_fds.remove(fd)
            real_close(fd)
            raise OSError(errno.EIO, "simulated probe close failure")
        return real_close(fd)

    monkeypatch.setattr(fs_ops.os, "open", tracking_open)
    monkeypatch.setattr(fs_ops.os, "close", close_probe_then_raise)

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[data],
            quarantine_root=data / ".trash",
        )
        with pytest.raises(WorkflowValidationError) as exc:
            compiler.compile(definition)

    assert exc.value.code == "UTILITY_CAPABILITY_PROBE_SAFETY_ERROR"
    assert exc.value.status_code == 422
    assert exc.value.details["reason"] == "probe_cleanup_failed"
    assert exc.value.details["scope_path"].endswith("/root/A")
    assert list(data.rglob(".__probe_noreplace_*")) == []
