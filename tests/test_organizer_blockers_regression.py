from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import OrganizerProfile
from app.organizers.engine import generate_organizer_proposals
from app.organizers.planner import compute_final_paths, plan_organizer_operations
from app.organizers.templates import (
    safe_apply_cleanup_pattern,
    validate_and_normalize_extensions,
    validate_cleanup_patterns,
)


def _get_client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        allow_mutation=True,
        allow_delete=False,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    return client, data, settings


# 1. Blocker 1: Plan Execution with Ordered Touch
def test_plan_execution_with_ordered_touch(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "Album1"
    root.mkdir()
    f1 = root / "001 Old Album [10P 1GB]"
    f1.mkdir()
    (f1 / "pic1.jpg").write_bytes(b"test1")
    (f1 / "pic2.png").write_bytes(b"test2")

    # Create profile with ordered touch
    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Ordered Touch Profile",
            "root": str(root),
            "mtime_mode": "ordered",
            "mtime_delay_seconds": 0.1,
            "rename_template": "{name} {statistics}",
            "statistics_template": "[{images}P {size}]",
            "cleanup_patterns": [r"\s+\[\d+P\s+\d+(?:\.\d+)?[A-Z]+\]$"],
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    proposals = prev_resp.json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["changed"] is True
    target_path = proposals[0]["target"]

    # Create Plan
    plan_resp = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"include_touch": True},
    )
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    # Strict lifecycle: Draft -> Freeze -> Validate -> Execute
    freeze_resp = client.post(f"/api/plans/{plan_id}/freeze")
    assert freeze_resp.status_code == 200
    assert freeze_resp.json()["status"] == "frozen"

    val_resp = client.post(f"/api/plans/{plan_id}/validate")
    assert val_resp.status_code == 200
    assert val_resp.json()["status"] == "ready"

    exec_resp = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert exec_data["status"] == "completed"

    # Verify rename and touch completed
    assert not f1.exists()
    assert Path(target_path).exists()


# 2. Blocker 2: Recursive Nested Rename (Parent [old]/Child [old])
def test_recursive_nested_rename(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "Library"
    root.mkdir()
    parent = root / "Parent [old]"
    parent.mkdir()
    child = parent / "Child [old]"
    child.mkdir()
    (child / "img.jpg").write_bytes(b"image")

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Recursive Profile",
            "root": str(root),
            "recursive": True,
            "mtime_mode": "ordered",
            "rename_template": "{name} [{images}P {size}]",
            "cleanup_patterns": [r"\s+\[old\]$"],
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    assert prev_resp.json()["summary"]["conflicts"] == 0
    assert prev_resp.json()["summary"]["changed_directories"] == 2

    # Create plan
    plan_resp = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")
    exec_resp = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "completed"

    # Assert old paths no longer exist, new paths exist
    assert not parent.exists()
    new_parent = root / "Parent [1P 5 B]"
    assert new_parent.exists()
    new_child = new_parent / "Child [1P 5 B]"
    assert new_child.exists()
    assert (new_child / "img.jpg").exists()


# 3. Blocker 3: Rename Dependency Chain (001 -> 002, 002 -> 003)
def test_rename_dependency_chain(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "ChainTest"
    root.mkdir()
    d1 = root / "001"
    d2 = root / "002"
    d1.mkdir()
    d2.mkdir()
    (d1 / "f.txt").write_text("1")
    (d2 / "f.txt").write_text("2")

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Chain Profile",
            "root": str(root),
            "numbering_mode": "sequential",
            "numbering_start": 2,
            "numbering_padding": 3,
            "rename_template": "{index}",
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview: 001 -> 002, 002 -> 003
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    assert prev_resp.json()["summary"]["conflicts"] == 0

    plan_resp = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")
    exec_resp = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "completed"

    assert not (root / "001").exists()
    assert (root / "002").exists()
    assert (root / "003").exists()
    assert (root / "002" / "f.txt").read_text() == "1"
    assert (root / "003" / "f.txt").read_text() == "2"


# 4. Blocker 3: Cycle Conflict Detection (A -> B, B -> A)
def test_rename_cycle_conflict(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "CycleTest"
    root.mkdir()
    dA = root / "A"
    dB = root / "B"
    dA.mkdir()
    dB.mkdir()

    from app.organizers.engine import OrganizerProposal
    proposals = [
        OrganizerProposal(source=str(dA), target=str(dB), images=0, videos=0, files=0, folders=0, total_bytes=0, preserved_tags=[], has_suspicious_tag=False, changed=True, conflict=False),
        OrganizerProposal(source=str(dB), target=str(dA), images=0, videos=0, files=0, folders=0, total_bytes=0, preserved_tags=[], has_suspicious_tag=False, changed=True, conflict=False),
    ]
    plan_items, cycle_sources = plan_organizer_operations(proposals)
    assert len(cycle_sources) == 2
    assert str(dA) in cycle_sources and str(dB) in cycle_sources


# 5. Blocker 4: Cleanup Case-Insensitivity (KB, kb, MB, mb, GB, gb, TB, tb)
def test_cleanup_case_insensitivity():
    pattern = r"\s+\[(?:(?:\d+P(?:\s+\d+V)?)|(?:\d+V))?\s*\d+(?:\.\d+)?(?:KB|MB|GB|TB)\]$"
    test_cases = [
        ("001 Album [9P 1gb]", "001 Album"),
        ("002 Album [10p 2v 500mb]", "002 Album"),
        ("003 Album [1TB]", "003 Album"),
        ("004 Album [4KB]", "004 Album"),
        ("005 Album [32P 1.5GB]", "005 Album"),
    ]
    for orig, expected in test_cases:
        cleaned = safe_apply_cleanup_pattern(orig, pattern)
        assert cleaned == expected, f"Failed for {orig}: got {cleaned}"


# 6. Blocker 5: Explicit Empty Extensions Preserved
def test_empty_media_extensions(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "EmptyExtTest"
    root.mkdir()
    folder = root / "Item"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"x")
    (folder / "b.mp4").write_bytes(b"y")

    # Profile with explicit empty video_extensions
    resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Images Only Profile",
            "root": str(root),
            "image_extensions": ["jpg"],
            "video_extensions": [],
        },
    )
    assert resp.status_code == 200
    p = resp.json()
    assert p["image_extensions"] == ["jpg"]
    assert p["video_extensions"] == []

    # Preview should report 0 videos
    prev = client.post(f"/api/organizer-profiles/{p['id']}/preview")
    assert prev.status_code == 200
    prop = prev.json()["proposals"][0]
    assert prop["images"] == 1
    assert prop["videos"] == 0


# 7. Blocker 5: Invalid Extension Rejection & Normalization
def test_invalid_extension_rejection_and_normalization():
    # Normalization
    norm = validate_and_normalize_extensions([".JPG", " PNG ", ".WebP"])
    assert norm == ["jpg", "png", "webp"]

    # Invalid characters rejected
    for bad in ["jpg/bad", "mkv\\bad", "a b", "test!"]:
        with pytest.raises(ValueError) as exc:
            validate_and_normalize_extensions([bad])
        assert "非法扩展名" in str(exc.value)


# 8. Blocker 6: Cleanup Regex ReDoS Protection
def test_cleanup_regex_timeout_catastrophic():
    catastrophic_pattern = r"(a+)+$"
    errors = validate_cleanup_patterns([catastrophic_pattern])
    assert any("嵌套量词" in e or "ReDoS" in e for e in errors)

    # Calling safe_apply_cleanup_pattern on catastrophic pattern rejects safely
    with pytest.raises(ValueError) as exc:
        safe_apply_cleanup_pattern("a" * 30 + "!", catastrophic_pattern)
    assert "嵌套量词" in str(exc.value) or "超时" in str(exc.value)


# 9. Blocker 7: Standalone Engine Import (No Circular Dependency)
def test_standalone_import_engine():
    res = subprocess.run(
        [sys.executable, "-c", "import app.organizers.engine; print('SUCCESS')"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "SUCCESS" in res.stdout


# 10. Blocker 8: mtime_delay_seconds Behavior
def test_mtime_delay_seconds_behavior(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "MtimeDelayTest"
    root.mkdir()
    d1 = root / "001"
    d1.mkdir()
    (d1 / "f").write_text("x")

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Delay Test",
            "root": str(root),
            "mtime_mode": "ordered",
            "mtime_delay_seconds": 2.5,
            "rename_template": "{name} [1P 1B]",
        },
    )
    profile_id = create_resp.json()["id"]

    plan_resp = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    plan_id = plan_resp.json()["id"]

    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")

    sleep_calls = []
    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        exec_resp = client.post(f"/api/plans/{plan_id}/execute")
        assert exec_resp.status_code == 200
        assert exec_resp.json()["status"] == "completed"

    assert 2.5 in sleep_calls


# 11. Blocker 9: files_count Variable in Templates
def test_files_count_variable_support(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "FilesCountTest"
    root.mkdir()
    d = root / "Album"
    d.mkdir()
    (d / "a.txt").write_text("a")
    (d / "b.txt").write_text("b")

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Files Count Test",
            "root": str(root),
            "rename_template": "{name} [{files_count} files]",
        },
    )
    profile_id = create_resp.json()["id"]
    prev = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev.status_code == 200
    target = prev.json()["proposals"][0]["target"]
    assert target.endswith("Album [2 files]")


# 12. Blocker 10: Import Strict Schema (Reject Extra Top-level Keys)
def test_import_strict_schema_rejection(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    bad_payload = {
        "schema_version": 1,
        "profile": {"name": "Test"},
        "evil": 666,
    }
    resp = client.post("/api/organizer-profiles/import", json=bad_payload)
    assert resp.status_code in {400, 422}


# 13. Blocker 11: Preview Snapshot Caching
def test_preview_snapshot_caching(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "SnapshotTest"
    root.mkdir()
    for i in range(5):
        (root / f"dir_{i}").mkdir()

    create_resp = client.post(
        "/api/organizer-profiles",
        json={"name": "Snapshot Profile", "root": str(root)},
    )
    profile_id = create_resp.json()["id"]

    # Initial preview generates snapshot_id
    resp1 = client.post(f"/api/organizer-profiles/{profile_id}/preview", json={"page": 1, "page_size": 2})
    assert resp1.status_code == 200
    data1 = resp1.json()
    snapshot_id = data1.get("snapshot_id")
    assert snapshot_id is not None
    assert len(data1["proposals"]) == 2

    # Second page using same snapshot_id
    resp2 = client.post(
        f"/api/organizer-profiles/{profile_id}/preview",
        json={"page": 2, "page_size": 2, "snapshot_id": snapshot_id},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2.get("snapshot_id") == snapshot_id
    assert len(data2["proposals"]) == 2
    assert data2["proposals"][0]["source"] != data1["proposals"][0]["source"]


# 14. Blocker Regression 1: Recursive >= 4 Level Rename and Touch Completed
def test_recursive_four_level_rename_and_touch_completed(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "FourLevelTest"
    root.mkdir()
    d1 = root / "A [old]"
    d2 = d1 / "B [old]"
    d3 = d2 / "C [old]"
    d4 = d3 / "D [old]"
    d4.mkdir(parents=True)
    (d4 / "img.jpg").write_bytes(b"hello")

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Four Level Profile",
            "root": str(root),
            "recursive": True,
            "mtime_mode": "ordered",
            "rename_template": "{name} [{images}P {size}]",
            "cleanup_patterns": [r"\s+\[old\]$"],
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    summary = prev_resp.json()["summary"]
    assert summary["conflicts"] == 0
    assert summary["changed_directories"] == 4

    # Create plan
    plan_resp = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")
    exec_resp = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert exec_data["status"] == "completed"

    # Verify all 4 levels are renamed and exist under their final paths
    final_a = root / "A [1P 5 B]"
    final_b = final_a / "B [1P 5 B]"
    final_c = final_b / "C [1P 5 B]"
    final_d = final_c / "D [1P 5 B]"
    assert final_a.exists()
    assert final_b.exists()
    assert final_c.exists()
    assert final_d.exists()
    assert (final_d / "img.jpg").exists()


# 15. Blocker Regression 2: ReDoS Alternation API Timeout
def test_cleanup_regex_alternation_redos_api_timeout(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "RedosTest"
    root.mkdir()
    evil_dir = root / ("a" * 40 + "!")
    evil_dir.mkdir()

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "ReDoS Alternation Profile",
            "root": str(root),
            "cleanup_patterns": [r"(a|aa)+$"],
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    start = time.monotonic()
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    elapsed = time.monotonic() - start

    # Must complete within 1 second and return 400 timeout error
    assert elapsed < 1.0, f"Preview took too long ({elapsed}s), ReDoS protection failed!"
    assert prev_resp.status_code == 400
    assert "超时" in prev_resp.json()["detail"] or "ReDoS" in prev_resp.json()["detail"]


# 16. Blocker Regression 3: Conflict Detection with Existing File Having Same Basename Elsewhere
def test_conflict_existing_file_same_basename_elsewhere(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "ConflictFullpathTest"
    root.mkdir()

    # P1 has X [old] (dir) and X (file occupying target)
    p1 = root / "P1"
    p1.mkdir()
    (p1 / "X [old]").mkdir()
    (p1 / "X").write_text("file content")

    # P2 has X (directory coincidentally sharing basename X)
    p2 = root / "P2"
    p2.mkdir()
    (p2 / "X").mkdir()

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Fullpath Conflict Profile",
            "root": str(root),
            "recursive": True,
            "rename_template": "{name}",
            "cleanup_patterns": [r"\s+\[old\]$"],
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview must detect conflict on P1/X [old] -> P1/X
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    assert prev_resp.json()["summary"]["conflicts"] >= 1

    # Plan creation must be rejected with 400
    plan_resp = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    assert plan_resp.status_code == 400
    assert "冲突项" in plan_resp.json()["detail"]


# 17. Blocker Regression 4: Touch-Only Organizer Plan (0 Renames)
def test_touch_only_organizer_plan(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "TouchOnlyTest"
    root.mkdir()
    dA = root / "A"
    dB = root / "B"
    dA.mkdir()
    dB.mkdir()

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Touch Only Profile",
            "root": str(root),
            "mtime_mode": "ordered",
            "rename_template": "{name}",
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview: 0 changed directories
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    summary = prev_resp.json()["summary"]
    assert summary["changed_directories"] == 0
    assert summary["total_directories"] == 2

    # Plan creation with touch enabled should succeed!
    plan_resp = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"include_touch": True},
    )
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    # Execute plan
    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")
    exec_resp = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "completed"

    # Both directories still exist with unchanged names
    assert dA.exists()
    assert dB.exists()


# 18. Blocker Regression 5: Recursive Summary Unique Total Bytes
def test_recursive_summary_unique_total_bytes(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "UniqueBytesTest"
    root.mkdir()
    dA = root / "A"
    dB = dA / "B"
    dC = dB / "C"
    dC.mkdir(parents=True)
    (dC / "x.jpg").write_bytes(b"x" * 100)

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Unique Bytes Profile",
            "root": str(root),
            "recursive": True,
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    data_res = prev_resp.json()

    # Unique summary total bytes MUST be 100, not 300!
    assert data_res["summary"]["total_bytes"] == 100

    # Subtree stats for each proposal can still report its own subtree
    for prop in data_res["proposals"]:
        assert prop["total_bytes"] == 100


# 19. Blocker Regression 6: Recursive Stats Single Pass Performance Contract
def test_recursive_stats_single_pass_contract(tmp_path: Path):
    from unittest.mock import patch
    from app.organizers.engine import generate_organizer_proposals

    root = tmp_path / "SinglePassTest"
    root.mkdir()
    d1 = root / "D1"
    d2 = d1 / "D2"
    d3 = d2 / "D3"
    d3.mkdir(parents=True)
    (d3 / "file.txt").write_text("abc")

    with patch("app.organizers.engine.collect_directory_stats") as mock_collect:
        summary, proposals = generate_organizer_proposals(
            root,
            allowed_roots=[tmp_path],
            image_extensions=["jpg"],
            video_extensions=["mp4"],
            rename_template="{name}",
            statistics_template="[{files} files]",
            preserve_tags=[],
            cleanup_patterns=[],
            recursive=True,
        )
        # In recursive mode, collect_directory_stats MUST NOT be called in a loop for each candidate
        assert not mock_collect.called, "collect_directory_stats was called in recursive mode instead of single-pass traversal!"
        assert summary["total_directories"] == 3
        assert len(proposals) == 3


# 20. Fixed3 Test 1: Frontend Touch-Only UI Source Contract
def test_frontend_touch_only_source_contract():
    preview_path = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "Organizer" / "ProfilePreview.tsx"
    content = preview_path.read_text(encoding="utf-8")
    assert "canGeneratePlan" in content
    # Ensure handleGeneratePlan does not block when changed_directories is 0
    assert "if (summary && summary.changed_directories === 0)" not in content
    assert "profile.mtime_mode === 'ordered'" in content


# 21. Fixed3 Test 2: Target NAME_MAX Preview Conflict Detection (Never 500)
def test_target_name_max_preview_conflict(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "NameMaxTest"
    root.mkdir()
    (root / "folder1").mkdir()

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "NameMax Profile",
            "root": str(root),
            "rename_template": "x" * 300,
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview must return 200 (not 500!) and flag conflict
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["summary"]["conflicts"] >= 1
    assert "文件系统限制" in prev_data["proposals"][0]["conflict_reason"]

    # Plan creation must be rejected with 400
    plan_resp = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    assert plan_resp.status_code == 400
    assert "冲突项" in plan_resp.json()["detail"]


# 22. Fixed3 Test 3: UTF-8 Byte-length NAME_MAX Preview Conflict
def test_target_utf8_name_max_preview_conflict(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "Utf8NameMaxTest"
    root.mkdir()
    (root / "folder1").mkdir()

    # 90 Chinese characters is 270 bytes in UTF-8, exceeding 255 bytes limit
    long_chinese = "测试" * 45
    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Utf8 NameMax Profile",
            "root": str(root),
            "rename_template": long_chinese,
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["summary"]["conflicts"] >= 1
    assert "文件系统限制" in prev_data["proposals"][0]["conflict_reason"]


# 23. Fixed3 Test 4: Existing Symlink Target Conflict
def test_symlink_destination_conflict(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "SymlinkConflictTest"
    root.mkdir()
    dir_a = root / "A"
    dir_a.mkdir()
    sym_b = root / "B"
    sym_b.symlink_to(dir_a)

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Symlink Target Profile",
            "root": str(root),
            "rename_template": "B",
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    # Preview must detect conflict on A -> B because B already exists as symlink
    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["summary"]["conflicts"] >= 1
    assert "符号链接" in prev_data["proposals"][0]["conflict_reason"]

    # Plan creation must be rejected with 400
    plan_resp = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    assert plan_resp.status_code == 400
    assert "冲突项" in plan_resp.json()["detail"]


# 24. Fixed3 Test 5: Conditional Template Live Preview
def test_conditional_template_live_preview():
    import shutil
    import subprocess
    from app.organizers.templates import render_template

    tpl = "[{images}P{?videos: {videos}V} {size}]"
    assert render_template(tpl, {"images": 120, "videos": 3, "size": "8.42GB"}) == "[120P 3V 8.42GB]"
    assert render_template(tpl, {"images": 120, "videos": 0, "size": "8.42GB"}) == "[120P 8.42GB]"

    # If node is available in the environment, also test typescript renderer directly
    if shutil.which("node"):
        node_code = """
import { renderTemplate } from './frontend/src/utils/templateRenderer.ts';
const tpl = '[{images}P{?videos: {videos}V} {size}]';
const r1 = renderTemplate(tpl, { images: 120, videos: 3, size: '8.42GB' });
const r2 = renderTemplate(tpl, { images: 120, videos: 0, size: '8.42GB' });
if (r1 !== '[120P 3V 8.42GB]' || r2 !== '[120P 8.42GB]') {
    process.exit(1);
}
"""
        project_dir = Path(__file__).resolve().parent.parent
        res = subprocess.run(
            ["node", "--experimental-strip-types", "-e", node_code],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Node template execution failed: {res.stderr}"


# 25. Fixed3 Test 6: Finite Range Validation for mtime_delay_seconds
def test_mtime_delay_finite_range_validation(tmp_path: Path):
    client, data, settings = _get_client(tmp_path)
    root = data / "MtimeDelayTest"
    root.mkdir()

    # 1. Negative delay rejected
    resp_neg = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Negative Delay",
            "root": str(root),
            "mtime_delay_seconds": -1.0,
        },
    )
    assert resp_neg.status_code in {400, 422}

    # 2. Excessive delay (> 60) rejected
    resp_gt = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Excessive Delay",
            "root": str(root),
            "mtime_delay_seconds": 60.1,
        },
    )
    assert resp_gt.status_code in {400, 422}

    # 3. 1e309 (Infinity) raw JSON body rejected (never 500!)
    resp_inf = client.post(
        "/api/organizer-profiles",
        content=f'{{"name": "Inf Delay", "root": "{root}", "mtime_delay_seconds": 1e309}}'.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp_inf.status_code in {400, 422}

    # 4. NaN / Infinity string values rejected
    resp_nan = client.post(
        "/api/organizer-profiles",
        content=f'{{"name": "NaN Delay", "root": "{root}", "mtime_delay_seconds": "NaN"}}'.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp_nan.status_code in {400, 422}

    # 4. Import profile with invalid delay rejected
    resp_imp = client.post(
        "/api/organizer-profiles/import",
        json={
            "schema_version": 1,
            "profile": {
                "name": "Bad Import",
                "root": str(root),
                "mtime_delay_seconds": 999.0,
            },
        },
    )
    assert resp_imp.status_code in {400, 422}

    # 5. Boundary valid values [0.0, 60.0] accepted
    resp_ok1 = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Zero Delay",
            "root": str(root),
            "mtime_delay_seconds": 0.0,
        },
    )
    assert resp_ok1.status_code == 200

    resp_ok2 = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Max Delay",
            "root": str(root),
            "mtime_delay_seconds": 60.0,
        },
    )
    assert resp_ok2.status_code == 200


# 26. Fixed4 Test: Size Formatting Consistency (format_size & formatBytes)
def test_organizer_size_formatting_consistency(tmp_path: Path):
    from app.batch.stats import format_size

    # Unit boundary verification
    assert format_size(0) == "0 B"
    assert format_size(128) == "128 B"
    assert format_size(1023) == "1023 B"
    assert format_size(1024) == "1.00 KB"
    assert format_size(3072) == "3.00 KB"
    assert format_size(4224) == "4.13 KB"
    assert format_size(7296) == "7.13 KB"
    assert format_size(1024**2) == "1.00 MB"
    assert format_size(int(1.25 * 1024**2)) == "1.25 MB"
    assert format_size(1024**3) == "1.00 GB"
    assert format_size(int(2.5 * 1024**3)) == "2.50 GB"
    assert format_size(int(1.1 * 1024**4)) == "1.10 TB"

    # End-to-End user scenario verification
    client, data, settings = _get_client(tmp_path)
    root = data / "SizeConsistencyTest"
    root.mkdir()

    # Album 2: photo1.jpg (1024 B), video1.mp4 (2048 B) -> 3072 B (3.00 KB)
    alb2 = root / "Album 2 [old]"
    alb2.mkdir()
    (alb2 / "photo1.jpg").write_bytes(b"p" * 1024)
    (alb2 / "video1.mp4").write_bytes(b"v" * 2048)

    # Album 10: photo2.jpg (4096 B), note.txt (128 B) -> 4224 B (4.13 KB)
    alb10 = root / "Album 10 [old]"
    alb10.mkdir()
    (alb10 / "photo2.jpg").write_bytes(b"p" * 4096)
    (alb10 / "note.txt").write_bytes(b"n" * 128)

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Size Consistency Profile",
            "root": str(root),
            "numbering_mode": "sequential",
            "numbering_start": 1,
            "numbering_padding": 3,
            "cleanup_patterns": [r"\s+\[old\]$"],
            "statistics_template": "[{images}P{?videos: {videos}V} {size}]",
            "rename_template": "{index} {name} {statistics}",
        },
    )
    assert create_resp.status_code == 200
    profile_id = create_resp.json()["id"]

    prev_resp = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert prev_resp.status_code == 200
    res_data = prev_resp.json()

    # Summary unique total bytes: 3072 + 4224 = 7296 (7.13 KB)
    summary = res_data["summary"]
    assert summary["total_bytes"] == 7296
    assert summary["conflicts"] == 0
    assert summary["changed_directories"] == 2

    proposals = res_data["proposals"]
    assert len(proposals) == 2

    # Album 2
    p_alb2 = next(p for p in proposals if "Album 2" in p["source"])
    assert p_alb2["total_bytes"] == 3072
    assert p_alb2["images"] == 1
    assert p_alb2["videos"] == 1
    assert Path(p_alb2["target"]).name == "001 Album 2 [1P 1V 3.00 KB]"

    # Album 10
    p_alb10 = next(p for p in proposals if "Album 10" in p["source"])
    assert p_alb10["total_bytes"] == 4224
    assert p_alb10["images"] == 1
    assert p_alb10["videos"] == 0
    assert Path(p_alb10["target"]).name == "002 Album 10 [1P 4.13 KB]"
