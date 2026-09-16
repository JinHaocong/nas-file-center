from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from app.batch.plans import OperationItem
from app.config import Settings
from app.execution.executor import execute_item
from app.models import BatchPlanItem, IndexRoot
from app.service import FileCenterService
from app.workflows.schema import (
    SingleChildWrapperCollapseStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
)


@pytest.fixture
def utility_execution_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    root = data_dir / "root1"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=config_dir / "app.db",
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine,
        protect_last_file=True,
    )
    service = FileCenterService(settings)

    with service.SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        session.add(idx)
        session.commit()
        root_id = idx.id

    workflow = service.workflow_service.create_workflow(
        None,
        WorkflowCreateRequest(
            name="Collapse wrappers safety",
            definition=WorkflowDefinition(
                schema_version=1,
                mode="utility",
                steps=[
                    SingleChildWrapperCollapseStep(
                        id="collapse",
                        type="single_child_wrapper_collapse",
                        root_id=root_id,
                        subpath="",
                    )
                ],
            ),
        ),
    )

    return {
        "service": service,
        "workflow_id": workflow["id"],
        "root": root,
        "quarantine": quarantine,
        "tmp_path": tmp_path,
    }


def _generate_frozen_plan(env) -> int:
    root = env["root"]
    (root / "B" / "C").mkdir(parents=True)

    preview = env["service"].workflow_service.preview_workflow(
        env["workflow_id"],
        WorkflowPreviewRequest(page=1, page_size=50),
    )
    candidate = next(
        item
        for item in preview["utility_summary"]["candidates"]
        if Path(item["wrapper_path"]).name == "B"
    )

    generated = env["service"].workflow_service.generate_plan(
        None,
        env["workflow_id"],
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=[candidate["candidate_id"]],
        ),
    )
    env["service"].freeze_plan(generated["plan_id"])
    return generated["plan_id"]


def _load_operations(env, plan_id: int) -> list[OperationItem]:
    with env["service"].SessionLocal() as session:
        rows = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence.asc())
            ).all()
        )
        return [
            OperationItem(
                sequence=row.sequence,
                operation=row.operation,
                source=Path(row.source_path),
                target=Path(row.target_path) if row.target_path else None,
                expected_size=row.expected_size,
                expected_hash=row.expected_hash,
                state=row.state,
                expected_mtime_ns=row.expected_mtime_ns,
                expected_device=row.expected_device,
                expected_inode=row.expected_inode,
            )
            for row in rows
        ]


def test_third_party_object_after_move_preserves_wrapper_and_object(utility_execution_env):
    env = utility_execution_env
    root = env["root"]
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)

    moved = execute_item(
        move_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
    )
    assert moved.state == "completed"
    assert (root / "C").is_dir()
    assert (root / "B").is_dir()

    intruder = root / "B" / "third-party.txt"
    intruder.write_text("must survive", encoding="utf-8")

    removed = execute_item(
        rmdir_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
    )

    assert removed.state != "completed"
    assert (root / "B").is_dir()
    assert intruder.read_text(encoding="utf-8") == "must survive"
    assert (root / "C").is_dir()


def test_target_appearing_after_freeze_marks_utility_plan_stale(utility_execution_env):
    env = utility_execution_env
    root = env["root"]
    plan_id = _generate_frozen_plan(env)

    target = root / "C"
    target.mkdir()
    marker = target / "foreign.txt"
    marker.write_text("foreign target", encoding="utf-8")

    validation = env["service"].validate_plan(plan_id)

    assert validation["status"] == "stale"
    move_row = next(item for item in validation["items"] if item["operation"] == "move")
    assert move_row["state"] == "stale"
    assert move_row["reason"] == "target_appeared"
    assert (root / "B" / "C").is_dir()
    assert marker.read_text(encoding="utf-8") == "foreign target"


def test_symlink_and_path_aba_after_freeze_fail_closed(utility_execution_env):
    env = utility_execution_env
    root = env["root"]

    plan_id = _generate_frozen_plan(env)
    original_child = env["tmp_path"] / "original-C"
    (root / "B" / "C").rename(original_child)
    os.symlink(original_child, root / "B" / "C")

    symlink_validation = env["service"].validate_plan(plan_id)
    assert symlink_validation["status"] == "stale"
    assert (root / "B" / "C").is_symlink()
    assert not (root / "C").exists()

    # Fresh environment path for an inode/path ABA replacement.
    root2 = env["data_root_2"] if "data_root_2" in env else None
    if root2 is None:
        # Rebuild this case under another direct child name without reusing the stale plan.
        (root / "B2" / "C2").mkdir(parents=True)
        preview = env["service"].workflow_service.preview_workflow(
            env["workflow_id"],
            WorkflowPreviewRequest(page=1, page_size=50),
        )
        candidate = next(
            item
            for item in preview["utility_summary"]["candidates"]
            if Path(item["wrapper_path"]).name == "B2"
        )
        generated = env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )
        aba_plan_id = generated["plan_id"]
        env["service"].freeze_plan(aba_plan_id)
    else:
        raise AssertionError("unexpected fixture state")

    old_child = env["tmp_path"] / "old-C2"
    (root / "B2" / "C2").rename(old_child)
    (root / "B2" / "C2").mkdir()

    aba_validation = env["service"].validate_plan(aba_plan_id)
    assert aba_validation["status"] == "stale"
    assert (root / "B2" / "C2").is_dir()
    assert not (root / "C2").exists()


def test_utility_empty_wrapper_removal_has_no_recursive_delete_path(
    utility_execution_env,
    monkeypatch,
):
    env = utility_execution_env
    root = env["root"]
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)

    moved = execute_item(
        move_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
    )
    assert moved.state == "completed"
    assert (root / "B").is_dir()
    assert list((root / "B").iterdir()) == []

    monkeypatch.setattr(os, "unlink", lambda *a, **k: pytest.fail("FORBIDDEN: os.unlink"))
    monkeypatch.setattr(os, "rmdir", lambda *a, **k: pytest.fail("FORBIDDEN: os.rmdir"))
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: pytest.fail("FORBIDDEN: shutil.rmtree"))

    removed = execute_item(
        rmdir_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
    )

    assert removed.state == "completed"
    assert not (root / "B").exists()
    assert removed.result_path is not None
    assert removed.result_path.is_dir()
