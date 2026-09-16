import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
from app.batch_utilities.errors import BatchUtilityPreviewChangedError
from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, IndexRoot
from app.service import FileCenterService
from app.workflows.errors import WorkflowDigestMismatchError
from app.workflows.schema import (
    SingleChildWrapperCollapseStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
)


@pytest.fixture
def utility_service_env(tmp_path):
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
            name="Collapse wrappers",
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
        "root_id": root_id,
        "root": root,
        "tmp_path": tmp_path,
    }


def _preview(env):
    return env["service"].workflow_service.preview_workflow(
        env["workflow_id"],
        WorkflowPreviewRequest(page=1, page_size=50),
    )


def _candidate(preview: dict, wrapper_name: str) -> dict:
    return next(
        c
        for c in preview["utility_summary"]["candidates"]
        if Path(c["wrapper_path"]).name == wrapper_name
    )


def _plan_count(env) -> int:
    with env["service"].SessionLocal() as session:
        return len(session.scalars(select(BatchPlan)).all())


def test_generate_selected_subset_persists_exact_pair_and_no_filesystem_mutation(utility_service_env):
    env = utility_service_env
    root = env["root"]
    (root / "B1" / "C1").mkdir(parents=True)
    (root / "B2" / "C2").mkdir(parents=True)

    preview = _preview(env)
    assert _plan_count(env) == 0
    b2 = _candidate(preview, "B2")

    generated = env["service"].workflow_service.generate_plan(
        None,
        env["workflow_id"],
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=[b2["candidate_id"]],
        ),
    )

    assert generated["status"] == "draft"
    assert generated["expected_changes"] == 2
    assert (root / "B2" / "C2").is_dir()
    assert not (root / "C2").exists()

    with env["service"].SessionLocal() as session:
        plan = session.get(BatchPlan, generated["plan_id"])
        assert plan is not None
        assert plan.status == "draft"
        metadata = json.loads(plan.metadata_json or "{}")
        assert metadata["workflow_mode"] == "utility"
        assert metadata["runtime_inputs"] == {
            "root_id": env["root_id"],
            "subpath": "",
        }
        items = session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan.id)
            .order_by(BatchPlanItem.sequence.asc())
        ).all()
        assert [(item.operation, item.source_path, item.target_path) for item in items] == [
            ("move", str(root / "B2" / "C2"), str(root / "C2")),
            ("rmdir_empty", str(root / "B2"), None),
        ]
        assert all("B1" not in item.source_path for item in items)


@pytest.mark.parametrize("mutation", ["target", "hidden", "aba"])
def test_generate_rejects_discovery_change_and_persists_zero_draft(utility_service_env, mutation):
    env = utility_service_env
    root = env["root"]
    (root / "B1" / "C1").mkdir(parents=True)

    preview = _preview(env)
    candidate = _candidate(preview, "B1")
    assert _plan_count(env) == 0

    if mutation == "target":
        (root / "C1").mkdir()
    elif mutation == "hidden":
        (root / "B1" / ".hidden").write_text("changed")
    else:
        old_child = env["tmp_path"] / "old-C1"
        (root / "B1" / "C1").rename(old_child)
        (root / "B1" / "C1").mkdir()

    with pytest.raises(WorkflowDigestMismatchError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )

    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0


def test_generate_wrapper_detach_during_recompile_is_preview_changed_with_zero_draft(
    utility_service_env,
    monkeypatch,
):
    env = utility_service_env
    root = env["root"]
    wrapper = root / "B1"
    (wrapper / "C1").mkdir(parents=True)

    preview = _preview(env)
    candidate = _candidate(preview, "B1")
    assert _plan_count(env) == 0

    detached = env["tmp_path"] / "detached-B1"
    real_scandir = os.scandir
    scandir_count = 0
    swapped = False

    def swap_wrapper_before_generate_wrapper_scan(path):
        nonlocal scandir_count, swapped
        scandir_count += 1
        if scandir_count == 2:
            swapped = True
            wrapper.rename(detached)
            (wrapper / "C1").mkdir(parents=True)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_wrapper_before_generate_wrapper_scan)

    with pytest.raises(BatchUtilityPreviewChangedError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )

    assert swapped is True
    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0
    assert (detached / "C1").is_dir()
    assert (wrapper / "C1").is_dir()


def test_generate_child_replacement_during_recompile_is_preview_changed_with_zero_draft(
    utility_service_env,
    monkeypatch,
):
    env = utility_service_env
    root = env["root"]
    wrapper = root / "B1"
    child = wrapper / "C1"
    child.mkdir(parents=True)

    preview = _preview(env)
    candidate = _candidate(preview, "B1")
    assert _plan_count(env) == 0

    detached = env["tmp_path"] / "detached-C1"
    real_entry_exists_at = single_child_wrapper_module._entry_exists_at
    swapped = False

    def swap_child_before_generate_target_check(scope_fd, entry_name, target_path):
        nonlocal swapped
        if not swapped:
            swapped = True
            child.rename(detached)
            child.mkdir()
        return real_entry_exists_at(scope_fd, entry_name, target_path)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "_entry_exists_at",
        swap_child_before_generate_target_check,
    )

    with pytest.raises(BatchUtilityPreviewChangedError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )

    assert swapped is True
    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0
    assert detached.is_dir()
    assert child.is_dir()


def test_candidate_id_from_another_preview_is_rejected(utility_service_env):
    env = utility_service_env
    root = env["root"]
    (root / "B1" / "C1").mkdir(parents=True)

    first = _preview(env)
    old_id = _candidate(first, "B1")["candidate_id"]

    old_child = env["tmp_path"] / "old-C1"
    (root / "B1" / "C1").rename(old_child)
    (root / "B1" / "C1").mkdir()
    second = _preview(env)
    new_id = _candidate(second, "B1")["candidate_id"]
    assert new_id != old_id

    with pytest.raises(WorkflowDigestMismatchError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=second["compile_digest"],
                selected_candidate_ids=[old_id],
            ),
        )

    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0
