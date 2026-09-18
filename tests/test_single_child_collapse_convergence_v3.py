from __future__ import annotations

import errno
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.execution.directory_transplant as transplant_module
import app.worker as worker_module
import app.tasks.utility_structural_cleanup_compat as cleanup_compat_module
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.execution.directory_transplant import (
    directory_transplant_preflight,
    move_directory_tree_noreplace,
)
from app.execution.utility_structural_cleanup import remove_authorized_empty_wrapper
from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.tasks.utility_structural_cleanup_compat import PreparedUtilityStructuralCleanup
from app.models import BatchPlan, BatchPlanItem, WorkJob


def test_transplant_metadata_failure_is_warning_not_partial_move(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    quarantine = root / ".nas-file-center-trash"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "payload.txt").write_text("payload", encoding="utf-8")

    def deny_chmod(*_args, **_kwargs):
        raise PermissionError(errno.EPERM, "simulated zfuse chmod denial")

    monkeypatch.setattr(transplant_module.os, "fchmod", deny_chmod)

    st = os.lstat(source)
    result = move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine,
        plan_id="metadata-warning",
        sequence=1,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    assert not source.exists()
    assert (target / "nested" / "payload.txt").read_text(encoding="utf-8") == "payload"
    assert result.metadata_warnings
    assert any("chmod" in warning for warning in result.metadata_warnings)


def test_transplant_core_failure_removes_owned_empty_target_shells(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target = root / "C"
    quarantine = root / ".nas-file-center-trash"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "payload.txt").write_text("payload", encoding="utf-8")

    def no_hardlink(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "simulated zfuse hardlink unsupported")

    monkeypatch.setattr(transplant_module.os, "link", no_hardlink)

    st = os.lstat(source)
    with pytest.raises(OSError) as exc:
        move_directory_tree_noreplace(
            source,
            target,
            quarantine_root=quarantine,
            plan_id="link-failure",
            sequence=1,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
        )

    assert "link" in str(exc.value).lower()
    assert "nested/payload.txt" in str(exc.value)
    assert source.exists()
    assert (source / "nested" / "payload.txt").exists()
    assert not target.exists()


def test_authorized_wrapper_cleanup_nonempty_is_failure_not_skip(tmp_path: Path):
    wrapper = tmp_path / "wrapper"
    wrapper.mkdir()
    (wrapper / "residue").mkdir()
    st = os.lstat(wrapper)

    result = remove_authorized_empty_wrapper(
        wrapper,
        allowed_roots=[tmp_path],
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    assert result.state == "failed"
    assert "not empty" in result.reason


def test_batch_plan_partial_cannot_be_reported_as_completed_work_job(tmp_path: Path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    quarantine = data / ".nas-file-center-trash"
    quarantine.mkdir()
    db_path = config / "app.db"

    settings = Settings(
        config_dir=config,
        database_path=db_path,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=quarantine,
        allow_mutation=True,
        allow_delete=True,
    )
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        plan = BatchPlan(
            name="partial utility plan",
            kind="workflow-utility",
            status="partial",
            expected_changes=1,
            metadata_json=json.dumps({
                "source": "workflow",
                "workflow_mode": "utility",
                "compile_context": {"utility_action": "single_child_wrapper_collapse"},
            }),
        )
        session.add(plan)
        session.flush()
        session.add(BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="move",
            source_path=str(data / "B" / "C"),
            target_path=str(data / "C"),
            keep_path=None,
            expected_size=0,
            expected_mtime_ns=0,
            expected_device=0,
            expected_inode=0,
            expected_hash=None,
            state="failed",
            reason="simulated partial transplant",
        ))
        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id}),
        )
        session.add(job)
        session.commit()
        plan_id = int(plan.id)
        job_id = int(job.id)

    class NoopHandler:
        def run(self, _job, _context, _settings):
            return None

    monkeypatch.setattr(worker_module, "get_handler", lambda _kind: NoopHandler())

    processed = worker_module.process_work_job(
        settings,
        job_id,
        session_factory=SessionLocal,
        engine=engine,
        worker_id=None,
    )

    assert processed is False
    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        plan = session.get(BatchPlan, plan_id)
        assert job is not None
        assert plan is not None
        assert job.status == "failed"
        assert job.error_code == "PLAN_NOT_COMPLETED"
        assert plan.status == "partial"


def test_transplant_preflight_rejects_regular_tree_without_hardlink_support(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "root"
    source = root / "B" / "C"
    target_parent = root
    source.mkdir(parents=True)
    (source / "payload.txt").write_text("payload", encoding="utf-8")

    def no_hardlink(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "simulated zfuse hardlink unsupported")

    monkeypatch.setattr(transplant_module.os, "link", no_hardlink)

    assert directory_transplant_preflight(source, target_parent) is False
    assert not any(".__nfc_transplant_link_" in p.name for p in source.iterdir())
    assert not any(".__nfc_transplant_link_" in p.name for p in target_parent.iterdir())


def test_paired_cleanup_accepts_post_move_inode_rekey_when_open_fd_matches_path(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "root"
    wrapper = root / "B"
    child = wrapper / "C"
    target = root / "C"
    child.mkdir(parents=True)

    parent_context = safe_open_parent_fd(wrapper, [root])
    parent_fd, leaf_name = parent_context.__enter__()
    wrapper_fd = os.open(
        leaf_name,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    guard = PreparedUtilityStructuralCleanup(
        parent_context=parent_context,
        parent_fd=parent_fd,
        wrapper_fd=wrapper_fd,
        leaf_name=leaf_name,
        cleanup_item_id=99,
    )

    os.rename(child, target)
    assert wrapper.is_dir()
    assert not any(wrapper.iterdir())

    real_fstat = cleanup_compat_module.os.fstat
    real_stat = cleanup_compat_module.os.stat
    current = real_fstat(wrapper_fd)
    synthetic_ino = int(current.st_ino) + 1000003
    synthetic = SimpleNamespace(
        st_mode=current.st_mode,
        st_dev=current.st_dev,
        st_ino=synthetic_ino,
    )

    def rekeyed_fstat(fd):
        if fd == wrapper_fd:
            return synthetic
        return real_fstat(fd)

    def rekeyed_stat(path, *args, **kwargs):
        if path == leaf_name and kwargs.get("dir_fd") == parent_fd:
            return synthetic
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(cleanup_compat_module.os, "fstat", rekeyed_fstat)
    monkeypatch.setattr(cleanup_compat_module.os, "stat", rekeyed_stat)
    try:
        result = guard.cleanup_after_move()
    finally:
        guard.close()

    assert result.state == "completed"
    assert not wrapper.exists()
    assert target.is_dir()


def test_paired_cleanup_rejects_actual_path_rebind_even_if_wrapper_is_empty(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "root"
    wrapper = root / "B"
    child = wrapper / "C"
    target = root / "C"
    child.mkdir(parents=True)

    parent_context = safe_open_parent_fd(wrapper, [root])
    parent_fd, leaf_name = parent_context.__enter__()
    wrapper_fd = os.open(
        leaf_name,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    guard = PreparedUtilityStructuralCleanup(
        parent_context=parent_context,
        parent_fd=parent_fd,
        wrapper_fd=wrapper_fd,
        leaf_name=leaf_name,
        cleanup_item_id=100,
    )
    os.rename(child, target)

    real_fstat = cleanup_compat_module.os.fstat
    real_stat = cleanup_compat_module.os.stat
    current = real_fstat(wrapper_fd)
    open_view = SimpleNamespace(
        st_mode=current.st_mode,
        st_dev=current.st_dev,
        st_ino=int(current.st_ino) + 2000001,
    )
    path_view = SimpleNamespace(
        st_mode=current.st_mode,
        st_dev=current.st_dev,
        st_ino=int(current.st_ino) + 2000002,
    )

    monkeypatch.setattr(
        cleanup_compat_module.os,
        "fstat",
        lambda fd: open_view if fd == wrapper_fd else real_fstat(fd),
    )

    def rebound_stat(path, *args, **kwargs):
        if path == leaf_name and kwargs.get("dir_fd") == parent_fd:
            return path_view
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(cleanup_compat_module.os, "stat", rebound_stat)
    try:
        result = guard.cleanup_after_move()
    finally:
        guard.close()

    assert result.state == "failed"
    assert "binding changed" in result.reason
    assert wrapper.is_dir()
