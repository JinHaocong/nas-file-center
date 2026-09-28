from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module

from app.config import Settings
from app.exceptions import StateConflictError
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, IndexRoot


def _client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    app = create_app(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=data / ".trash",
            allow_mutation=True,
            allow_delete=False,
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
        )
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login.status_code == 200
    return app, client, data


def _rules(*, file_numbering: bool = False, wrapper: bool = False):
    return {
        "version": 1,
        "directory_depth": {"enabled": False, "rename_from_depth": 2},
        "file_numbering": {
            "enabled": file_numbering,
            "start": 1,
            "padding": 3,
            "sort": "natural_name",
            "extension_mode": "preserve",
        },
        "latest_child_prefix": {
            "enabled": False,
            "prefix": "New ",
            "timestamp": "mtime_ns",
        },
        "single_child_wrapper_collapse": {
            "enabled": wrapper,
            "wrapper_depth": 2,
            "child_type": "directory",
        },
    }


def _create_profile(client: TestClient, root: Path, rules: dict) -> int:
    response = client.post(
        "/api/organizer-profiles",
        json={
            "name": "advanced-plan",
            "root": str(root),
            "recursive": True,
            "rename_template": "{name}",
            "advanced_rules": rules,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _plan_count(app) -> int:
    with app.state.service.SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(BatchPlan)) or 0


def test_advanced_plan_requires_matching_preview_digest_and_persists_zero_on_mismatch(tmp_path: Path):
    app, client, data = _client(tmp_path)
    root = data / "Organizer"
    parent = root / "A"
    parent.mkdir(parents=True)
    (parent / "photo.JPG").write_bytes(b"x")

    profile_id = _create_profile(client, root, _rules(file_numbering=True))
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert preview.status_code == 200, preview.text
    digest = preview.json()["preview_digest"]

    before = _plan_count(app)

    missing = client.post(f"/api/organizer-profiles/{profile_id}/plan", json={})
    assert missing.status_code == 400
    assert "expected_preview_digest" in missing.json()["detail"]
    assert _plan_count(app) == before

    mismatch = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": "0" * 64},
    )
    assert mismatch.status_code == 400
    assert "Preview 已变化" in mismatch.json()["detail"]
    assert _plan_count(app) == before

    matched = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": digest},
    )
    assert matched.status_code == 200, matched.text
    assert _plan_count(app) == before + 1


def test_preview_digest_rejects_same_path_inode_replacement(tmp_path: Path):
    app, client, data = _client(tmp_path)
    root = data / "Organizer"
    parent = root / "A"
    parent.mkdir(parents=True)
    source = parent / "photo.JPG"
    source.write_bytes(b"x")

    profile_id = _create_profile(client, root, _rules(file_numbering=True))
    preview_response = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert preview_response.status_code == 200
    preview = preview_response.json()
    before = _plan_count(app)

    replacement = parent / "replacement.JPG"
    replacement.write_bytes(b"x")
    replacement.replace(source)

    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    assert created.status_code == 400
    assert "Preview 已变化" in created.json()["detail"]
    assert _plan_count(app) == before


def test_advanced_rename_plan_uses_dedicated_metadata_and_preserves_suffix(tmp_path: Path):
    app, client, data = _client(tmp_path)
    root = data / "Organizer"
    parent = root / "A"
    parent.mkdir(parents=True)
    source = parent / "photo.JPG"
    source.write_bytes(b"abc")

    profile_id = _create_profile(client, root, _rules(file_numbering=True))
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()

    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    assert created.status_code == 200, created.text
    plan_id = created.json()["id"]

    with app.state.service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        metadata = json.loads(plan.metadata_json)
        assert metadata["organizer_advanced"] is True
        assert metadata["organizer_stage"] == "rename"
        assert metadata["preview_digest"] == preview["preview_digest"]
        assert metadata["source_snapshot_digest"] == preview["source_snapshot_digest"]

        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert len(items) == 1
        assert items[0].operation == "rename"
        assert items[0].source_path == str(source)
        assert Path(items[0].target_path or "").name == "001.JPG"
        item_meta = json.loads(items[0].metadata_json)
        assert item_meta["proposal_type"] == "file_rename"
        assert item_meta["object_type"] == "file"
        assert item_meta["organizer_generated_snapshot"]["inode"] > 0


def test_wrapper_stage_generates_stage_a_structural_draft(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: True,
    )
    app, client, data = _client(tmp_path)
    root = data / "Organizer"
    (root / "A" / "Wrapper" / "Child").mkdir(parents=True)

    profile_id = _create_profile(client, root, _rules(wrapper=True))
    preview_response = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["structural_required"] is True

    before = _plan_count(app)
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    assert created.status_code == 200, created.text
    assert _plan_count(app) == before + 1

    with app.state.service.SessionLocal() as session:
        plan = session.get(BatchPlan, created.json()["id"])
        assert plan is not None
        metadata = json.loads(plan.metadata_json)
        assert metadata["organizer_stage"] == "structural"
        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan.id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert [item.operation for item in items] == ["move", "rmdir_empty"]


def test_freeze_rejects_source_identity_change_after_advanced_plan_generation(tmp_path: Path):
    app, client, data = _client(tmp_path)
    root = data / "Organizer"
    parent = root / "A"
    parent.mkdir(parents=True)
    source = parent / "photo.JPG"
    source.write_bytes(b"before")

    profile_id = _create_profile(client, root, _rules(file_numbering=True))
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    assert created.status_code == 200, created.text

    source.write_bytes(b"after-content-is-different")

    with pytest.raises(StateConflictError, match="ORGANIZER_SOURCE_CHANGED_SINCE_GENERATE"):
        app.state.service.freeze_plan(created.json()["id"])


def test_workflow_advanced_organizer_requires_preview_digest_and_persists_bound_plan(tmp_path: Path):
    app, client, data = _client(tmp_path)
    root = data / "WorkflowOrganizer"
    parent = root / "A"
    parent.mkdir(parents=True)
    source = parent / "movie.MKV"
    source.write_bytes(b"workflow")

    with app.state.service.SessionLocal() as session:
        index_root = IndexRoot(root=str(root))
        session.add(index_root)
        session.commit()
        session.refresh(index_root)
        root_id = index_root.id

    create = client.post(
        "/api/workflows",
        json={
            "name": "advanced-organizer-workflow",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "scan", "type": "scan", "root_ids": [root_id]},
                    {
                        "id": "organize",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "advanced-workflow",
                            "recursive": True,
                            "rename_template": "{name}",
                            "statistics_template": "[{files}F]",
                            "advanced_rules": _rules(file_numbering=True),
                        },
                    },
                ],
            },
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = create.json()["id"]

    preview_response = client.post(f"/api/workflows/{workflow_id}/preview", json={})
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    organizer_summary = preview["organizer_summary"]
    assert organizer_summary["advanced_enabled"] is True
    assert organizer_summary["structural_required"] is False
    assert len(organizer_summary["preview_digest"]) == 64

    before = _plan_count(app)

    missing = client.post(
        f"/api/workflows/{workflow_id}/generate-plan",
        json={"expected_compile_digest": preview["compile_digest"]},
    )
    assert missing.status_code == 409
    assert _plan_count(app) == before

    created = client.post(
        f"/api/workflows/{workflow_id}/generate-plan",
        json={
            "expected_compile_digest": preview["compile_digest"],
            "expected_preview_digest": organizer_summary["preview_digest"],
        },
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["plan_id"]
    assert _plan_count(app) == before + 1

    with app.state.service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        metadata = json.loads(plan.metadata_json)
        assert metadata["workflow_mode"] == "organizer"
        assert metadata["organizer_advanced"] is True
        assert metadata["organizer_stage"] == "rename"
        assert metadata["organizer_preview_digest"] == organizer_summary["preview_digest"]

        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert len(items) == 1
        assert items[0].operation == "rename"
        item_meta = json.loads(items[0].metadata_json)
        assert item_meta["preview_only"] is False
        assert item_meta["organizer_generated_snapshot"]["inode"] > 0
