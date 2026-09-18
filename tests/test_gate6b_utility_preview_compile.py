from pathlib import Path

import pytest

from app.batch_utilities.errors import BatchUtilitySymlinkBlockedError
from app.db import create_engine_and_session, init_db
from app.models import IndexRoot
from app.workflows.compiler import WorkflowCompiler
from app.workflows.schema import SingleChildWrapperCollapseStep, WorkflowDefinition


def _utility(root_id: int, subpath: str = "") -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version=1,
        mode="utility",
        steps=[
            SingleChildWrapperCollapseStep(
                id="collapse",
                type="single_child_wrapper_collapse",
                root_id=root_id,
                subpath=subpath,
            )
        ],
    )


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _by_wrapper_name(result) -> dict[str, dict]:
    return {
        Path(candidate["wrapper_path"]).name: candidate
        for candidate in result.compile_context["utility_candidates"]
    }


def test_utility_preview_compile_defaults_ready_candidates_selected_and_pairs_actions(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (root / "B1" / "C1" / "D1").mkdir(parents=True)
    (root / "B2" / "C2").mkdir(parents=True)
    (root / "B_conflict" / "Taken").mkdir(parents=True)
    (root / "Taken").write_text("occupied")

    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    with SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        session.add(idx)
        session.commit()
        root_id = idx.id

    before = _tree(root)
    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root],
            quarantine_root=quarantine,
        )
        result = compiler.compile(_utility(root_id))
        repeat = compiler.compile(_utility(root_id))

    assert before == _tree(root)
    assert result.compile_digest == repeat.compile_digest
    assert result.matched_count == 3
    assert result.matched_bytes == 0

    candidates = _by_wrapper_name(result)
    assert candidates["B1"]["state"] == "READY"
    assert candidates["B1"]["selectable"] is True
    assert candidates["B1"]["selected"] is True
    assert candidates["B2"]["state"] == "READY"
    assert candidates["B2"]["selected"] is True
    assert candidates["B_conflict"]["state"] == "TARGET_EXISTS"
    assert candidates["B_conflict"]["selectable"] is False
    assert candidates["B_conflict"]["selected"] is False

    assert [
        (op["sequence"], op["operation"], op["source"], op.get("target"))
        for op in result.planned_operations
    ] == [
        (1, "move", str(root / "B1" / "C1"), str(root / "C1")),
        (2, "rmdir_empty", str(root / "B1"), None),
        (3, "move", str(root / "B2" / "C2"), str(root / "C2")),
        (4, "rmdir_empty", str(root / "B2"), None),
    ]
    # One plan collapses only the wrapper layer B -> C; it must not recursively
    # collapse C1/D1 in the same compile.
    assert not any(op["source"] == str(root / "B1" / "C1" / "D1") for op in result.planned_operations)


def test_utility_preview_compile_supports_regular_file_single_child(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    wrapper = root / "001-1"
    wrapper.mkdir()
    child = wrapper / "001"
    child.write_bytes(b"payload")

    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    with SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        session.add(idx)
        session.commit()
        root_id = idx.id

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root],
            quarantine_root=quarantine,
        )
        result = compiler.compile(_utility(root_id))

    candidate = _by_wrapper_name(result)["001-1"]
    assert candidate["state"] == "READY"
    assert candidate["selectable"] is True
    assert candidate["selected"] is True
    assert candidate["child_object_type"] == "file"
    assert candidate["child_path"] == str(child)
    assert candidate["target_path"] == str(root / "001")

    assert [
        (op["operation"], op["source"], op.get("target"), op["child_object_type"])
        for op in result.planned_operations
    ] == [
        ("move", str(child), str(root / "001"), "file"),
        ("rmdir_empty", str(wrapper), None, "file"),
    ]


def test_utility_compile_explicit_selection_omits_deselected_candidate(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (root / "B1" / "C1").mkdir(parents=True)
    (root / "B2" / "C2").mkdir(parents=True)

    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    with SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        session.add(idx)
        session.commit()
        root_id = idx.id

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root],
            quarantine_root=quarantine,
        )
        preview = compiler.compile(_utility(root_id))
        candidates = _by_wrapper_name(preview)
        selected_id = candidates["B2"]["candidate_id"]
        selected = compiler.compile(
            _utility(root_id),
            selected_candidate_ids=[selected_id],
        )

    assert selected.compile_digest == preview.compile_digest
    assert [op["operation"] for op in selected.planned_operations] == ["move", "rmdir_empty"]
    assert selected.planned_operations[0]["source"] == str(root / "B2" / "C2")
    assert selected.planned_operations[0]["target"] == str(root / "C2")
    assert selected.planned_operations[1]["source"] == str(root / "B2")
    assert all("B1" not in op["source"] for op in selected.planned_operations)


def test_utility_compile_rejects_symlink_authoritative_index_root(tmp_path):
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    (real_root / "B" / "C").mkdir(parents=True)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    with SessionLocal() as session:
        idx = IndexRoot(root=str(linked_root))
        session.add(idx)
        session.commit()
        root_id = idx.id

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[tmp_path],
            quarantine_root=quarantine,
        )
        with pytest.raises(BatchUtilitySymlinkBlockedError):
            compiler.compile(_utility(root_id))
