from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
from app.batch.plans import OperationItem
from app.config import Settings
from app.exceptions import PlanStaleError
from app.execution.executor import execute_item
from app.models import BatchPlan, BatchPlanItem, IndexRoot
from app.service import FileCenterService
from app.workflows.schema import (
    SingleChildWrapperCollapseStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
)


@pytest.fixture
def utility_execution_env(tmp_path, monkeypatch):
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

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: True,
    )

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


def _generate_frozen_plan(env, wrapper_name: str = "B", child_name: str = "C") -> int:
    root = env["root"]
    (root / wrapper_name / child_name).mkdir(parents=True)

    preview = env["service"].workflow_service.preview_workflow(
        env["workflow_id"],
        WorkflowPreviewRequest(page=1, page_size=50),
    )
    candidate = next(
        item
        for item in preview["utility_summary"]["candidates"]
        if Path(item["wrapper_path"]).name == wrapper_name
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
    validation = env["service"].validate_plan(generated["plan_id"])
    assert validation["status"] == "ready"
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


def _mark_move_completed(env, plan_id: int, *, candidate_id_override: str | None = None) -> None:
    with env["service"].SessionLocal() as session:
        move_row = session.scalar(
            select(BatchPlanItem).where(
                BatchPlanItem.plan_id == plan_id,
                BatchPlanItem.operation == "move",
            )
        )
        assert move_row is not None
        move_row.state = "completed"
        if candidate_id_override is not None:
            metadata = json.loads(move_row.metadata_json or "{}")
            metadata["candidate_id"] = candidate_id_override
            move_row.metadata_json = json.dumps(metadata, ensure_ascii=False)
        session.commit()


def _execute_move(env, plan_id: int, move_item: OperationItem) -> None:
    moved = execute_item(
        move_item,
        allowed_roots=[env["root"]],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
    )
    assert moved.state == "completed"


def test_paired_utility_empty_wrapper_cleanup_allowed_with_global_delete_disabled(utility_execution_env):
    env = utility_execution_env
    root = env["root"]
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)

    _execute_move(env, plan_id, move_item)
    _mark_move_completed(env, plan_id)
    assert (root / "B").is_dir()
    assert list((root / "B").iterdir()) == []

    removed = execute_item(
        rmdir_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
        session_factory=env["service"].SessionLocal,
    )

    assert removed.state == "completed"
    assert not (root / "B").exists()


def test_utility_empty_wrapper_cleanup_without_session_factory_stays_blocked(utility_execution_env):
    env = utility_execution_env
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)
    _execute_move(env, plan_id, move_item)
    _mark_move_completed(env, plan_id)

    removed = execute_item(
        rmdir_item,
        allowed_roots=[env["root"]],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
    )

    assert removed.state == "skipped"
    assert removed.reason == "permanent deletion is disabled"
    assert (env["root"] / "B").is_dir()


def test_utility_empty_wrapper_cleanup_non_workflow_plan_stays_blocked(utility_execution_env):
    env = utility_execution_env
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)
    _execute_move(env, plan_id, move_item)
    _mark_move_completed(env, plan_id)

    with env["service"].SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        metadata = json.loads(plan.metadata_json or "{}")
        metadata["source"] = "manual"
        plan.metadata_json = json.dumps(metadata, ensure_ascii=False)
        session.commit()

    removed = execute_item(
        rmdir_item,
        allowed_roots=[env["root"]],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
        session_factory=env["service"].SessionLocal,
    )

    assert removed.state == "skipped"
    assert removed.reason == "permanent deletion is disabled"
    assert (env["root"] / "B").is_dir()


def test_utility_empty_wrapper_cleanup_requires_completed_predecessor(utility_execution_env):
    env = utility_execution_env
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)
    _execute_move(env, plan_id, move_item)

    removed = execute_item(
        rmdir_item,
        allowed_roots=[env["root"]],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
        session_factory=env["service"].SessionLocal,
    )

    assert removed.state == "skipped"
    assert removed.reason == "permanent deletion is disabled"
    assert (env["root"] / "B").is_dir()


def test_utility_empty_wrapper_cleanup_requires_same_candidate_binding(utility_execution_env):
    env = utility_execution_env
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)
    _execute_move(env, plan_id, move_item)
    _mark_move_completed(env, plan_id, candidate_id_override="different-candidate")

    removed = execute_item(
        rmdir_item,
        allowed_roots=[env["root"]],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
        session_factory=env["service"].SessionLocal,
    )

    assert removed.state == "skipped"
    assert removed.reason == "permanent deletion is disabled"
    assert (env["root"] / "B").is_dir()


def test_unlink_under_utility_plan_stays_blocked_with_delete_disabled(utility_execution_env):
    env = utility_execution_env
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)
    _execute_move(env, plan_id, move_item)
    _mark_move_completed(env, plan_id)

    unlink_item = OperationItem(
        sequence=rmdir_item.sequence,
        operation="unlink",
        source=rmdir_item.source,
        target=None,
        expected_size=rmdir_item.expected_size,
        expected_hash=rmdir_item.expected_hash,
        state=rmdir_item.state,
        expected_mtime_ns=rmdir_item.expected_mtime_ns,
        expected_device=rmdir_item.expected_device,
        expected_inode=rmdir_item.expected_inode,
    )
    result = execute_item(
        unlink_item,
        allowed_roots=[env["root"]],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
        session_factory=env["service"].SessionLocal,
    )

    assert result.state == "skipped"
    assert result.reason == "permanent deletion is disabled"
    assert (env["root"] / "B").is_dir()


def test_third_party_object_after_move_preserves_wrapper_and_object(utility_execution_env):
    env = utility_execution_env
    root = env["root"]
    plan_id = _generate_frozen_plan(env)
    move_item, rmdir_item = _load_operations(env, plan_id)

    _execute_move(env, plan_id, move_item)
    _mark_move_completed(env, plan_id)
    assert (root / "C").is_dir()
    assert (root / "B").is_dir()

    intruder = root / "B" / "third-party.txt"
    intruder.write_text("must survive", encoding="utf-8")

    removed = execute_item(
        rmdir_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
        session_factory=env["service"].SessionLocal,
    )

    assert removed.state != "completed"
    assert removed.reason != "permanent deletion is disabled"
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


def test_target_appearing_after_validate_is_rechecked_before_execute(utility_execution_env):
    env = utility_execution_env
    root = env["root"]
    plan_id = _generate_frozen_plan(env)

    validation = env["service"].validate_plan(plan_id)
    assert validation["status"] == "ready"

    target = root / "C"
    target.mkdir()
    marker = target / "foreign-after-validate.txt"
    marker.write_text("foreign target", encoding="utf-8")

    with pytest.raises(PlanStaleError) as exc:
        env["service"].execute_plan(plan_id)

    assert any(item["reason"] == "target_appeared" for item in exc.value.stale_items)
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

    aba_plan_id = _generate_frozen_plan(env, wrapper_name="B2", child_name="C2")
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

    _execute_move(env, plan_id, move_item)
    _mark_move_completed(env, plan_id)
    assert (root / "B").is_dir()
    assert list((root / "B").iterdir()) == []

    monkeypatch.setattr(os, "unlink", lambda *a, **k: pytest.fail("FORBIDDEN: os.unlink"))
    monkeypatch.setattr(os, "rmdir", lambda *a, **k: pytest.fail("FORBIDDEN: os.rmdir"))
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: pytest.fail("FORBIDDEN: shutil.rmtree"))

    removed = execute_item(
        rmdir_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=env["quarantine"],
        plan_id=str(plan_id),
        session_factory=env["service"].SessionLocal,
    )

    assert removed.state == "completed"
    assert not (root / "B").exists()
    assert removed.result_path is not None
    assert removed.result_path.is_dir()
