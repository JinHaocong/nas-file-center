from __future__ import annotations

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
