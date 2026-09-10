import json
import os
import pytest
from pathlib import Path
from app.batch_utilities.schema import RemoveEmptyDirsAction
from app.batch_utilities.compiler import (
    compile_remove_empty_dirs_preview,
    compile_batch_utility_preview,
    BatchUtilitySafetySnapshot,
)
from app.batch_utilities.service import build_batch_utility_preview_response
from app.batch_utilities.errors import (
    BatchUtilityScopeOverlapError,
    BatchUtilityInvalidConfigError,
    BatchUtilitySymlinkBlockedError,
)


def test_compile_nested_empty_directories(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    (scope / "a" / "b" / "c").mkdir(parents=True)

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    compilation = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)

    # Decisions must be deepest-first: c, then b, then a
    assert len(compilation.rows) == 3
    assert [r["relative_path"] for r in compilation.rows] == ["a/b/c", "a/b", "a"]
    assert all(r["decision"] == "REMOVE_EMPTY_DIR" for r in compilation.rows)
    assert all(r["object_type"] == "directory" for r in compilation.rows)
    assert all(r["target_path"] is None for r in compilation.rows)

    # Scope itself must never be included
    assert str(scope) not in [r["source_path"] for r in compilation.rows]

    # Intents
    assert len(compilation.intents) == 3
    assert [i.operation for i in compilation.intents] == ["rmdir_empty", "rmdir_empty", "rmdir_empty"]
    assert [i.sequence for i in compilation.intents] == [1, 2, 3]
    assert compilation.intents[0].source_path == str(scope / "a" / "b" / "c")
    assert compilation.intents[1].source_path == str(scope / "a" / "b")
    assert compilation.intents[2].source_path == str(scope / "a")


def test_compile_file_blocks_ancestor_virtual_emptiness(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    (scope / "a" / "b").mkdir(parents=True)
    # file directly inside a
    (scope / "a" / "keep.txt").write_text("data")

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    compilation = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)

    # b is removable, a is blocked by keep.txt
    assert len(compilation.rows) == 1
    assert compilation.rows[0]["relative_path"] == "a/b"
    assert compilation.rows[0]["decision"] == "REMOVE_EMPTY_DIR"

    assert len(compilation.intents) == 1
    assert compilation.intents[0].source_path == str(scope / "a" / "b")

    # Summary checks
    assert compilation.matched_count == 2  # a and b examined
    assert compilation.candidate_count == 1  # only b is virtually removable
    assert compilation.planned_operations_count == 1
    assert compilation.skipped_count == 1  # a is non-empty
    assert compilation.safety_excluded_count == 0
    assert compilation.blocking_conflict_count == 0


def test_compile_exact_zeros_summary(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    (scope / "sub1").mkdir(parents=True)
    (scope / "sub2").mkdir(parents=True)

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    compilation = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)

    assert compilation.matched_bytes == 0
    assert compilation.candidate_bytes == 0
    assert compilation.expected_reclaim_bytes == 0
    assert compilation.summary["matched_bytes"] == 0
    assert compilation.summary["candidate_bytes"] == 0
    assert compilation.summary["expected_reclaim_bytes"] == 0


def test_compile_draft_intents_zero_identity(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    sub = scope / "sub"
    sub.mkdir(parents=True)

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    compilation = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)

    assert len(compilation.intents) == 1
    intent = compilation.intents[0]

    # Draft identity fields MUST be zero/null
    assert intent.expected_device == 0
    assert intent.expected_inode == 0
    assert intent.expected_mtime_ns == 0
    assert intent.expected_size == 0
    assert intent.expected_hash is None
    assert intent.target_path is None
    assert intent.keep_path is None

    # Metadata must carry preview observation
    meta = json.loads(intent.metadata_json)
    sub_st = sub.stat()
    assert meta["preview_observed_device"] == sub_st.st_dev
    assert meta["preview_observed_inode"] == sub_st.st_ino
    assert meta["scope_root"] == str(scope.resolve())
    assert meta["relative_path"] == "sub"
    assert meta["depth"] == 1


def test_compile_deterministic_ordering_two_trees(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    (scope / "dir_b" / "sub_deep").mkdir(parents=True)
    (scope / "dir_a" / "sub_deep").mkdir(parents=True)
    (scope / "dir_c").mkdir(parents=True)

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    c1 = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)
    c2 = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)

    # Determinism
    assert c1.source_snapshot_digest == c2.source_snapshot_digest
    assert [r["relative_path"] for r in c1.rows] == [r["relative_path"] for r in c2.rows]

    # Order: depth 2 first (alphabetical: dir_a/sub_deep, then dir_b/sub_deep), then depth 1 (dir_a, dir_b, dir_c)
    expected_order = [
        "dir_a/sub_deep",
        "dir_b/sub_deep",
        "dir_a",
        "dir_b",
        "dir_c",
    ]
    assert [r["relative_path"] for r in c1.rows] == expected_order


def test_compile_source_snapshot_digest_changes_on_fs_change(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    (scope / "dir_a").mkdir(parents=True)

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    c1 = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)

    # Now add a new empty dir
    (scope / "dir_b").mkdir(parents=True)
    c2 = compile_remove_empty_dirs_preview(session=None, action=action, safety_snapshot=snapshot)

    assert c1.source_snapshot_digest != c2.source_snapshot_digest


def test_compile_batch_utility_preview_dispatch(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    (scope / "empty_child").mkdir(parents=True)

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    compilation = compile_batch_utility_preview(session=None, action=action, safety_snapshot=snapshot)
    assert compilation.canonical_action["type"] == "remove_empty_dirs"
    assert len(compilation.rows) == 1
    assert compilation.rows[0]["relative_path"] == "empty_child"


def test_build_preview_response_live_directory_readonly(tmp_path):
    root = tmp_path / "root"
    scope = root / "scope"
    (scope / "empty_child").mkdir(parents=True)

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(scope)],
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    compilation = compile_batch_utility_preview(session=None, action=action, safety_snapshot=snapshot)
    resp = build_batch_utility_preview_response(compilation, snapshot, page=1, page_size=50)

    assert resp["utility_action"] == "remove_empty_dirs"
    assert resp["preview_source"] == "live-directory-readonly"
    assert resp["live_filesystem_verified"] is False
    assert resp["candidate_count"] == 1
    assert len(resp["items"]) == 1
    assert resp["items"][0]["decision"] == "REMOVE_EMPTY_DIR"
