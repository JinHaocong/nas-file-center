from __future__ import annotations

import errno
import json
import os
from pathlib import Path

from app.batch.plans import OperationItem
from app.db import create_engine_and_session, init_db
from app.execution.executor import execute_item
from app.execution.utility_structural_cleanup import remove_authorized_empty_wrapper
from app.models import BatchPlan, BatchPlanItem


def test_paired_utility_cleanup_removes_empty_wrapper_without_quarantine_dependency(tmp_path):
    """Frozen Amendment-B cleanup is direct, non-recursive, and quarantine-independent."""
    data_root = tmp_path / "data"
    wrapper = data_root / "utility" / "A" / "B"
    wrapper.mkdir(parents=True)

    quarantine_root = data_root / ".nas-file-center-trash"
    assert not quarantine_root.exists()

    st = os.lstat(wrapper)
    candidate_id = "native-cleanup-contract"
    target = data_root / "utility" / "A" / "C"

    db_path = tmp_path / "app.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    plan_metadata = {
        "source": "workflow",
        "workflow_mode": "utility",
        "compile_context": {
            "utility_action": "single_child_wrapper_collapse",
        },
    }
    item_metadata = {
        "candidate_id": candidate_id,
        "utility_action": "single_child_wrapper_collapse",
        "wrapper_path": str(wrapper),
        "child_path": str(wrapper / "C"),
        "target_path": str(target),
    }

    with SessionLocal() as session:
        plan = BatchPlan(
            name="native cleanup contract",
            kind="workflow-1",
            status="ready",
            expected_changes=2,
            metadata_json=json.dumps(plan_metadata),
        )
        session.add(plan)
        session.flush()

        session.add_all([
            BatchPlanItem(
                plan_id=plan.id,
                sequence=1,
                operation="move",
                source_path=str(wrapper / "C"),
                target_path=str(target),
                keep_path=None,
                expected_size=0,
                expected_mtime_ns=0,
                expected_device=0,
                expected_inode=0,
                expected_hash=None,
                state="completed",
                reason="moved",
                metadata_json=json.dumps(item_metadata),
            ),
            BatchPlanItem(
                plan_id=plan.id,
                sequence=2,
                operation="rmdir_empty",
                source_path=str(wrapper),
                target_path=None,
                keep_path=None,
                expected_size=0,
                expected_mtime_ns=0,
                expected_device=st.st_dev,
                expected_inode=st.st_ino,
                expected_hash=None,
                state="validated",
                reason="empty directory deletion validated",
                metadata_json=json.dumps(item_metadata),
            ),
        ])
        session.commit()
        plan_id = plan.id

    cleanup_item = OperationItem(
        sequence=2,
        operation="rmdir_empty",
        source=wrapper,
        target=None,
        keep=None,
        expected_size=0,
        expected_hash=None,
        state="validated",
        expected_mtime_ns=0,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    result = execute_item(
        cleanup_item,
        allowed_roots=[data_root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=quarantine_root,
        plan_id=str(plan_id),
        session_factory=SessionLocal,
    )

    assert result.state == "completed"
    assert not wrapper.exists()
    assert not quarantine_root.exists()


def test_structural_cleanup_stays_completed_if_wrapper_close_reports_error_after_rmdir(
    tmp_path,
    monkeypatch,
):
    """A post-rmdir descriptor-close error must not rewrite completed namespace truth as failed."""
    data_root = tmp_path / "data"
    wrapper = data_root / "utility" / "A" / "B"
    wrapper.mkdir(parents=True)
    st = os.lstat(wrapper)

    real_close = os.close

    def close_then_report_error(fd):
        try:
            fd_stat = os.fstat(fd)
        except OSError:
            return real_close(fd)
        if fd_stat.st_dev == st.st_dev and fd_stat.st_ino == st.st_ino:
            real_close(fd)
            raise OSError(errno.EIO, "simulated wrapper close failure after successful rmdir")
        return real_close(fd)

    monkeypatch.setattr(os, "close", close_then_report_error)

    result = remove_authorized_empty_wrapper(
        wrapper,
        allowed_roots=[data_root],
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    assert not wrapper.exists()
    assert result.state == "completed"
    assert result.reason.startswith("empty wrapper structurally removed")
