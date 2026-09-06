from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import time
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.main import create_app
from app.models import (
    FilterPolicy,
    IndexRoot,
    OrganizerProfile,
    Workflow,
    WorkflowRevision,
)
from app.organizers.engine import generate_organizer_proposals
from app.organizers.planner import plan_organizer_operations
from app.service import FileCenterService
from app.workflows.schema import OrganizerProfileSnapshot


@pytest.fixture
def hotfix3_env(tmp_path: Path):
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


# =========================================================================
# CP1: sequential snapshot accepted
# =========================================================================
def test_cp1_sequential_snapshot_accepted(hotfix3_env):
    """CP1: numbering_mode='sequential' must be accepted in OrganizerProfileSnapshot."""
    client = hotfix3_env["client"]
    payload = {
        "name": "Sequential Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Sequential Profile",
                        "numbering_mode": "sequential",
                        "numbering_start": 1,
                        "numbering_padding": 3,
                    },
                },
            ],
        },
    }
    res = client.post("/api/workflows", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    saved = data["definition"]["steps"][1]["profile_snapshot"]
    assert saved["numbering_mode"] == "sequential"
    assert saved["numbering_start"] == 1
    assert saved["numbering_padding"] == 3


# =========================================================================
# CP2: ordered snapshot accepted
# =========================================================================
def test_cp2_ordered_snapshot_accepted(hotfix3_env):
    """CP2: mtime_mode='ordered' must be accepted in OrganizerProfileSnapshot."""
    client = hotfix3_env["client"]
    payload = {
        "name": "Ordered Mtime Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Ordered Profile",
                        "mtime_mode": "ordered",
                        "mtime_delay_seconds": 2.5,
                    },
                },
            ],
        },
    }
    res = client.post("/api/workflows", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    saved = data["definition"]["steps"][1]["profile_snapshot"]
    assert saved["mtime_mode"] == "ordered"
    assert saved["mtime_delay_seconds"] == 2.5


# =========================================================================
# CP3: continuous / per_folder rejected
# =========================================================================
def test_cp3_continuous_and_per_folder_rejected(hotfix3_env):
    """CP3: numbering_mode='continuous' or 'per_folder' must be rejected with 422."""
    client = hotfix3_env["client"]
    for bad_mode in ["continuous", "per_folder", "custom", "unknown"]:
        payload = {
            "name": f"Bad Numbering {bad_mode}",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {
                        "id": "s2",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "Bad Profile",
                            "numbering_mode": bad_mode,
                        },
                    },
                ],
            },
        }
        res = client.post("/api/workflows", json=payload)
        assert res.status_code == 422, f"Expected 422 for numbering_mode={bad_mode}, got {res.status_code}"


# =========================================================================
# CP4: delay / preserve / current rejected
# =========================================================================
def test_cp4_delay_preserve_current_rejected(hotfix3_env):
    """CP4: mtime_mode='delay', 'preserve', 'current' must be rejected with 422."""
    client = hotfix3_env["client"]
    for bad_mode in ["delay", "preserve", "current", "auto", "touch"]:
        payload = {
            "name": f"Bad Mtime {bad_mode}",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {
                        "id": "s2",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "Bad Profile",
                            "mtime_mode": bad_mode,
                        },
                    },
                ],
            },
        }
        res = client.post("/api/workflows", json=payload)
        assert res.status_code == 422, f"Expected 422 for mtime_mode={bad_mode}, got {res.status_code}"


# =========================================================================
# CP5: invalid numbering bounds rejected
# =========================================================================
def test_cp5_invalid_numbering_bounds_rejected(hotfix3_env):
    """CP5: numbering_start < 0 and numbering_padding not in 1..10 must return 422."""
    client = hotfix3_env["client"]

    # numbering_start invalid values
    bad_starts = [-1, -5, "1", True, 1.5]
    for val in bad_starts:
        payload = {
            "name": "Bad Start",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {
                        "id": "s2",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "Bad Start",
                            "numbering_start": val,
                        },
                    },
                ],
            },
        }
        res = client.post("/api/workflows", json=payload)
        assert res.status_code == 422, f"Expected 422 for numbering_start={val}, got {res.status_code}"

    # numbering_padding invalid values
    bad_paddings = [0, -1, 11, 100, 1000, "3", True, 3.5]
    for val in bad_paddings:
        payload = {
            "name": "Bad Padding",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {
                        "id": "s2",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "Bad Padding",
                            "numbering_padding": val,
                        },
                    },
                ],
            },
        }
        res = client.post("/api/workflows", json=payload)
        assert res.status_code == 422, f"Expected 422 for numbering_padding={val}, got {res.status_code}"


# =========================================================================
# CP6: bool / string / invalid delay seconds rejected
# =========================================================================
def test_cp6_bool_string_invalid_delay_rejected(hotfix3_env):
    """CP6: mtime_delay_seconds must reject booleans, strings, out-of-range and non-finite values."""
    client = hotfix3_env["client"]

    bad_delays = [True, False, "2.5", "2", -0.1, -1.0, 60.1, 100.0]
    for val in bad_delays:
        payload = {
            "name": "Bad Delay",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {
                        "id": "s2",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "Bad Delay",
                            "mtime_delay_seconds": val,
                        },
                    },
                ],
            },
        }
        res = client.post("/api/workflows", json=payload)
        assert res.status_code == 422, f"Expected 422 for mtime_delay_seconds={val}, got {res.status_code}"


# =========================================================================
# CP7: Existing OrganizerProfile -> snapshot round-trip
# =========================================================================
def test_cp7_existing_organizer_profile_roundtrip(hotfix3_env):
    """CP7: Create real OrganizerProfile, serialize it, strip provenance fields, and create Workflow."""
    client = hotfix3_env["client"]
    service = hotfix3_env["service"]

    # 1. Create a real OrganizerProfile
    profile_payload = {
        "name": "Canonical Roundtrip Profile",
        "description": "Roundtrip test profile",
        "recursive": False,
        "image_extensions": ["jpg", "png", "webp"],
        "video_extensions": ["mp4", "mkv"],
        "rename_template": "{index} - {name} {statistics}",
        "statistics_template": "[{images}P{?videos: {videos}V} {size}]",
        "preserve_tags": ["HDR", "RAW"],
        "cleanup_patterns": ["\\[.*?\\]"],
        "numbering_mode": "sequential",
        "numbering_start": 1,
        "numbering_padding": 3,
        "mtime_mode": "ordered",
        "mtime_delay_seconds": 2.0,
    }
    created_profile = service.create_organizer_profile(user_id=1, payload=profile_payload)

    # 2. Serialize profile
    with service.SessionLocal() as session:
        profile_obj = session.get(OrganizerProfile, created_profile["id"])
        serialized = FileCenterService._serialize_organizer_profile(profile_obj)

    # 3. Strip provenance fields
    provenance_keys = {"id", "user_id", "slug", "builtin_version", "is_builtin", "created_at", "updated_at"}
    snapshot = {k: v for k, v in serialized.items() if k not in provenance_keys}

    # 4. Create Workflow using snapshot -> must return 201
    wf_payload = {
        "name": "Workflow From Real Profile",
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
    assert res.status_code == 201, res.text
    wf_data = res.json()
    saved_snapshot = wf_data["definition"]["steps"][1]["profile_snapshot"]
    assert saved_snapshot["numbering_mode"] == "sequential"
    assert saved_snapshot["mtime_mode"] == "ordered"
    assert saved_snapshot["numbering_start"] == 1
    assert saved_snapshot["numbering_padding"] == 3
    assert saved_snapshot["mtime_delay_seconds"] == 2.0
    assert saved_snapshot["preserve_tags"] == ["HDR", "RAW"]
    assert saved_snapshot["cleanup_patterns"] == ["\\[.*?\\]"]


# =========================================================================
# CP8: Direct Organizer plan vs Workflow snapshot plan semantic equivalence
# =========================================================================
def test_cp8_semantic_equivalence_direct_organizer_vs_workflow(hotfix3_env):
    """CP8: Workflow with profile snapshot must produce operations semantically equivalent to direct Organizer planner."""
    client = hotfix3_env["client"]
    data_dir = hotfix3_env["data_dir"]
    service = hotfix3_env["service"]

    # Setup directories on disk
    dir1 = data_dir / "Photos Alpha [old]"
    dir1.mkdir(parents=True, exist_ok=True)
    (dir1 / "pic1.jpg").write_bytes(b"image content 1")
    (dir1 / "pic2.png").write_bytes(b"image content 2")

    dir2 = data_dir / "Videos Beta [old]"
    dir2.mkdir(parents=True, exist_ok=True)
    (dir2 / "clip.mp4").write_bytes(b"video content")

    # Profile configuration
    profile_payload = {
        "name": "Equivalence Profile",
        "description": "Semantic equivalence test",
        "recursive": False,
        "image_extensions": ["jpg", "png"],
        "video_extensions": ["mp4"],
        "rename_template": "{index} - {name} {statistics}",
        "statistics_template": "[{images}P{?videos: {videos}V} {size}]",
        "preserve_tags": [],
        "cleanup_patterns": ["\\[old\\]"],
        "numbering_mode": "sequential",
        "numbering_start": 1,
        "numbering_padding": 3,
        "mtime_mode": "ordered",
        "mtime_delay_seconds": 2.0,
    }
    created_profile = service.create_organizer_profile(user_id=1, payload=profile_payload)

    # Direct Organizer execution
    _, direct_proposals = generate_organizer_proposals(
        data_dir,
        allowed_roots=[data_dir],
        image_extensions=profile_payload["image_extensions"],
        video_extensions=profile_payload["video_extensions"],
        rename_template=profile_payload["rename_template"],
        statistics_template=profile_payload["statistics_template"],
        preserve_tags=profile_payload["preserve_tags"],
        cleanup_patterns=profile_payload["cleanup_patterns"],
        numbering_mode=profile_payload["numbering_mode"],
        numbering_start=profile_payload["numbering_start"],
        numbering_padding=profile_payload["numbering_padding"],
        mtime_mode=profile_payload["mtime_mode"],
        mtime_delay_seconds=profile_payload["mtime_delay_seconds"],
        recursive=False,
    )
    direct_ops, direct_cycles = plan_organizer_operations(
        direct_proposals,
        include_touch=True,
        mtime_mode="ordered",
    )
    assert not direct_cycles

    # Workflow execution
    with service.SessionLocal() as session:
        profile_obj = session.get(OrganizerProfile, created_profile["id"])
        serialized = FileCenterService._serialize_organizer_profile(profile_obj)
    provenance_keys = {"id", "user_id", "slug", "builtin_version", "is_builtin", "created_at", "updated_at"}
    snapshot = {k: v for k, v in serialized.items() if k not in provenance_keys}

    wf_payload = {
        "name": "Equivalence Workflow",
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
    wf_res = client.post("/api/workflows", json=wf_payload)
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]

    prev_res = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})
    assert prev_res.status_code == 200, prev_res.text
    wf_ops = prev_res.json()["items"]

    # Semantic comparison: operations count, kinds, sources, and targets
    assert len(wf_ops) == len(direct_ops)

    for w_op, d_op in zip(wf_ops, direct_ops):
        assert w_op["operation"] == d_op["operation"]
        assert w_op["source_path"] == d_op["source"]
        assert w_op["target_path"] == d_op.get("target")

    # Verify numbering order in rename operations
    rename_ops = [op for op in wf_ops if op["operation"] == "rename"]
    assert len(rename_ops) == 2
    assert "001" in rename_ops[0]["target_path"]
    assert "002" in rename_ops[1]["target_path"]

    # Verify touch operations exist and targets match final paths
    touch_ops = [op for op in wf_ops if op["operation"] == "touch"]
    assert len(touch_ops) == 2
    assert touch_ops[0]["source_path"] == rename_ops[0]["target_path"]
    assert touch_ops[1]["source_path"] == rename_ops[1]["target_path"]


# =========================================================================
# CP9: Live profile mutation does not change Workflow revision
# =========================================================================
def test_cp9_live_profile_mutation_isolation(hotfix3_env):
    """CP9: Modifying a live OrganizerProfile must not affect existing Workflow revision snapshot."""
    client = hotfix3_env["client"]
    service = hotfix3_env["service"]

    # 1. Create initial profile A
    profile_a = service.create_organizer_profile(
        user_id=1,
        payload={
            "name": "Profile Initial A",
            "rename_template": "{name} - VERSION_A",
            "numbering_mode": "sequential",
            "numbering_start": 1,
            "numbering_padding": 3,
        },
    )

    with service.SessionLocal() as session:
        profile_obj = session.get(OrganizerProfile, profile_a["id"])
        serialized = FileCenterService._serialize_organizer_profile(profile_obj)
    provenance_keys = {"id", "user_id", "slug", "builtin_version", "is_builtin", "created_at", "updated_at"}
    snapshot = {k: v for k, v in serialized.items() if k not in provenance_keys}

    # 2. Create Workflow with snapshot
    wf_payload = {
        "name": "Isolation Workflow",
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
    wf_res = client.post("/api/workflows", json=wf_payload)
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]

    # 3. Modify live profile to B
    service.update_organizer_profile(
        profile_id=profile_a["id"],
        user_id=1,
        payload={
            "name": "Profile Modified B",
            "rename_template": "{name} - VERSION_B",
            "numbering_mode": "none",
            "numbering_start": 999,
            "numbering_padding": 9,
        },
    )

    # 4. Fetch Workflow Revision 1 and verify snapshot is still Version A
    wf_get = client.get(f"/api/workflows/{wf_id}")
    assert wf_get.status_code == 200
    rev_snapshot = wf_get.json()["definition"]["steps"][1]["profile_snapshot"]
    assert rev_snapshot["name"] == "Profile Initial A"
    assert rev_snapshot["rename_template"] == "{name} - VERSION_A"
    assert rev_snapshot["numbering_mode"] == "sequential"
    assert rev_snapshot["numbering_start"] == 1
    assert rev_snapshot["numbering_padding"] == 3


# =========================================================================
# CP10: Zero unexpected filesystem mutation
# =========================================================================
def test_cp10_zero_unexpected_filesystem_mutation(hotfix3_env):
    """CP10: Workflow preview and compile operations must be strictly read-only and never mutate files."""
    client = hotfix3_env["client"]
    data_dir = hotfix3_env["data_dir"]

    # Create dummy directory structure
    folder = data_dir / "Original Folder"
    folder.mkdir(parents=True, exist_ok=True)
    file1 = folder / "test.jpg"
    file1.write_bytes(b"content")

    # Record snapshot of filesystem before preview
    before_stat = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in data_dir.rglob("*")}

    # Create and preview workflow
    wf_payload = {
        "name": "Read-only Test Workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Read-only Profile",
                        "numbering_mode": "sequential",
                        "mtime_mode": "ordered",
                    },
                },
            ],
        },
    }
    wf_res = client.post("/api/workflows", json=wf_payload)
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]

    # Preview
    client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})

    # Generate draft plan
    client.post(f"/api/workflows/{wf_id}/plans", json={"runtime_inputs": {"root_ids": [1]}})

    # Check filesystem again
    after_stat = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in data_dir.rglob("*")}
    assert before_stat == after_stat


# =========================================================================
# CP11: SQLite integrity and invalid recipes must never persist
# =========================================================================
def test_cp11_sqlite_integrity_and_recipe_immutability(hotfix3_env):
    """CP11: Invalid workflow definitions must never persist and SQLite database must maintain complete integrity."""
    client = hotfix3_env["client"]
    SessionLocal = hotfix3_env["SessionLocal"]

    with SessionLocal() as session:
        initial_wf_count = session.scalar(select(text("COUNT(*)")).select_from(Workflow))
        initial_rev_count = session.scalar(select(text("COUNT(*)")).select_from(WorkflowRevision))

    invalid_payloads = [
        # Bad numbering mode
        {"name": "Bad", "definition": {"schema_version": 1, "mode": "organizer", "steps": [
            {"id": "s1", "type": "scan", "root_ids": [1]},
            {"id": "s2", "type": "organize", "profile_snapshot": {"name": "T", "numbering_mode": "continuous"}},
        ]}},
        # Bad padding
        {"name": "Bad", "definition": {"schema_version": 1, "mode": "organizer", "steps": [
            {"id": "s1", "type": "scan", "root_ids": [1]},
            {"id": "s2", "type": "organize", "profile_snapshot": {"name": "T", "numbering_padding": 1000}},
        ]}},
        # Bad mtime mode
        {"name": "Bad", "definition": {"schema_version": 1, "mode": "organizer", "steps": [
            {"id": "s1", "type": "scan", "root_ids": [1]},
            {"id": "s2", "type": "organize", "profile_snapshot": {"name": "T", "mtime_mode": "delay"}},
        ]}},
        # Bad delay bool
        {"name": "Bad", "definition": {"schema_version": 1, "mode": "organizer", "steps": [
            {"id": "s1", "type": "scan", "root_ids": [1]},
            {"id": "s2", "type": "organize", "profile_snapshot": {"name": "T", "mtime_delay_seconds": True}},
        ]}},
    ]

    for p in invalid_payloads:
        res = client.post("/api/workflows", json=p)
        assert res.status_code == 422

    # Verify counts in SQLite are completely unchanged
    with SessionLocal() as session:
        final_wf_count = session.scalar(select(text("COUNT(*)")).select_from(Workflow))
        final_rev_count = session.scalar(select(text("COUNT(*)")).select_from(WorkflowRevision))
        assert final_wf_count == initial_wf_count
        assert final_rev_count == initial_rev_count

        # PRAGMA integrity_check
        integrity = session.execute(text("PRAGMA integrity_check")).fetchall()
        assert integrity == [("ok",)]
