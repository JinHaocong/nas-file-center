from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.auth.password import hash_password
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.filters.schema import LeafNode
from app.main import create_app
from app.models import BatchPlan, FilterPolicy, IndexRoot, IndexedPath, User, Workflow, WorkflowRevision
from app.service import FileCenterService
from app.workflows.compiler import WorkflowCompiler
from app.workflows.errors import VirtualGraphCollisionError
from app.workflows.graph import VirtualCandidate, VirtualPathGraph
from app.workflows.schema import MoveStep, RenameStep, ScanStep, WorkflowDefinition


@pytest.fixture
def env(tmp_path: Path):
    data = tmp_path / "data"
    media = data / "media"
    archive = data / "archive"
    quarantine = tmp_path / "quarantine"
    config = tmp_path / "config"
    for p in (data, media, archive, quarantine, config):
        p.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        quarantine_dir=quarantine,
        allowed_roots_raw=f"{data},{media},{archive}",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    with service.SessionLocal() as session:
        r1 = IndexRoot(root=str(media))
        r2 = IndexRoot(root=str(archive))
        session.add_all([r1, r2])
        session.commit()
        media_root_id = r1.id
        archive_root_id = r2.id

        f1 = media / "doc1.txt"
        f1.write_text("content 1")
        f2 = media / "doc2.txt"
        f2.write_text("content 2")

        p1 = IndexedPath(
            root_key=str(media),
            absolute_path=str(f1),
            relative_path="doc1.txt",
            basename="doc1.txt",
            stem="doc1",
            suffix=".txt",
            size=len("content 1"),
            mtime_ns=1000,
            is_dir=False,
            scan_generation="g1",
        )
        p2 = IndexedPath(
            root_key=str(media),
            absolute_path=str(f2),
            relative_path="doc2.txt",
            basename="doc2.txt",
            stem="doc2",
            suffix=".txt",
            size=len("content 2"),
            mtime_ns=2000,
            is_dir=False,
            scan_generation="g1",
        )
        session.add_all([p1, p2])
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    res = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert res.status_code == 200

    return {
        "client": client,
        "service": service,
        "media_root_id": media_root_id,
        "archive_root_id": archive_root_id,
        "media": media,
        "archive": archive,
        "quarantine": quarantine,
    }


def test_red_same_entity_chain_ordering(env):
    """
    P1-01 RED:
    A single file is renamed: doc1.txt -> file1.txt, and then moved to archive root.
    Operations for this entity MUST be:
      1. rename: doc1.txt -> file1.txt
      2. move: file1.txt -> archive/file1.txt
    Currently, the compiler topological sort treats file1.txt as a collision/dependency
    and reverses them to (move before rename), causing FileNotFoundError on Freeze!
    """
    media_root_id = env["media_root_id"]
    archive_root_id = env["archive_root_id"]
    service = env["service"]
    media = env["media"]
    quarantine = env["quarantine"]

    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan", root_ids=[media_root_id]),
            RenameStep(id="s2", type="rename", pattern="doc1", replacement="file1"),
            MoveStep(id="s3", type="move", destination_root_id=archive_root_id),
        ],
    )

    with service.SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[media, env["archive"]],
            quarantine_root=quarantine,
        )
        res = compiler.compile(wf)
        ops = [op for op in res.planned_operations if "doc1" in op["source"] or "file1" in op["source"]]
        assert len(ops) == 2
        # FIRST operation MUST be rename from doc1 to file1!
        assert ops[0]["operation"] == "rename", f"Expected first op to be rename, got {ops[0]}"
        assert ops[0]["source"].endswith("doc1.txt")
        assert ops[0]["target"].endswith("file1.txt")
        # SECOND operation MUST be move from file1 to archive!
        assert ops[1]["operation"] == "move", f"Expected second op to be move, got {ops[1]}"
        assert ops[1]["source"].endswith("file1.txt")


def test_red_occupied_target_candidate_does_not_move(env):
    """
    P1-02 RED:
    doc1.txt -> doc2.txt, but doc2.txt is not modified or moved.
    Currently, compiler incorrectly accepts this because doc2.txt is in all_original_paths.
    Expected: PATH_COLLISION!
    """
    media_root_id = env["media_root_id"]
    service = env["service"]
    media = env["media"]
    quarantine = env["quarantine"]

    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan", root_ids=[media_root_id]),
            RenameStep(id="s2", type="rename", pattern="doc1.txt", replacement="doc2.txt"),
        ],
    )

    with service.SessionLocal() as session:
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=[media, env["archive"]],
            quarantine_root=quarantine,
        )
        with pytest.raises(VirtualGraphCollisionError) as exc:
            compiler.compile(wf)
        assert exc.value.code == "PATH_COLLISION"


def test_red_generate_without_digest(env):
    """
    P2-01 RED:
    Generate plan without expected_compile_digest must return HTTP 422, never 201!
    """
    client = env["client"]
    media_root_id = env["media_root_id"]

    create_res = client.post(
        "/api/workflows",
        json={
            "name": "Digest WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [media_root_id]},
                    {"id": "s2", "type": "rename", "pattern": "doc", "replacement": "file"},
                ],
            },
        },
    )
    wf_id = create_res.json()["id"]

    # Post {} without expected_compile_digest
    gen_res = client.post(f"/api/workflows/{wf_id}/generate-plan", json={})
    assert gen_res.status_code == 422, f"Expected 422, got {gen_res.status_code}: {gen_res.text}"


def test_red_historical_revision_preview_and_generate(env):
    """
    P2-02 RED:
    Preview and Generate must accept 'revision' parameter and execute that historical revision!
    """
    client = env["client"]
    media_root_id = env["media_root_id"]

    # Rev 1
    create_res = client.post(
        "/api/workflows",
        json={
            "name": "Hist WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [media_root_id]},
                    {"id": "s2", "type": "rename", "pattern": "doc", "replacement": "v1"},
                ],
            },
        },
    )
    wf_id = create_res.json()["id"]

    # Rev 2
    client.put(
        f"/api/workflows/{wf_id}",
        json={
            "expected_current_revision": 1,
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [media_root_id]},
                    {"id": "s2", "type": "rename", "pattern": "doc", "replacement": "v2"},
                ],
            },
        },
    )

    # Preview rev 1 explicitly
    prev_res = client.post(f"/api/workflows/{wf_id}/preview", json={"revision": 1})
    assert prev_res.status_code == 200
    prev_data = prev_res.json()
    assert prev_data["revision"] == 1
    assert any("v1" in it["target_path"] for it in prev_data["items"] if it.get("target_path"))

    # Generate plan from rev 1 explicitly
    gen_res = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"revision": 1, "expected_compile_digest": prev_data["compile_digest"]},
    )
    assert gen_res.status_code == 201
    plan_id = gen_res.json()["plan_id"]

    # Verify plan metadata records workflow_revision = 1
    service = env["service"]
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        assert meta["workflow_revision"] == 1


def test_red_metadata_only_put_must_bump_revision(env):
    """
    P2-06 RED:
    Any PUT must bump current_revision, even if definition is unchanged.
    """
    client = env["client"]
    media_root_id = env["media_root_id"]

    create_res = client.post(
        "/api/workflows",
        json={
            "name": "Meta WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [media_root_id]},
                    {"id": "s2", "type": "rename", "pattern": "doc", "replacement": "file"},
                ],
            },
        },
    )
    wf_id = create_res.json()["id"]

    # PUT name only
    put_res = client.put(
        f"/api/workflows/{wf_id}",
        json={"expected_current_revision": 1, "name": "Renamed WF"},
    )
    assert put_res.status_code == 200
    assert put_res.json()["current_revision"] == 2, f"Expected revision 2, got {put_res.json()['current_revision']}"


def test_red_archive_requires_expected_current_revision(env):
    """
    P2-06 RED:
    DELETE /api/workflows/{id} must require expected_current_revision.
    """
    client = env["client"]
    media_root_id = env["media_root_id"]

    create_res = client.post(
        "/api/workflows",
        json={
            "name": "Archive WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [media_root_id]},
                    {"id": "s2", "type": "rename", "pattern": "doc", "replacement": "file"},
                ],
            },
        },
    )
    wf_id = create_res.json()["id"]

    # DELETE without expected_current_revision -> 422
    del_res = client.delete(f"/api/workflows/{wf_id}")
    assert del_res.status_code == 422, f"Expected 422 when expected_current_revision missing, got {del_res.status_code}"


def test_red_builtin_workflow_immutable(env):
    """
    P2-06 RED:
    Builtin workflows cannot be modified, archived, or rolled back (409 BUILTIN_WORKFLOW_IMMUTABLE).
    """
    client = env["client"]
    service = env["service"]
    media_root_id = env["media_root_id"]

    # Manually create a builtin workflow in DB
    with service.SessionLocal() as session:
        wf = Workflow(name="Builtin WF", is_builtin=True, current_revision=1)
        session.add(wf)
        session.commit()
        rev = WorkflowRevision(
            workflow_id=wf.id,
            revision=1,
            definition_json=json.dumps({
                "schema_version": 1,
                "mode": "file",
                "steps": [{"id": "s1", "type": "scan", "root_ids": [media_root_id]}],
            }),
            definition_sha256="abc",
        )
        session.add(rev)
        session.commit()
        wf_id = wf.id

    # PUT -> 409 BUILTIN_WORKFLOW_IMMUTABLE
    put_res = client.put(f"/api/workflows/{wf_id}", json={"expected_current_revision": 1, "name": "Changed"})
    assert put_res.status_code == 409
    err = put_res.json().get("error", {})
    code = err.get("code") if isinstance(err, dict) else err
    assert code == "BUILTIN_WORKFLOW_IMMUTABLE"

    # DELETE -> 409 BUILTIN_WORKFLOW_IMMUTABLE
    del_res = client.delete(f"/api/workflows/{wf_id}?expected_current_revision=1")
    assert del_res.status_code == 409
    err = del_res.json().get("error", {})
    code = err.get("code") if isinstance(err, dict) else err
    assert code == "BUILTIN_WORKFLOW_IMMUTABLE"


def test_red_regex_rename_forbidden(env):
    """
    P2-05 RED:
    RenameStep.is_regex is forbidden. Submitting is_regex must be rejected (422).
    """
    client = env["client"]
    media_root_id = env["media_root_id"]

    create_res = client.post(
        "/api/workflows",
        json={
            "name": "Regex WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [media_root_id]},
                    {"id": "s2", "type": "rename", "pattern": r"doc\d+", "replacement": "file", "is_regex": True},
                ],
            },
        },
    )
    assert create_res.status_code == 422, f"Expected 422 for is_regex, got {create_res.status_code}: {create_res.text}"


def test_red_digest_includes_filter_policy_and_runtime_context(env):
    """
    P2-04 RED:
    compile_digest must incorporate FilterPolicy excludes and runtime_inputs.
    If FilterPolicy excludes change, compile_digest MUST change even if matching operations are identical!
    """
    media_root_id = env["media_root_id"]
    service = env["service"]
    media = env["media"]
    quarantine = env["quarantine"]

    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan", root_ids=[media_root_id]),
            RenameStep(id="s2", type="rename", pattern="doc", replacement="file"),
        ],
    )

    with service.SessionLocal() as session:
        compiler1 = WorkflowCompiler(
            session=session,
            allowed_roots=[media, env["archive"]],
            quarantine_root=quarantine,
        )
        res1 = compiler1.compile(wf)

        # Modify FilterPolicy
        policy = session.get(FilterPolicy, 1)
        if policy:
            policy.exclude_dir_names_json = json.dumps([".custom_exclude"])
            policy.updated_at = datetime.now(timezone.utc)
            session.commit()

        compiler2 = WorkflowCompiler(
            session=session,
            allowed_roots=[media, env["archive"]],
            quarantine_root=quarantine,
        )
        res2 = compiler2.compile(wf)

        assert res1.compile_digest != res2.compile_digest, (
            f"Digest should change when FilterPolicy changes! Both are {res1.compile_digest}"
        )


def test_workflow_gate3_freeze_compatibility(env):
    """
    Verify end-to-end Gate3 compatibility:
    A workflow chains rename + move on doc1.txt (doc1.txt -> file1.txt -> archive/file1.txt).
    Generates a draft BatchPlan, and calls service.freeze_plan(plan.id).
    Freeze must succeed without FileNotFoundError, producing a frozen plan with valid snapshots!
    """
    from sqlalchemy import select
    from app.models import BatchPlanItem

    client = env["client"]
    service = env["service"]
    media_root_id = env["media_root_id"]
    archive_root_id = env["archive_root_id"]

    create_res = client.post(
        "/api/workflows",
        json={
            "name": "Gate3 Chained WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [media_root_id]},
                    {"id": "s2", "type": "filter", "filter": {"field": "name", "operator": "eq", "value": "doc1.txt"}},
                    {"id": "s3", "type": "rename", "pattern": "doc1", "replacement": "file1"},
                    {"id": "s4", "type": "move", "destination_root_id": archive_root_id},
                ],
            },
        },
    )
    assert create_res.status_code == 201
    wf_id = create_res.json()["id"]

    prev_res = client.post(f"/api/workflows/{wf_id}/preview", json={})
    assert prev_res.status_code == 200
    digest = prev_res.json()["compile_digest"]
    assert prev_res.json()["planned_operations_count"] == 2

    gen_res = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"expected_compile_digest": digest},
    )
    assert gen_res.status_code == 201
    plan_id = gen_res.json()["plan_id"]

    # Now call freeze_plan directly to verify Gate3 physical freeze snapshot immutability
    frozen_plan = service.freeze_plan(plan_id)
    assert frozen_plan.status == "frozen"
    assert frozen_plan.frozen_at is not None

    with service.SessionLocal() as session:
        items = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id).order_by(BatchPlanItem.sequence)
        ).all()
        assert len(items) == 2
        # First item: rename doc1 -> file1
        assert items[0].operation == "rename"
        assert items[0].expected_inode > 0
        # Second item: move file1 -> archive/file1 (chained!)
        assert items[1].operation == "move"
        assert items[1].expected_inode == items[0].expected_inode
        item1_meta = json.loads(items[1].metadata_json)
        assert item1_meta.get("chained_target") is True
