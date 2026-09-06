import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, IndexRoot, IndexedPath, User, Workflow
from app.service import FileCenterService


@pytest.fixture
def workflow_test_env(tmp_path: Path):
    data = tmp_path / "data"
    media = data / "media"
    media.mkdir(parents=True, exist_ok=True)
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

    # Physical test files
    f1 = media / "movie1.mkv"
    f1.write_text("movie data 1")
    f2 = media / "movie2.mkv"
    f2.write_text("movie data 2")

    settings = Settings(
        config_dir=config,
        data_mount=data,
        quarantine_dir=quarantine,
        allowed_roots_raw=f"{data},{media}",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    with service.SessionLocal() as session:
        idx_root = IndexRoot(root=str(media), last_indexed_at=None)
        session.add(idx_root)
        session.commit()
        root_id = idx_root.id

        paths = [
            IndexedPath(
                root_key=str(media),
                absolute_path=str(f1),
                relative_path="movie1.mkv",
                basename="movie1.mkv",
                stem="movie1",
                suffix=".mkv",
                size=len("movie data 1"),
                mtime_ns=1000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key=str(media),
                absolute_path=str(f2),
                relative_path="movie2.mkv",
                basename="movie2.mkv",
                stem="movie2",
                suffix=".mkv",
                size=len("movie data 2"),
                mtime_ns=2000,
                is_dir=False,
                scan_generation="gen1",
            ),
        ]
        session.add_all(paths)

        # Create normal member user
        member = User(
            username="member1",
            password_hash=hash_password("MemberPassword123!"),
            role="member",
            is_active=True,
        )
        session.add(member)
        session.commit()

    app = create_app(settings)

    # Admin client
    admin_client = TestClient(app)
    admin_client.headers["Origin"] = "http://testserver"
    res_admin = admin_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert res_admin.status_code == 200

    # Member client
    member_client = TestClient(app)
    member_client.headers["Origin"] = "http://testserver"
    res_member = member_client.post(
        "/api/auth/login",
        json={"username": "member1", "password": "MemberPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert res_member.status_code == 200

    # Unauthenticated client
    unauth_client = TestClient(app)
    unauth_client.headers["Origin"] = "http://testserver"

    return {
        "admin_client": admin_client,
        "member_client": member_client,
        "unauth_client": unauth_client,
        "root_id": root_id,
        "media": media,
        "service": service,
    }


def test_workflow_rbac(workflow_test_env):
    admin = workflow_test_env["admin_client"]
    member = workflow_test_env["member_client"]
    unauth = workflow_test_env["unauth_client"]
    root_id = workflow_test_env["root_id"]

    valid_payload = {
        "name": "RBAC Test WF",
        "description": "testing rbac",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [root_id]},
                {"id": "s2", "type": "rename", "pattern": "movie", "replacement": "film"},
            ],
        },
    }

    # 1. Unauthenticated -> 401
    assert unauth.get("/api/workflows").status_code == 401
    assert unauth.post("/api/workflows", json=valid_payload).status_code == 401

    # 2. Member write actions -> 403
    res = member.post("/api/workflows", json=valid_payload)
    assert res.status_code == 403

    # Create with admin
    create_res = admin.post("/api/workflows", json=valid_payload)
    assert create_res.status_code == 201
    wf_id = create_res.json()["id"]

    # Member update / delete / rollback -> 403
    assert member.put(f"/api/workflows/{wf_id}", json={"expected_current_revision": 1, "name": "Hack"}).status_code == 403
    assert member.delete(f"/api/workflows/{wf_id}").status_code == 403
    assert member.post(f"/api/workflows/{wf_id}/rollback", json={"expected_current_revision": 1, "target_revision": 1}).status_code == 403

    # Member read actions -> 200
    assert member.get("/api/workflows").status_code == 200
    assert member.get(f"/api/workflows/{wf_id}").status_code == 200
    assert member.get(f"/api/workflows/{wf_id}/revisions").status_code == 200
    assert member.get(f"/api/workflows/{wf_id}/revisions/1").status_code == 200


def test_workflow_crud_optimistic_locking(workflow_test_env):
    admin = workflow_test_env["admin_client"]
    root_id = workflow_test_env["root_id"]

    # Create
    create_res = admin.post(
        "/api/workflows",
        json={
            "name": "Initial WF",
            "description": "v1",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [root_id]},
                    {"id": "s2", "type": "rename", "pattern": "movie", "replacement": "video"},
                ],
            },
        },
    )
    assert create_res.status_code == 201
    wf = create_res.json()
    wf_id = wf["id"]
    assert wf["current_revision"] == 1
    assert wf["definition_sha256"]

    # Update definition with correct expected_current_revision=1 -> revision becomes 2
    update_res = admin.put(
        f"/api/workflows/{wf_id}",
        json={
            "expected_current_revision": 1,
            "name": "Updated WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [root_id]},
                    {"id": "s2", "type": "rename", "pattern": "movie", "replacement": "cinema"},
                ],
            },
        },
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["current_revision"] == 2
    assert updated["name"] == "Updated WF"

    # Stale update with expected_current_revision=1 -> 409 Conflict
    conflict_res = admin.put(
        f"/api/workflows/{wf_id}",
        json={
            "expected_current_revision": 1,
            "name": "Stale WF",
        },
    )
    assert conflict_res.status_code == 409
    assert conflict_res.json()["error"] == "WORKFLOW_REVISION_CONFLICT"


def test_workflow_rollback_and_archive(workflow_test_env):
    admin = workflow_test_env["admin_client"]
    member = workflow_test_env["member_client"]
    root_id = workflow_test_env["root_id"]

    # Create
    create_res = admin.post(
        "/api/workflows",
        json={
            "name": "Rollback WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [root_id]},
                    {"id": "s2", "type": "rename", "pattern": "movie", "replacement": "v1"},
                ],
            },
        },
    )
    wf_id = create_res.json()["id"]

    # Update to rev 2
    admin.put(
        f"/api/workflows/{wf_id}",
        json={
            "expected_current_revision": 1,
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [root_id]},
                    {"id": "s2", "type": "rename", "pattern": "movie", "replacement": "v2"},
                ],
            },
        },
    )

    # Rollback to revision 1 with expected_current_revision=2 -> creates revision 3
    rb_res = admin.post(
        f"/api/workflows/{wf_id}/rollback",
        json={
            "target_revision": 1,
            "expected_current_revision": 2,
        },
    )
    assert rb_res.status_code == 200
    rolled_back = rb_res.json()
    assert rolled_back["current_revision"] == 3
    assert rolled_back["definition"]["steps"][1]["replacement"] == "v1"

    # Delete (archive)
    del_res = admin.delete(f"/api/workflows/{wf_id}")
    assert del_res.status_code == 200
    assert del_res.json() == {"status": "ok", "archived": True}

    # Check list: not in list by default
    list_res = member.get("/api/workflows")
    assert not any(w["id"] == wf_id for w in list_res.json())

    # Included when include_archived=true
    list_archived = member.get("/api/workflows?include_archived=true")
    assert any(w["id"] == wf_id for w in list_archived.json())

    # Actions on archived workflow are rejected
    assert admin.put(f"/api/workflows/{wf_id}", json={"expected_current_revision": 3, "name": "new"}).status_code == 400
    assert member.post(f"/api/workflows/{wf_id}/preview", json={}).status_code == 400
    assert member.post(f"/api/workflows/{wf_id}/generate-plan", json={}).status_code == 400


def test_workflow_unsupported_step_rejection(workflow_test_env):
    admin = workflow_test_env["admin_client"]
    root_id = workflow_test_env["root_id"]

    # Reject dedupe
    res_dedupe = admin.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [root_id]},
                    {"id": "s2", "type": "dedupe"},
                ],
            },
        },
    )
    assert res_dedupe.status_code == 400
    assert res_dedupe.json()["error"] == "UNSUPPORTED_STEP"

    # Reject copy
    res_copy = admin.post(
        "/api/workflows",
        json={
            "name": "Copy WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [root_id]},
                    {"id": "s2", "type": "copy"},
                ],
            },
        },
    )
    assert res_copy.status_code == 400
    assert res_copy.json()["error"] == "UNSUPPORTED_STEP"


def test_workflow_preview_and_generate_plan(workflow_test_env):
    admin = workflow_test_env["admin_client"]
    member = workflow_test_env["member_client"]
    root_id = workflow_test_env["root_id"]
    service = workflow_test_env["service"]

    # Create valid workflow
    create_res = admin.post(
        "/api/workflows",
        json={
            "name": "Preview Plan WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [root_id]},
                    {"id": "s2", "type": "rename", "pattern": "movie", "replacement": "film"},
                    {"id": "s3", "type": "touch", "mtime_ns": 999999},
                ],
            },
        },
    )
    wf_id = create_res.json()["id"]

    # 1. Preview by member
    preview_res = member.post(f"/api/workflows/{wf_id}/preview", json={"page": 1, "page_size": 10})
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert preview_data["matched_count"] == 2
    assert preview_data["planned_operations_count"] == 4  # 2 renames + 2 touches
    assert preview_data["compile_digest"]
    assert len(preview_data["items"]) == 4

    # Verify zero batch plans in DB after preview
    with service.SessionLocal() as session:
        plans_count = len(session.scalars(select(BatchPlan)).all())
        assert plans_count == 0

    # 2. Generate Plan with digest mismatch -> 409
    bad_gen = member.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"expected_compile_digest": "bad_digest_hash"},
    )
    assert bad_gen.status_code == 409
    assert bad_gen.json()["error"] == "COMPILE_DIGEST_MISMATCH"

    # 3. Generate Plan with correct digest -> 201 Created
    gen_res = member.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"expected_compile_digest": preview_data["compile_digest"]},
    )
    assert gen_res.status_code == 201
    plan_info = gen_res.json()
    assert plan_info["status"] == "draft"
    assert plan_info["expected_changes"] == 4
    plan_id = plan_info["plan_id"]

    # Verify Plan & Items in DB
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "draft"
        assert len(plan.items) == 4

        # Verify physical identity separation: expected_* MUST be 0!
        for item in plan.items:
            assert item.expected_inode == 0
            assert item.expected_device == 0
            assert item.expected_mtime_ns == 0
            assert item.state == "pending"
