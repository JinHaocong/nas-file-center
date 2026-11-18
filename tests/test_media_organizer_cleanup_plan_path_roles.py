"""Schema-2 role evidence is explicit; legacy plan bytes remain unchanged."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.batch.media_organizer_cleanup_plan import (
    CleanupPlanConflict, build_cleanup_plan, read_cleanup_plan, save_cleanup_plan,
)
from app.batch.media_organizer_path_roles import POLICY, cleanup_plan_path_role_fields
from tests.test_media_organizer_path_roles import _manifest


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _prepared(tmp_path):
    unit = tmp_path / "unit"
    unit.mkdir()
    group = "P [4 50B]"
    manifest = _manifest(str(unit), pairs=[
        (f"{group}/001.jpg", f"{group}/001.jpg"),
        (f"{group}/a.jpg", f"{group}/b.jpg"),
        (f"{group}/b.jpg", f"{group}/a.jpg"),
        ("P1/old.png", f"{group}/002.png"),
    ])
    manifest["path_role_policy"] = POLICY
    stage = unit / manifest["stage_directory"]
    stage.mkdir(mode=0o700)
    manifest["unit_dev"], manifest["unit_ino"] = unit.stat().st_dev, unit.stat().st_ino
    for index, row in enumerate(manifest["moves"], 1):
        source = Path(row["source"])
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(bytes([96 + index]) * (10 + index))
        info = source.stat()
        row["identity"] = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
        os.link(source, row["target"])
    manifest["groups"] = [{"name": group, "kind": "P", "count": 4, "bytes": 50,
                           "destination": str(unit / group)}]
    manifest["wrapper_identities"] = {
        str(folder): [folder.stat().st_dev, folder.stat().st_ino]
        for folder in (unit / group, unit / "P1")
    }
    manifest["wrapper_cleanup"] = [str(unit / "P1")]
    return unit, manifest


def _snapshot(unit):
    return {str(path.relative_to(unit)): (path.lstat().st_ino, path.lstat().st_nlink,
                                        path.read_bytes() if path.is_file() else None)
            for path in unit.rglob("*")}


def _link(row):
    return {"path": row["source"], "identity": row["identity"],
            "published_path": row["final"]}


def test_schema2_plan_records_self_group_reuse_and_two_phase_remap_without_mutation(tmp_path):
    unit, manifest = _prepared(tmp_path)
    rows = manifest["moves"]
    before, frozen = _snapshot(unit), deepcopy(manifest)

    plan = build_cleanup_plan(manifest)

    assert plan["schema_version"] == 2
    assert plan["path_role_policy"] == POLICY
    assert plan["original_links"] == [_link(row) for row in rows[1:]]
    assert plan["retained_original_links"] == [_link(rows[0])]
    assert plan["staged_links"] == [
        {"path": row["target"], "identity": row["identity"], "published_path": row["final"]}
        for row in rows
    ]
    assert plan["wrapper_directories"] == [{
        "path": str(unit / "P1"), "identity": manifest["wrapper_identities"][str(unit / "P1")],
    }]
    group_path = manifest["groups"][0]["destination"]
    assert plan["retained_wrapper_directories"] == [{
        "path": group_path, "identity": manifest["wrapper_identities"][group_path],
    }]
    assert plan["deferred_publications"] == [
        {"path": row["final"], "stage_path": row["target"], "identity": row["identity"],
         "source_path": row["source"]} for row in rows[1:3]
    ]
    assert plan["released_original_links"] == [
        {**_link(row), "stage_path": row["target"]} for row in rows[1:3]
    ]
    assert plan["cleanup_authorized"] is plan["finalized"] is False
    assert plan["namespace_exclusive_custody_proven"] is False
    assert _snapshot(unit) == before
    assert manifest == frozen


def test_policy_free_plan_preserves_exact_v1_record_and_bytes(tmp_path):
    unit, manifest = _prepared(tmp_path)
    del manifest["path_role_policy"]
    rows = manifest["moves"]
    stage = unit / manifest["stage_directory"]
    expected = {
        "schema_version": 1, "plan_kind": "review_only", "job_id": 41,
        "unit": str(unit), "manifest_checksum": hashlib.sha256(_canonical(manifest)).hexdigest(),
        "stage": {"path": str(stage), "identity": [stage.stat().st_dev, stage.stat().st_ino]},
        "original_links": [_link(row) for row in rows],
        "staged_links": [{"path": row["target"], "identity": row["identity"],
                          "published_path": row["final"]} for row in rows],
        "wrapper_directories": [{"path": path, "identity": manifest["wrapper_identities"][path]}
                                for path in sorted(manifest["wrapper_identities"])],
        "cleanup_authorized": False, "finalized": False,
        "zero_change_rescan_verified": False, "namespace_exclusive_custody_proven": False,
    }
    expected["plan_sha256"] = hashlib.sha256(_canonical(expected)).hexdigest()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "cleanup-plan.json"

    assert save_cleanup_plan(path, manifest) == expected
    assert path.read_bytes() == _canonical(expected)
    assert read_cleanup_plan(path, manifest) == expected


def test_schema2_plan_roundtrip_rejects_resigned_role_changes_without_overwrite(tmp_path):
    unit, manifest = _prepared(tmp_path)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "cleanup-plan.json"
    plan = save_cleanup_plan(path, manifest)
    assert plan["schema_version"] == 2
    assert read_cleanup_plan(path, manifest) == plan
    plan["original_links"].insert(0, _link(manifest["moves"][0]))
    plan["plan_sha256"] = hashlib.sha256(_canonical({
        key: value for key, value in plan.items() if key != "plan_sha256"
    })).hexdigest()
    path.write_bytes(_canonical(plan))
    before = path.read_bytes(), _snapshot(unit)

    with pytest.raises(CleanupPlanConflict):
        read_cleanup_plan(path, manifest)
    with pytest.raises(CleanupPlanConflict):
        save_cleanup_plan(path, manifest)

    assert (path.read_bytes(), _snapshot(unit)) == before


@pytest.mark.parametrize("policy", [None, "future_relayout"])
def test_plan_refuses_unknown_policy_without_mutating_media(tmp_path, policy):
    unit, manifest = _prepared(tmp_path)
    manifest["path_role_policy"] = policy
    before = _snapshot(unit)

    with pytest.raises(ValueError):
        build_cleanup_plan(manifest)

    assert _snapshot(unit) == before


def test_replay_role_fields_do_not_depend_on_stage_still_existing(tmp_path):
    unit, manifest = _prepared(tmp_path)
    fields = cleanup_plan_path_role_fields(manifest)
    (unit / manifest["stage_directory"]).rename(tmp_path / "detached-stage")

    assert cleanup_plan_path_role_fields(manifest) == fields
