import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, IndexRoot, IndexedPath, User, Workflow, WorkJob, utcnow
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


def test_latest_scheduled_workflow_run_is_scoped_to_workflow_and_keeps_exact_task_id(workflow_test_env):
    env = workflow_test_env
    admin = env["admin_client"]
    create = admin.post("/api/workflows", json={
        "name": "Latest run",
        "definition": {"schema_version": 1, "mode": "file", "steps": [
            {"id": "scan", "type": "scan", "root_ids": [env["root_id"]]},
        ]},
    })
    assert create.status_code == 201
    workflow = create.json()["id"]
    endpoint = f"/api/workflows/{workflow}/latest-run"
    assert admin.get(endpoint).json() is None
    with env["service"].SessionLocal() as session:
        for task, kind, owner in [
            (9007199254740993, "workflow-scheduled", workflow),
            (9007199254740994, "workflow-scheduled", workflow),
            (9007199254740995, "workflow-scheduled", workflow + 1),
            (9007199254740996, "fclones-scan", workflow),
        ]:
            session.add(WorkJob(id=task, kind=kind, status="running", progress_current=46, progress_total=100,
                                state_json=json.dumps({"workflow_id": owner, "workflow_revision": 1})))
        session.add(WorkJob(id=9007199254740997, kind="workflow-scheduled", state_json="{malformed"))
        session.commit()
    assert env["unauth_client"].get(endpoint).status_code == 401
    response = env["member_client"].get(endpoint)
    assert response.status_code == 200
    assert response.json()["id"] == "9007199254740994"
    assert response.json()["progress"]["percent"] == 46


def _directory_workflow(env):
    root = env["media"].resolve()
    chosen = root / "本次_%归档"
    sibling = root / "本次_%归档-副本"
    with env["service"].SessionLocal() as session:
        index_root = session.get(IndexRoot, env["root_id"])
        index_root.last_indexed_at = utcnow()
        for folder in (chosen, sibling):
            folder.mkdir()
            file = folder / "movie.mkv"
            file.write_text("demo")
            session.add(IndexedPath(
                root_key=str(root), absolute_path=str(file), relative_path=file.relative_to(root).as_posix(),
                basename=file.name, stem=file.stem, suffix=file.suffix, size=4, mtime_ns=1000,
                is_dir=False, scan_generation="gen1",
            ))
        session.commit()
    response = env["admin_client"].post("/api/workflows", json={
        "name": "媒体归档",
        "definition": {"schema_version": 1, "mode": "file", "steps": [
            {"id": "scan", "type": "scan", "root_ids": [env["root_id"]], "subpath": sibling.name},
            {"id": "rename", "type": "rename", "pattern": ".mkv", "replacement": ".mp4"},
            {"id": "touch", "type": "touch", "touch_now": False, "mtime_ns": 42},
        ]},
    })
    assert response.status_code == 201, response.json()
    return response.json()["id"], chosen, sibling


def test_workflow_runtime_directory_keeps_exact_scope_in_preview_plan_and_rebuild(workflow_test_env):
    env = workflow_test_env
    admin = env["admin_client"]
    workflow, chosen, sibling = _directory_workflow(env)
    endpoint = f"/api/workflows/{workflow}"
    inputs = {"directory": str(chosen)}
    preview = admin.post(endpoint + "/preview", json={
        "revision": 1, "runtime_inputs": inputs, "only_changed": True, "page_size": 1,
    })
    assert preview.status_code == 200, preview.json()
    body = preview.json()
    assert body["matched_count"] == 1
    assert body["total_pages"] == 2
    assert body["file_summary"] == {"directory": str(chosen), "operation_counts": {"rename": 1, "touch": 1}}
    assert body["items"][0]["source_path"] == str(chosen / "movie.mkv")
    second_page = admin.post(endpoint + "/preview", json={
        "revision": 1, "runtime_inputs": inputs, "only_changed": True, "page": 2, "page_size": 1,
    }).json()
    assert second_page["compile_digest"] == body["compile_digest"]
    assert second_page["items"][0]["operation"] == "touch"

    # Even with the same operation counts, switching directories invalidates the reviewed digest.
    draft = {"revision": 1, "expected_compile_digest": body["compile_digest"], "runtime_inputs": inputs}
    stale = admin.post(endpoint + "/generate-plan", json={**draft, "runtime_inputs": {"directory": str(sibling)}})
    assert stale.status_code == 409, stale.json()
    generated = admin.post(endpoint + "/generate-plan", json=draft)
    assert generated.status_code == 201, generated.json()
    plan_id = generated.json()["plan_id"]
    with env["service"].SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert json.loads(plan.metadata_json)["runtime_inputs"] == {"root_ids": [env["root_id"]], **inputs}
        plan.status = "stale"
        session.commit()
    rebuild = admin.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
    assert rebuild.status_code == 200, rebuild.json()
    assert rebuild.json()["runtime_inputs"]["directory"] == str(chosen)
    assert all(Path(item["source_path"]).is_relative_to(chosen) for item in rebuild.json()["items"])
    state = admin.get(endpoint).json()
    assert state["current_revision"] == 1
    assert state["definition"]["steps"][0]["subpath"] == sibling.name


def test_workflow_runtime_directory_rejects_link_alias_unindexed_directory_and_mixed_inputs(workflow_test_env):
    env = workflow_test_env
    workflow, chosen, _ = _directory_workflow(env)
    admin = env["admin_client"]
    endpoint = f"/api/workflows/{workflow}/preview"
    alias = chosen.parent / "目录软链接"
    alias.symlink_to(chosen, target_is_directory=True)
    unindexed = chosen.parent / "尚未索引"
    unindexed.mkdir()
    protected = chosen.parent / ".git"
    protected.mkdir()
    for inputs, code in (
        ({"directory": str(alias)}, "WORKFLOW_DIRECTORY_UNAVAILABLE"),
        ({"directory": str(unindexed)}, "WORKFLOW_DIRECTORY_NOT_INDEXED"),
        ({"directory": str(protected)}, "WORKFLOW_DIRECTORY_FORBIDDEN"),
        ({"directory": str(chosen), "root_ids": [env["root_id"]]}, "AMBIGUOUS_RUNTIME_INPUTS"),
        ({"directory": str(chosen), "scan_job_id": 1}, "AMBIGUOUS_RUNTIME_INPUTS"),
    ):
        response = admin.post(endpoint, json={"runtime_inputs": inputs})
        assert response.status_code == 422, response.json()
        assert response.json()["error"]["code"] == code

    (chosen / "movie.mp4").write_text("occupied")
    collision = admin.post(endpoint, json={"runtime_inputs": {"directory": str(chosen)}})
    assert collision.status_code == 409
    assert collision.json()["error"]["details"]["target"] == str(chosen / "movie.mp4")


def test_workflow_runtime_directory_detects_replacement_after_preview(workflow_test_env):
    env = workflow_test_env
    workflow, chosen, _ = _directory_workflow(env)
    admin = env["admin_client"]
    endpoint = f"/api/workflows/{workflow}"
    inputs = {"directory": str(chosen)}
    root_scope = admin.post(endpoint + "/preview", json={"runtime_inputs": {"directory": str(chosen.parent)}})
    assert root_scope.status_code == 200, root_scope.json()
    assert root_scope.json()["file_summary"]["directory"] == str(chosen.parent)
    preview = admin.post(endpoint + "/preview", json={"runtime_inputs": inputs})
    assert preview.status_code == 200, preview.json()

    chosen.rename(chosen.with_name("原目录"))
    chosen.mkdir()
    (chosen / "movie.mkv").write_text("new file at the same path")
    generated = admin.post(endpoint + "/generate-plan", json={
        "revision": 1, "expected_compile_digest": preview.json()["compile_digest"], "runtime_inputs": inputs,
    })
    assert generated.status_code == 409, generated.json()


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
    assert member.delete(f"/api/workflows/{wf_id}?expected_current_revision=1").status_code == 403
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
    err = conflict_res.json()["error"]
    code = err["code"] if isinstance(err, dict) else err
    assert code == "WORKFLOW_REVISION_CONFLICT"


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
    del_res = admin.delete(f"/api/workflows/{wf_id}?expected_current_revision=3")
    assert del_res.status_code == 200
    assert del_res.json() == {"status": "ok", "archived": True}

    # Check list: not in list by default
    list_res = member.get("/api/workflows")
    assert not any(w["id"] == wf_id for w in list_res.json())

    # Included when include_archived=true
    list_archived = member.get("/api/workflows?include_archived=true")
    assert any(w["id"] == wf_id for w in list_archived.json())

    # Actions on archived workflow are rejected with 409
    assert admin.put(f"/api/workflows/{wf_id}", json={"expected_current_revision": 3, "name": "new"}).status_code == 409
    assert member.post(f"/api/workflows/{wf_id}/preview", json={}).status_code == 409
    assert member.post(f"/api/workflows/{wf_id}/generate-plan", json={"expected_compile_digest": "0" * 64}).status_code == 409


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
    assert res_dedupe.status_code == 422
    err = res_dedupe.json()["error"]
    code = err["code"] if isinstance(err, dict) else err
    assert code == "UNSUPPORTED_STEP"

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
    assert res_copy.status_code == 422
    err = res_copy.json()["error"]
    code = err["code"] if isinstance(err, dict) else err
    assert code == "UNSUPPORTED_STEP"


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
        json={"expected_compile_digest": "0" * 64},
    )
    assert bad_gen.status_code == 409
    err = bad_gen.json()["error"]
    code = err["code"] if isinstance(err, dict) else err
    assert code == "PREVIEW_CHANGED"

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
