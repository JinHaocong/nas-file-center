from __future__ import annotations

from pathlib import Path

import pytest

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
from app.batch_utilities.single_child_wrapper import discover_single_child_wrappers
from app.db import create_engine_and_session, init_db
from app.models import IndexRoot
from app.workflows.compiler import WorkflowCompiler
from app.workflows.schema import SingleChildWrapperCollapseStep, WorkflowDefinition


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
