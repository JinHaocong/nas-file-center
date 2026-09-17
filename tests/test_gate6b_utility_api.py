from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, IndexRoot, User
from app.service import FileCenterService


@pytest.fixture
def utility_api_env(tmp_path):
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
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    with service.SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        session.add(idx)
        member = User(
            username="member1",
            password_hash=hash_password("MemberPassword123!"),
            role="member",
            is_active=True,
        )
        session.add(member)
        session.commit()
        root_id = idx.id

    app = create_app(settings)

    admin = TestClient(app)
    admin.headers["Origin"] = "http://testserver"
    assert admin.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    ).status_code == 200

    member = TestClient(app)
    member.headers["Origin"] = "http://testserver"
    assert member.post(
        "/api/auth/login",
        json={"username": "member1", "password": "MemberPassword123!"},
        headers={"Origin": "http://testserver"},
    ).status_code == 200

    return {
        "service": service,
        "admin": admin,
        "member": member,
        "root": root,
        "root_id": root_id,
    }


def test_utility_api_preview_selection_and_generate_draft(utility_api_env):
    env = utility_api_env
    root = env["root"]
    (root / "B1" / "C1").mkdir(parents=True)
    (root / "B2" / "C2").mkdir(parents=True)
    (root / "B_conflict" / "Taken").mkdir(parents=True)
    (root / "Taken").write_text("occupied")

    create = env["admin"].post(
        "/api/workflows",
        json={
            "name": "Utility wrapper collapse",
            "definition": {
                "schema_version": 1,
                "mode": "utility",
                "steps": [
                    {
                        "id": "collapse",
                        "type": "single_child_wrapper_collapse",
                        "root_id": env["root_id"],
                        "subpath": "",
                    }
                ],
            },
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = create.json()["id"]

    preview = env["member"].post(
        f"/api/workflows/{workflow_id}/preview",
        json={"page": 1, "page_size": 50},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["workflow_mode"] == "utility"
    assert body["preview_source"] == "utility-live-readonly"
    assert body["live_filesystem_verified"] is False
    assert body["planned_operations_count"] == 4

    summary = body["utility_summary"]
    candidates = {
        Path(candidate["wrapper_path"]).name: candidate
        for candidate in summary["candidates"]
    }
    assert candidates["B1"]["state"] == "READY"
    assert candidates["B1"]["selectable"] is True
    assert candidates["B1"]["selected"] is True
    assert candidates["B2"]["selected"] is True
    assert candidates["B_conflict"]["state"] == "TARGET_EXISTS"
    assert candidates["B_conflict"]["selectable"] is False
    assert candidates["B_conflict"]["selected"] is False
    assert summary["selected_candidate_ids"] == [
        candidates["B1"]["candidate_id"],
        candidates["B2"]["candidate_id"],
    ]

    with env["service"].SessionLocal() as session:
        assert len(session.scalars(select(BatchPlan)).all()) == 0

    generated = env["member"].post(
        f"/api/workflows/{workflow_id}/generate-plan",
        json={
            "expected_compile_digest": body["compile_digest"],
            "selected_candidate_ids": [candidates["B2"]["candidate_id"]],
        },
    )
    assert generated.status_code == 201, generated.text
    plan_info = generated.json()
    assert plan_info["status"] == "draft"
    assert plan_info["expected_changes"] == 2

    # Generate persists only a draft; it must not mutate the filesystem.
    assert (root / "B2" / "C2").is_dir()
    assert not (root / "C2").exists()

    with env["service"].SessionLocal() as session:
        plan = session.get(BatchPlan, plan_info["plan_id"])
        assert plan is not None
        assert plan.status == "draft"
        items = session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan.id)
            .order_by(BatchPlanItem.sequence.asc())
        ).all()
        assert [(item.operation, item.source_path, item.target_path) for item in items] == [
            ("move", str(root / "B2" / "C2"), str(root / "C2")),
            ("rmdir_empty", str(root / "B2"), None),
        ]
