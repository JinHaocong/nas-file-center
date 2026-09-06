from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.models import FilterPolicy, IndexRoot, OrganizerProfile
from app.service import FileCenterService
from app.workflows.schema import OrganizerProfileSnapshot


@pytest.fixture
def hotfix4_env(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        quarantine_root=quarantine_dir,
        allowed_roots_raw=str(data_dir),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    with service.SessionLocal() as session:
        root1 = IndexRoot(id=1, root=str(data_dir))
        session.add(root1)

        policy = FilterPolicy(
            id=1,
            exclude_dir_names_json=json.dumps([".git", ".recycle", "@eaDir", ".nas-file-center-trash"]),
        )
        session.merge(policy)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"

    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login_resp.status_code == 200

    return {
        "client": client,
        "settings": settings,
        "SessionLocal": service.SessionLocal,
        "service": service,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def test_minimal_defaults_equivalence(hotfix4_env):
    """1. minimal OrganizerProfile defaults == minimal Workflow Snapshot defaults."""
    service = hotfix4_env["service"]
    created = service._validate_profile_payload({"name": "Minimal"})
    snapshot = OrganizerProfileSnapshot(name="Minimal")

    assert snapshot.name == "Minimal"
    assert snapshot.description is None
    assert snapshot.root is None
    assert snapshot.recursive is False
    assert snapshot.image_extensions == ["jpg", "jpeg", "png", "webp"]
    assert snapshot.video_extensions == ["mp4", "mov", "mkv"]
    assert snapshot.rename_template == "{name}"
    assert snapshot.statistics_template == "[{images}P {videos}V {size}]"
    assert snapshot.preserve_tags == []
    assert snapshot.cleanup_patterns == []
    assert snapshot.numbering_mode == "none"
    assert snapshot.numbering_start == 1
    assert snapshot.numbering_padding == 3
    assert snapshot.mtime_mode == "none"
    assert snapshot.mtime_delay_seconds == 2.0

    # Ensure exact equivalence with FileCenterService validation
    assert snapshot.image_extensions == json.loads(created["image_extensions"])
    assert snapshot.video_extensions == json.loads(created["video_extensions"])
    assert snapshot.rename_template == created["rename_template"]
    assert snapshot.statistics_template == created["statistics_template"]
    assert snapshot.preserve_tags == json.loads(created["preserve_tags"])
    assert snapshot.cleanup_patterns == json.loads(created["cleanup_patterns"])
    assert snapshot.numbering_mode == created["numbering_mode"]
    assert snapshot.numbering_start == created["numbering_start"]
    assert snapshot.numbering_padding == created["numbering_padding"]
    assert snapshot.mtime_mode == created["mtime_mode"]
    assert snapshot.mtime_delay_seconds == created["mtime_delay_seconds"]


def test_minimal_preview_semantic_equivalence(hotfix4_env):
    """2. minimal direct Organizer preview == minimal Workflow preview: Album -> Album (changed=False)."""
    client = hotfix4_env["client"]
    data_dir = hotfix4_env["data_dir"]
    service = hotfix4_env["service"]

    # Setup Album with a.jpg
    album_dir = data_dir / "Album"
    album_dir.mkdir(parents=True, exist_ok=True)
    (album_dir / "a.jpg").write_bytes(b"content")

    # 1. Direct Organizer Profile with minimal config
    prof_res = client.post(
        "/api/organizer-profiles",
        json={"name": "Minimal"},
    )
    assert prof_res.status_code == 200
    prof_id = prof_res.json()["id"]

    direct_prev = client.post(
        f"/api/organizer-profiles/{prof_id}/preview",
        json={"root": str(data_dir)},
    )
    assert direct_prev.status_code == 200
    direct_data = direct_prev.json()
    assert direct_data["summary"]["changed_directories"] == 0
    direct_proposals = direct_data["proposals"]
    assert len(direct_proposals) == 1
    assert direct_proposals[0]["source"] == str(album_dir)
    assert direct_proposals[0]["target"] == str(album_dir)
    assert direct_proposals[0]["changed"] is False

    # 2. Workflow with minimal snapshot
    wf_payload = {
        "name": "Minimal Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {"name": "Minimal"},
                },
            ],
        },
    }
    wf_res = client.post("/api/workflows", json=wf_payload)
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]

    wf_prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"root_ids": [1]}},
    )
    assert wf_prev.status_code == 200
    wf_data = wf_prev.json()
    wf_items = wf_data["items"]
    # With rename_template="{name}", Album does not change, no touch when mtime_mode="none"
    assert len(wf_items) == 0  # No operations needed since changed is False!


def test_extension_normalization(hotfix4_env):
    """3. .JPG normalization to jpg and deduplication."""
    client = hotfix4_env["client"]
    wf_payload = {
        "name": "Normalization Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Normalized",
                        "image_extensions": [".JPG", "jpg", "PNG"],
                    },
                },
            ],
        },
    }
    res = client.post("/api/workflows", json=wf_payload)
    assert res.status_code == 201
    snapshot = res.json()["definition"]["steps"][1]["profile_snapshot"]
    assert snapshot["image_extensions"] == ["jpg", "png"]


def test_invalid_extension_rejection(hotfix4_env):
    """4. Invalid extensions must be rejected with 422."""
    client = hotfix4_env["client"]
    for bad_ext in ["jpg/bad", "mkv\\bad", "a b"]:
        wf_payload = {
            "name": "Bad Ext Workflow",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {
                        "id": "s2",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "Bad Ext",
                            "image_extensions": [bad_ext],
                        },
                    },
                ],
            },
        }
        res = client.post("/api/workflows", json=wf_payload)
        assert res.status_code == 422, f"Expected 422 for extension {bad_ext}, got {res.status_code}"


def test_whitespace_only_name_rejection(hotfix4_env):
    """5. Whitespace-only or empty name must be rejected with 422."""
    client = hotfix4_env["client"]
    for bad_name in ["   ", "", "\t", "  \n "]:
        wf_payload = {
            "name": "Bad Name Workflow",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {
                        "id": "s2",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": bad_name,
                        },
                    },
                ],
            },
        }
        res = client.post("/api/workflows", json=wf_payload)
        assert res.status_code == 422, f"Expected 422 for name {bad_name!r}, got {res.status_code}"


def test_preserve_tags_trim_drop_empty_cap(hotfix4_env):
    """6. preserve_tags must trim each tag, drop empty strings, and cap at 20."""
    client = hotfix4_env["client"]
    raw_tags = ["  HDR  ", "", " RAW ", "  ", "4K"] + [f"tag{i}" for i in range(25)]
    wf_payload = {
        "name": "Tags Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Tags Test",
                        "preserve_tags": raw_tags,
                    },
                },
            ],
        },
    }
    res = client.post("/api/workflows", json=wf_payload)
    assert res.status_code == 201
    saved_tags = res.json()["definition"]["steps"][1]["profile_snapshot"]["preserve_tags"]
    assert len(saved_tags) == 20
    assert saved_tags[0] == "HDR"
    assert saved_tags[1] == "RAW"
    assert saved_tags[2] == "4K"
    assert "" not in saved_tags


def test_full_existing_profile_roundtrip(hotfix4_env):
    """7. Full existing OrganizerProfile round-trip still passes."""
    client = hotfix4_env["client"]
    service = hotfix4_env["service"]

    profile_payload = {
        "name": "Full Profile",
        "description": "Roundtrip test",
        "recursive": False,
        "image_extensions": ["jpg", "png"],
        "video_extensions": ["mp4"],
        "rename_template": "{index} - {name} {statistics}",
        "statistics_template": "[{images}P{?videos: {videos}V} {size}]",
        "preserve_tags": ["HDR", "RAW"],
        "cleanup_patterns": ["\\[old\\]"],
        "numbering_mode": "sequential",
        "numbering_start": 1,
        "numbering_padding": 3,
        "mtime_mode": "ordered",
        "mtime_delay_seconds": 2.0,
    }
    created = service.create_organizer_profile(user_id=1, payload=profile_payload)
    with service.SessionLocal() as session:
        prof_obj = session.get(OrganizerProfile, created["id"])
        serialized = FileCenterService._serialize_organizer_profile(prof_obj)

    provenance = {"id", "user_id", "slug", "builtin_version", "is_builtin", "created_at", "updated_at"}
    snapshot = {k: v for k, v in serialized.items() if k not in provenance}

    wf_payload = {
        "name": "Full Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": snapshot,
                },
            ],
        },
    }
    res = client.post("/api/workflows", json=wf_payload)
    assert res.status_code == 201


def test_sequential_and_ordered_still_pass(hotfix4_env):
    """8. sequential and ordered options still pass."""
    client = hotfix4_env["client"]
    wf_payload = {
        "name": "Seq Ordered Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Seq Ordered",
                        "numbering_mode": "sequential",
                        "numbering_start": 1,
                        "numbering_padding": 3,
                        "mtime_mode": "ordered",
                        "mtime_delay_seconds": 2.0,
                    },
                },
            ],
        },
    }
    res = client.post("/api/workflows", json=wf_payload)
    assert res.status_code == 201


def test_invalid_enum_numeric_cases_still_422(hotfix4_env):
    """9. Invalid enum / numeric cases still return 422."""
    client = hotfix4_env["client"]

    bad_snapshots = [
        {"name": "T", "numbering_mode": "continuous"},
        {"name": "T", "numbering_mode": "per_folder"},
        {"name": "T", "mtime_mode": "delay"},
        {"name": "T", "mtime_mode": "preserve"},
        {"name": "T", "numbering_start": -1},
        {"name": "T", "numbering_start": True},
        {"name": "T", "numbering_padding": 0},
        {"name": "T", "numbering_padding": 11},
        {"name": "T", "numbering_padding": True},
        {"name": "T", "mtime_delay_seconds": True},
        {"name": "T", "mtime_delay_seconds": False},
        {"name": "T", "mtime_delay_seconds": 61.0},
        {"name": "T", "mtime_delay_seconds": -0.5},
    ]

    for bad in bad_snapshots:
        wf_payload = {
            "name": "Bad Case",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {"id": "s2", "type": "organize", "profile_snapshot": bad},
                ],
            },
        }
        res = client.post("/api/workflows", json=wf_payload)
        assert res.status_code == 422, f"Expected 422 for {bad}, got {res.status_code}"
