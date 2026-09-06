from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import init_db, create_engine_and_session
from app.filters.schema import LeafNode
from app.models import FilterPolicy, IndexRoot, IndexedPath, User
from app.workflows.compiler import WorkflowCompiler
from app.workflows.errors import (
    VirtualGraphCollisionError,
    VirtualGraphCycleError,
    WorkflowBoundaryError,
    WorkflowSafetyLimitExceededError,
)
from app.workflows.schema import (
    FilterStep,
    MoveStep,
    QuarantineStep,
    RenameStep,
    ScanStep,
    TouchStep,
    WorkflowDefinition,
)


@pytest.fixture
def setup_env(tmp_path: Path):
    root_dir = tmp_path / "storage"
    root_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "test.db"

    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file)

    with SessionLocal() as session:
        # Create IndexRoot
        idx_root = IndexRoot(root=str(root_dir))
        session.add(idx_root)
        session.commit()
        root_id = idx_root.id

        # Create physical test files
        f1 = root_dir / "doc1.txt"
        f1.write_text("hello 1")
        f2 = root_dir / "doc2.txt"
        f2.write_text("hello 2")
        f3 = root_dir / "image.jpg"
        f3.write_text("image content")

        # Create IndexedPath rows
        p1 = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(f1),
            relative_path="doc1.txt",
            basename="doc1.txt",
            stem="doc1",
            suffix=".txt",
            size=7,
            mtime_ns=1_000_000_000,
            is_dir=False,
            scan_generation="gen1",
        )
        p2 = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(f2),
            relative_path="doc2.txt",
            basename="doc2.txt",
            stem="doc2",
            suffix=".txt",
            size=7,
            mtime_ns=2_000_000_000,
            is_dir=False,
            scan_generation="gen1",
        )
        p3 = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(f3),
            relative_path="image.jpg",
            basename="image.jpg",
            stem="image",
            suffix=".jpg",
            size=13,
            mtime_ns=3_000_000_000,
            is_dir=False,
            scan_generation="gen1",
        )
        session.add_all([p1, p2, p3])
        session.commit()

    return {
        "engine": engine,
        "SessionLocal": SessionLocal,
        "root_dir": root_dir,
        "quarantine_dir": quarantine_dir,
        "root_id": root_id,
    }


def test_file_workflow_compiler_preview(setup_env):
    SessionLocal = setup_env["SessionLocal"]
    root_dir = setup_env["root_dir"]
    quarantine_dir = setup_env["quarantine_dir"]
    root_id = setup_env["root_id"]

    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan", root_ids=[root_id]),
            FilterStep(id="s2", type="filter", filter=LeafNode(field="extension", operator="eq", value=".txt")),
            RenameStep(id="s3", type="rename", pattern="doc", replacement="file"),
            TouchStep(id="s4", type="touch", mtime_ns=5_000_000_000),
        ],
    )

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root_dir],
            quarantine_root=quarantine_dir,
        )
        res = compiler.compile(wf)
        assert res.matched_count == 2
        assert res.matched_bytes == 14
        assert len(res.planned_operations) == 4  # 2 renames + 2 touches
        assert len(res.compile_digest) == 64

        # Check operations
        renames = [op for op in res.planned_operations if op["operation"] == "rename"]
        touches = [op for op in res.planned_operations if op["operation"] == "touch"]
        assert len(renames) == 2
        assert len(touches) == 2
        assert any("file1.txt" in r["target"] for r in renames)
        assert any("file2.txt" in r["target"] for r in renames)


def test_file_workflow_compiler_collision_intra_step(setup_env):
    SessionLocal = setup_env["SessionLocal"]
    root_dir = setup_env["root_dir"]
    quarantine_dir = setup_env["quarantine_dir"]
    root_id = setup_env["root_id"]

    # Two steps mapping doc1 and doc2 to same.txt
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan", root_ids=[root_id]),
            FilterStep(id="s2", type="filter", filter=LeafNode(field="extension", operator="eq", value=".txt")),
            RenameStep(id="s3", type="rename", pattern="doc1", replacement="same"),
            RenameStep(id="s4", type="rename", pattern="doc2", replacement="same"),
        ],
    )

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root_dir],
            quarantine_root=quarantine_dir,
        )
        with pytest.raises(VirtualGraphCollisionError) as exc:
            compiler.compile(wf)
        assert exc.value.code == "PATH_COLLISION"


def test_file_workflow_compiler_collision_physical_file(setup_env):
    SessionLocal = setup_env["SessionLocal"]
    root_dir = setup_env["root_dir"]
    quarantine_dir = setup_env["quarantine_dir"]
    root_id = setup_env["root_id"]

    # Rename doc1.txt to image.jpg which already physically exists
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan", root_ids=[root_id]),
            FilterStep(id="s2", type="filter", filter=LeafNode(field="name", operator="eq", value="doc1.txt")),
            RenameStep(id="s3", type="rename", pattern="doc1.txt", replacement="image.jpg"),
        ],
    )

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root_dir],
            quarantine_root=quarantine_dir,
        )
        with pytest.raises(VirtualGraphCollisionError) as exc:
            compiler.compile(wf)
        assert exc.value.code == "PATH_COLLISION"


def test_file_workflow_compiler_cycle_detection(setup_env):
    SessionLocal = setup_env["SessionLocal"]
    root_dir = setup_env["root_dir"]
    quarantine_dir = setup_env["quarantine_dir"]
    root_id = setup_env["root_id"]

    # Direct cycle in VirtualPathGraph
    from app.workflows.graph import VirtualCandidate, VirtualPathGraph
    graph = VirtualPathGraph(allowed_roots=[root_dir], quarantine_root=quarantine_dir)
    c1 = VirtualCandidate(
        id=1,
        original_path=str(root_dir / "a.txt"),
        original_root_id=root_id,
        current_path=str(root_dir / "a.txt"),
        current_root_id=root_id,
        size=10,
        mtime_ns=0,
    )
    c2 = VirtualCandidate(
        id=2,
        original_path=str(root_dir / "b.txt"),
        original_root_id=root_id,
        current_path=str(root_dir / "b.txt"),
        current_root_id=root_id,
        size=10,
        mtime_ns=0,
    )
    c1.operations.append({"operation": "rename", "source": str(root_dir / "a.txt"), "target": str(root_dir / "b.txt")})
    c2.operations.append({"operation": "rename", "source": str(root_dir / "b.txt"), "target": str(root_dir / "a.txt")})
    graph.add_candidate(c1)
    graph.add_candidate(c2)

    with pytest.raises(VirtualGraphCycleError) as exc:
        graph.resolve_ordered_operations()
    assert exc.value.code == "PATH_CYCLE"


def test_file_workflow_compiler_safety_limit(setup_env):
    SessionLocal = setup_env["SessionLocal"]
    root_dir = setup_env["root_dir"]
    quarantine_dir = setup_env["quarantine_dir"]
    root_id = setup_env["root_id"]

    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan", root_ids=[root_id]),
            RenameStep(id="s2", type="rename", pattern="doc", replacement="file"),
        ],
    )

    with SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[root_dir],
            quarantine_root=quarantine_dir,
        )
        # Limit set to 1 candidate
        with pytest.raises(WorkflowSafetyLimitExceededError) as exc:
            compiler.compile(wf, max_candidates=1)
        assert exc.value.code == "WORKFLOW_LIMIT_EXCEEDED"
