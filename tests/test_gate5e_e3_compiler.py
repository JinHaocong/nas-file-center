import pytest
from pathlib import Path
from app.batch_utilities.schema import FlattenOneLevelAction
from app.batch_utilities.compiler import compile_flatten_one_level_preview, BatchUtilitySafetySnapshot
from app.batch_utilities.errors import BatchUtilityScopeOverlapError

def test_compile_flatten_overlap(tmp_path):
    root = tmp_path / "root"
    w1 = root / "w1"
    w2 = w1 / "w2"
    w2.mkdir(parents=True)
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(w1), str(w2)]
    )
    
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    
    with pytest.raises(BatchUtilityScopeOverlapError):
        compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_blocked_source_creates_no_intent(tmp_path):
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    
    (wrapper / "a.txt").write_text("a")
    (wrapper / "b.txt").write_text("b")
    # Conflict: target a.txt already exists
    (root / "a.txt").write_text("existing_a")
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(wrapper)]
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    
    compilation = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
    assert len(compilation.rows) == 2
    assert compilation.planned_operations_count == 1
    assert len(compilation.intents) == 1
    assert compilation.intents[0].source_path == str(wrapper / "b.txt")
    assert compilation.intents[0].operation == "move"
    
    rows_by_src = {r["source_path"]: r for r in compilation.rows}
    row_a = rows_by_src[str(wrapper / "a.txt")]
    row_b = rows_by_src[str(wrapper / "b.txt")]
    
    assert row_a["decision"] == "BLOCKING_CONFLICT"
    assert row_a["reason_code"] == "TARGET_EXISTS"
    assert row_b["decision"] == "MOVE"
    assert row_b["reason_code"] is None


def test_compiler_preview_row_fields_and_directory(tmp_path):
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    
    file_path = wrapper / "file.txt"
    file_path.write_text("content")
    sub_dir = wrapper / "sub_dir"
    sub_dir.mkdir()
    (sub_dir / "nested.txt").write_text("nested")
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(wrapper)]
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    
    compilation = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
    assert compilation.planned_operations_count == 2
    rows_by_src = {r["source_path"]: r for r in compilation.rows}
    
    row_file = rows_by_src[str(file_path)]
    assert row_file["decision"] == "MOVE"
    assert row_file["object_type"] == "file"
    assert row_file["wrapper_path"] == str(wrapper)
    assert row_file["index_root_id"] is None
    assert row_file["index_root_path"] is None
    
    row_dir = rows_by_src[str(sub_dir)]
    assert row_dir["decision"] == "MOVE"
    assert row_dir["object_type"] == "directory"
    assert row_dir["wrapper_path"] == str(wrapper)
    assert row_dir["index_root_id"] is None
    assert row_dir["index_root_path"] is None


def test_compiler_wrapper_symlink_blocked(tmp_path):
    import os
    from app.batch_utilities.errors import BatchUtilitySymlinkBlockedError
    root = tmp_path / "root"
    real_wrapper = root / "real_wrapper"
    real_wrapper.mkdir(parents=True)
    symlink_wrapper = root / "symlink_wrapper"
    os.symlink(str(real_wrapper), str(symlink_wrapper))
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(symlink_wrapper)]
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    
    with pytest.raises(BatchUtilitySymlinkBlockedError):
        compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_wrapper_cross_root(tmp_path):
    from app.batch_utilities.errors import BatchUtilityCrossRootError
    root = tmp_path / "root"
    root.mkdir(parents=True)
    outside = tmp_path / "outside_wrapper"
    outside.mkdir(parents=True)
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(outside)]
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    
    with pytest.raises(BatchUtilityCrossRootError):
        compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_digest_changes_on_same_size_mtime_change(tmp_path):
    import os
    import time
    from app.batch_utilities.service import compute_preview_digest_from_compilation
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    
    test_file = wrapper / "data.txt"
    test_file.write_text("ABCD")  # 4 bytes
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(wrapper)]
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    
    comp1 = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
    digest1 = compute_preview_digest_from_compilation(comp1, snapshot)
    snap_digest1 = comp1.source_snapshot_digest
    
    # Change mtime explicitly while keeping same 4-byte size
    st = test_file.stat()
    new_mtime = st.st_mtime + 100.0
    os.utime(test_file, (new_mtime, new_mtime))
    
    comp2 = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
    digest2 = compute_preview_digest_from_compilation(comp2, snapshot)
    snap_digest2 = comp2.source_snapshot_digest
    
    assert snap_digest1 != snap_digest2
    assert digest1 != digest2
