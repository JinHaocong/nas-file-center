from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.batch.plans import OperationItem
from app.db import create_engine_and_session, init_db
from app.execution.executor import execute_item
from app.models import BatchPlan, BatchPlanItem


def _exercise_cleanup(
    tmp_path: Path,
    *,
    cleanup_device: int | None = None,
    cleanup_inode: int | None = None,
    use_actual_identity: bool = False,
    predecessor_source_override: str | None = None,
    predecessor_target_override: str | None = None,
):
    data_root = tmp_path / "data"
    wrapper = data_root / "utility" / "A" / "B"
    wrapper.mkdir(parents=True)
    child = wrapper / "C"
    target = data_root / "utility" / "A" / "C"
    candidate_id = "review-authority-binding"

    if use_actual_identity:
        st = os.lstat(wrapper)
        cleanup_device = st.st_dev
        cleanup_inode = st.st_ino

    db_path = tmp_path / "app.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    plan_metadata = {
        "source": "workflow",
        "workflow_mode": "utility",
        "compile_context": {"utility_action": "single_child_wrapper_collapse"},
    }
    item_metadata = {
        "candidate_id": candidate_id,
        "utility_action": "single_child_wrapper_collapse",
        "wrapper_path": str(wrapper),
        "child_path": str(child),
        "target_path": str(target),
    }

    with SessionLocal() as session:
        plan = BatchPlan(
            name="review authority binding",
            kind="workflow-1",
            status="ready",
            expected_changes=2,
            metadata_json=json.dumps(plan_metadata),
        )
        session.add(plan)
        session.flush()
        session.add_all(
            [
                BatchPlanItem(
                    plan_id=plan.id,
                    sequence=1,
                    operation="move",
                    source_path=predecessor_source_override or str(child),
                    target_path=predecessor_target_override or str(target),
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
                    expected_device=cleanup_device,
                    expected_inode=cleanup_inode,
                    expected_hash=None,
                    state="validated",
                    reason="empty directory deletion validated",
                    metadata_json=json.dumps(item_metadata),
                ),
            ]
        )
        session.commit()
        plan_id = plan.id

    item = OperationItem(
        sequence=2,
        operation="rmdir_empty",
        source=wrapper,
        target=None,
        keep=None,
        expected_size=0,
        expected_hash=None,
        state="validated",
        expected_mtime_ns=0,
        expected_device=cleanup_device,
        expected_inode=cleanup_inode,
    )
    result = execute_item(
        item,
        allowed_roots=[data_root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data_root / ".nas-file-center-trash",
        plan_id=str(plan_id),
        session_factory=SessionLocal,
    )
    return result, wrapper


@pytest.mark.parametrize(
    ("cleanup_device", "cleanup_inode"),
    [
        (None, None),
        (0, 0),
    ],
)
def test_cleanup_authority_requires_valid_frozen_wrapper_identity(
    tmp_path,
    cleanup_device,
    cleanup_inode,
):
    result, wrapper = _exercise_cleanup(
        tmp_path,
        cleanup_device=cleanup_device,
        cleanup_inode=cleanup_inode,
    )

    assert result.state == "skipped"
    assert result.reason == "permanent deletion is disabled"
    assert wrapper.exists()


def test_cleanup_authority_binds_completed_move_actual_source_path(tmp_path):
    result, wrapper = _exercise_cleanup(
        tmp_path,
        use_actual_identity=True,
        predecessor_source_override=str(tmp_path / "data" / "utility" / "WRONG"),
    )

    assert result.state == "skipped"
    assert result.reason == "permanent deletion is disabled"
    assert wrapper.exists()


def test_cleanup_authority_binds_completed_move_actual_target_path(tmp_path):
    result, wrapper = _exercise_cleanup(
        tmp_path,
        use_actual_identity=True,
        predecessor_target_override=str(tmp_path / "data" / "utility" / "WRONG-TARGET"),
    )

    assert result.state == "skipped"
    assert result.reason == "permanent deletion is disabled"
    assert wrapper.exists()
