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


def test_compiler_candidate_limit_includes_all_error_rows(tmp_path):
    from unittest.mock import patch
    from app.batch_utilities.flatten import FlattenError
    from app.batch_utilities.errors import BatchUtilityLimitExceededError
    
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    
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
    
    # 50,001 error rows
    fake_errors = [
        FlattenError(
            source_path=f"{wrapper}/link_{i}.txt",
            conflict_type="WRAPPER_CHILD_SYMLINK",
            reason="Wrapper child is a symlink",
            wrapper_path=str(wrapper),
            object_type="symlink",
        )
        for i in range(50001)
    ]
    
    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=([], fake_errors)):
        with pytest.raises(BatchUtilityLimitExceededError, match="maximum 50,000 candidates"):
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_wrapper_scandir_oserror_fails_closed(tmp_path):
    import os
    from unittest.mock import patch
    from app.batch_utilities.errors import BatchUtilityInvalidConfigError
    
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    
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
    
    orig_scandir = os.scandir
    def mock_scandir(path):
        if str(path) == str(wrapper):
            err = PermissionError(13, "Permission denied")
            err.errno = 13
            raise err
        return orig_scandir(path)
        
    with patch("os.scandir", side_effect=mock_scandir):
        with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert exc_info.value.details.get("wrapper_path") == str(wrapper)
        assert exc_info.value.details.get("errno") == 13


def test_compiler_quarantine_wrapper_maps_cross_root(tmp_path):
    from app.batch_utilities.errors import BatchUtilityCrossRootError
    root = tmp_path / "root"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    w_quarantine = quarantine / "w_inside_quarantine"
    w_quarantine.mkdir()
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(w_quarantine)]
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=quarantine,
        effective_policy={},
    )
    with pytest.raises(BatchUtilityCrossRootError):
        compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_allowed_root_wrapper_maps_invalid_config(tmp_path):
    from app.batch_utilities.errors import BatchUtilityInvalidConfigError
    root = tmp_path / "root"
    root.mkdir()
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(root)]
    )
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    with pytest.raises(BatchUtilityInvalidConfigError):
        compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_overlap_resolution_oserror_fails_closed(tmp_path):
    from unittest.mock import patch
    from app.batch_utilities.errors import BatchUtilityInvalidConfigError
    root = tmp_path / "root"
    w1 = root / "w1"
    w1.mkdir(parents=True)
    w2 = root / "w2"
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
    
    orig_resolve = Path.resolve
    def mock_resolve(self, strict=False):
        if str(self) == str(w2):
            raise OSError(5, "Input/output error")
        return orig_resolve(self, strict=strict)
        
    with patch.object(Path, "resolve", mock_resolve):
        with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert exc_info.value.details.get("wrapper_path") == str(w2)


def test_compiler_overlap_physical_dev_ino_duplicate(tmp_path):
    import os
    from unittest.mock import patch
    from app.batch_utilities.errors import BatchUtilityScopeOverlapError
    root = tmp_path / "root"
    w1 = root / "w1"
    w1.mkdir(parents=True)
    w2 = root / "w2"
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
    
    orig_stat = os.stat
    def mock_stat(path, *args, **kwargs):
        st = orig_stat(path, *args, **kwargs)
        if str(path) == str(w2):
            # Simulate same dev & ino as w1
            st1 = orig_stat(str(w1))
            class MockStat:
                st_mode = st.st_mode
                st_size = st.st_size
                st_mtime_ns = st.st_mtime_ns
                st_dev = st1.st_dev
                st_ino = st1.st_ino
            return MockStat()
        return st
        
    with patch("os.stat", side_effect=mock_stat):
        with pytest.raises(BatchUtilityScopeOverlapError):
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_candidate_source_outside_allowed_roots_blocks(tmp_path):
    from unittest.mock import patch
    from app.batch_utilities.flatten import FlattenCandidate
    
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret")
    
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
    
    # Injected candidate whose source is outside allowed roots
    cand = FlattenCandidate(
        wrapper_path=str(wrapper),
        source_path=str(outside_file),
        target_path=str(root / "secret.txt"),
        object_type="file",
        size=6,
        mtime_ns=0,
        device=0,
        inode=0,
        is_dir=False,
    )
    
    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=([cand], [])):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] in ("TARGET_OUTSIDE_ALLOWED_ROOT", "SOURCE_OUTSIDE_ALLOWED_ROOT")


def test_compiler_candidate_source_escaped_symlink_race(tmp_path):
    import os
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret")
    
    # Symlink child escaping to outside
    escaped_link = wrapper / "escaped.txt"
    os.symlink(str(outside_file), str(escaped_link))
    
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
    
    comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
    assert comp.planned_operations_count == 0
    assert len(comp.intents) == 0
    assert len(comp.rows) == 1
    assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
    assert comp.rows[0]["reason_code"] in ("WRAPPER_CHILD_SYMLINK", "TARGET_OUTSIDE_ALLOWED_ROOT")
