from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
from app.batch_utilities.single_child_wrapper import discover_single_child_wrappers
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import BatchPlan, BatchPlanItem, IndexRoot
from app.service import FileCenterService
from app.workflows.compiler import WorkflowCompiler
from app.workflows.errors import WorkflowError
from app.workflows.schema import (
    SingleChildWrapperCollapseStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
)


@pytest.mark.parametrize("capability", [False, None])
def test_valid_wrapper_is_nonselectable_when_native_noreplace_is_unavailable(
    tmp_path,
    monkeypatch,
    capability,
):
    root = tmp_path / "root"
    scope = root / "A"
    (scope / "B" / "C").mkdir(parents=True)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: capability,
        raising=False,
    )

    monkeypatch.setattr(
        single_child_wrapper_module,
        "directory_transplant_preflight",
        lambda _path: False,
        raising=False,
    )

    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    decisions = discover_single_child_wrappers(str(scope), str(root))
    after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

    assert len(decisions) == 1
    decision = decisions[0]
    assert Path(decision.wrapper_path).name == "B"
    assert Path(decision.child_path or "").name == "C"
    assert decision.state == "UNSUPPORTED_FILESYSTEM"
    assert decision.selectable is False
    assert decision.capability_reason == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
    assert before == after


def test_utility_preview_transports_unsupported_capability_and_plans_zero_operations(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (root / "B" / "C").mkdir(parents=True)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: False,
    )

    monkeypatch.setattr(
        single_child_wrapper_module,
        "directory_transplant_preflight",
        lambda _path: False,
        raising=False,
    )

    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    with SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        session.add(idx)
        session.commit()
        root_id = idx.id

    definition = WorkflowDefinition(
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
    )

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root],
            quarantine_root=quarantine,
        )
        result = compiler.compile(definition)

    assert result.matched_count == 1
    assert result.planned_operations == []
    assert result.compile_context["selected_candidate_ids"] == []
    candidate = result.compile_context["utility_candidates"][0]
    assert candidate["state"] == "UNSUPPORTED_FILESYSTEM"
    assert candidate["selectable"] is False
    assert candidate["selected"] is False
    assert candidate["capability_reason"] == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"


def test_generate_forced_unsupported_candidate_rejects_stable_code_and_persists_zero_draft(
    tmp_path,
    monkeypatch,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    root = data_dir / "root"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (root / "B" / "C").mkdir(parents=True)

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

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: False,
    )

    monkeypatch.setattr(
        single_child_wrapper_module,
        "directory_transplant_preflight",
        lambda _path: False,
        raising=False,
    )

    preview = service.workflow_service.preview_workflow(
        workflow["id"],
        WorkflowPreviewRequest(page=1, page_size=50),
    )
    candidate = preview["utility_summary"]["candidates"][0]
    assert candidate["state"] == "UNSUPPORTED_FILESYSTEM"
    assert candidate["selectable"] is False
    assert candidate["selected"] is False
    assert candidate["capability_reason"] == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"

    with service.SessionLocal() as session:
        plans_before = session.scalar(select(func.count()).select_from(BatchPlan)) or 0
        items_before = session.scalar(select(func.count()).select_from(BatchPlanItem)) or 0

    with pytest.raises(WorkflowError) as exc:
        service.workflow_service.generate_plan(
            None,
            workflow["id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )

    assert exc.value.code == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
    assert exc.value.status_code == 422
    assert exc.value.details == {"candidate_ids": [candidate["candidate_id"]]}

    with service.SessionLocal() as session:
        plans_after = session.scalar(select(func.count()).select_from(BatchPlan)) or 0
        items_after = session.scalar(select(func.count()).select_from(BatchPlanItem)) or 0

    assert plans_after == plans_before
    assert items_after == items_before
