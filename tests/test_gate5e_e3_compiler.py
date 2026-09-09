import pytest
from pathlib import Path
from app.batch_utilities.schema import FlattenOneLevelAction
from app.batch_utilities.compiler import compile_flatten_one_level_preview, BatchUtilitySafetySnapshot
from app.batch_utilities.errors import BatchUtilityScopeOverlapError, BatchUtilityInvalidConfigError, BatchUtilitySymlinkBlockedError

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


def test_compiler_source_missing_after_discovery(tmp_path):
    """Test A: wrapper/W/gone.txt exists -> real discovery -> unlink gone.txt -> graph/compiler.
    Expected: planned_operations_count = 0, no intent, BLOCKING_CONFLICT, reason = SOURCE_MISSING.
    """
    from unittest.mock import patch
    from app.batch_utilities.flatten import discover_flatten_one_level
    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    gone_file = wrapper / "gone.txt"
    gone_file.write_text("temporary")

    # Real discovery
    cands, errs = discover_flatten_one_level(wrapper_paths=[str(wrapper)])
    assert len(cands) == 1

    # Unlink after discovery
    gone_file.unlink()

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

    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=(cands, errs)):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "SOURCE_MISSING"
        assert comp.rows[0]["reason"] == "SOURCE_MISSING"


def test_compiler_source_type_race_file_to_directory(tmp_path):
    """Test B: wrapper/W/x exists as regular file -> real discovery -> replace x with directory -> graph/compiler.
    Expected: 0 intent, blocking conflict.
    """
    from unittest.mock import patch
    from app.batch_utilities.flatten import discover_flatten_one_level
    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    x_file = wrapper / "x"
    x_file.write_text("regular file")

    # Real discovery
    cands, errs = discover_flatten_one_level(wrapper_paths=[str(wrapper)])
    assert len(cands) == 1
    assert cands[0].object_type == "file"

    # Replace x with directory
    x_file.unlink()
    x_file.mkdir()

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

    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=(cands, errs)):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "SOURCE_TYPE_CHANGED"


def test_compiler_source_type_race_directory_to_file(tmp_path):
    """Test C: directory candidate -> replace with regular file after discovery.
    Expected: 0 intent, blocking conflict.
    """
    from unittest.mock import patch
    from app.batch_utilities.flatten import discover_flatten_one_level
    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    sub_dir = wrapper / "subdir"
    sub_dir.mkdir()

    # Real discovery
    cands, errs = discover_flatten_one_level(wrapper_paths=[str(wrapper)])
    assert len(cands) == 1
    assert cands[0].object_type == "directory"

    # Replace with regular file
    sub_dir.rmdir()
    sub_dir.write_text("now regular file")

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

    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=(cands, errs)):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "SOURCE_TYPE_CHANGED"


def test_compiler_same_type_source_replacement_blocked(tmp_path):
    """Section 7 Regression:
    1. create W/same.bin as regular file
    2. perform real discovery
    3. preserve discovery candidate
    4. replace same.bin with a different regular file
    5. keep same basename and same size
    6. ensure mtime_ns and/or physical identity differs
    7. run graph/compiler
    Expected: 0 ordered items, 0 Draft intents, BLOCKING_CONFLICT, SOURCE_IDENTITY_CHANGED
    """
    import os
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    same_bin = wrapper / "same.bin"
    same_bin.write_bytes(b"AAAA")  # size = 4

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

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # File is replaced after discovery and wrapper observation, but before graph
        st_before = os.lstat(same_bin)
        same_bin.unlink()
        same_bin.write_bytes(b"BBBB")  # size remains 4
        new_mtime = st_before.st_mtime_ns + 5_000_000
        os.utime(same_bin, ns=(new_mtime, new_mtime))
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "SOURCE_IDENTITY_CHANGED"
        assert "SOURCE_IDENTITY_CHANGED" in comp.rows[0]["reason"]


def test_compiler_wrapper_symlink_swap_blocked(tmp_path):
    """Section 8 Regression:
    Preview: W is normal directory.
    During Generate / graph:
    after discovery / wrapper identity observation and before graph,
    replace W with symlink to another directory inside the SAME allowed root.
    Expected: 0 safe ordered items, 0 Draft, BLOCKING_CONFLICT, WRAPPER_IDENTITY_CHANGED
    """
    import os
    import shutil
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    (wrapper / "a.txt").write_text("file in W")

    other = root / "Other"
    other.mkdir(parents=True)
    (other / "a.txt").write_text("file in Other")

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

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # Swap after discovery and wrapper observation, immediately before graph
        shutil.rmtree(wrapper)
        os.symlink(str(other), str(wrapper))
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "WRAPPER_IDENTITY_CHANGED"


def test_compiler_wrapper_replaced_by_different_directory_blocked(tmp_path):
    """Test wrapper replaced by a different real directory identity, not only symlink."""
    import os
    import shutil
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    (wrapper / "a.txt").write_text("file in original W")

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

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # Re-create W as a different directory identity (new inode)
        w2 = root / "W_new"
        w2.mkdir(parents=True)
        (w2 / "a.txt").write_text("file in new W")
        shutil.rmtree(wrapper)
        os.rename(str(w2), str(wrapper))
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "WRAPPER_IDENTITY_CHANGED"


def test_compiler_directory_source_replacement_blocked(tmp_path):
    """Test directory candidate physical identity mismatch."""
    import shutil
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    sub = wrapper / "sub"
    sub.mkdir()

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

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # Replace sub with a new directory (new inode)
        shutil.rmtree(sub)
        sub.mkdir()
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "SOURCE_IDENTITY_CHANGED"


def test_compiler_nonempty_wrapper_child_appearance_blocked(tmp_path):
    """E3-hotfix5 Regression 1:
    Nonempty wrapper child-appearance race.
    1. wrapper contains W/a.txt
    2. discovery and wrapper observation observe only W/a.txt
    3. before graph authority completes: create W/new.txt
    Expected: 0 planned operations, 0 intents, BLOCKING_CONFLICT, WRAPPER_IDENTITY_CHANGED
    """
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    (wrapper / "a.txt").write_text("file in W")

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

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # Create new child after discovery and wrapper observation, but before graph resolution
        (wrapper / "new.txt").write_text("new child")
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "WRAPPER_IDENTITY_CHANGED"
        assert "WRAPPER_IDENTITY_CHANGED" in comp.rows[0]["reason"]


def test_compiler_empty_wrapper_child_appearance_blocked(tmp_path):
    """E3-hotfix5 Regression 2:
    Empty wrapper child-appearance race.
    1. wrapper W is initially empty (0 candidates)
    2. discovery and wrapper observation observe empty W
    3. before graph authority completes: create W/new.txt
    Expected: 0 planned operations, 0 intents, BLOCKING_CONFLICT on W, WRAPPER_IDENTITY_CHANGED
    """
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    root = tmp_path / "root"
    wrapper = root / "W_empty"
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

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # Create new child in empty wrapper after discovery and wrapper observation, before graph
        (wrapper / "new.txt").write_text("new child in empty W")
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert comp.planned_operations_count == 0
        assert len(comp.intents) == 0
        assert len(comp.rows) == 1
        assert comp.rows[0]["source_path"] == str(wrapper)
        assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
        assert comp.rows[0]["reason_code"] == "WRAPPER_IDENTITY_CHANGED"
        assert "WRAPPER_IDENTITY_CHANGED" in comp.rows[0]["reason"]
        assert comp.blocking_conflict_count == 1


def test_canonical_wrapper_trailing_slash_digest_equality(tmp_path):
    """E3-hotfix6 Regression:
    W and W/ represent the same actual wrapper:
    -> same canonical wrapper representation
    -> same action_config_digest
    Also test redundant lexical form: /root/X/../W where X is a real non-symlink directory
    """
    from app.batch_utilities.digest import (
        canonicalize_flatten_one_level_action,
        compute_action_config_digest,
    )
    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)
    x_dir = root / "X"
    x_dir.mkdir(parents=True)

    w_plain = str(wrapper)
    w_slash = str(wrapper) + "/"
    w_redundant = str(root / "X" / ".." / "W")

    a1 = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[w_plain])
    a2 = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[w_slash])
    a3 = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[w_redundant])

    c1 = canonicalize_flatten_one_level_action(a1)
    c2 = canonicalize_flatten_one_level_action(a2)
    c3 = canonicalize_flatten_one_level_action(a3)

    assert c1["wrapper_paths"] == c2["wrapper_paths"] == c3["wrapper_paths"]
    assert len(c1["wrapper_paths"]) == 1
    assert not c1["wrapper_paths"][0].endswith("/")

    d1 = compute_action_config_digest(c1)
    d2 = compute_action_config_digest(c2)
    d3 = compute_action_config_digest(c3)

    assert d1 == d2 == d3


def test_canonical_wrapper_input_ordering_invariance(tmp_path):
    """E3-hotfix6 Regression:
    Wrapper input ordering is invariant for action_config_digest.
    """
    from app.batch_utilities.digest import (
        canonicalize_flatten_one_level_action,
        compute_action_config_digest,
    )
    root = tmp_path / "root"
    w1 = root / "W1"
    w2 = root / "W2"
    w1.mkdir(parents=True)
    w2.mkdir(parents=True)

    a1 = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(w1), str(w2)])
    a2 = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(w2), str(w1)])

    c1 = canonicalize_flatten_one_level_action(a1)
    c2 = canonicalize_flatten_one_level_action(a2)

    assert c1["wrapper_paths"] == c2["wrapper_paths"]
    assert compute_action_config_digest(c1) == compute_action_config_digest(c2)


def test_canonical_wrapper_duplicate_rejection(tmp_path):
    """E3-hotfix6 Regression:
    Duplicate wrapper representations (e.g. W and W/) are rejected.
    Pydantic schema validation rejects normalized duplicates with ValidationError.
    Canonicalize / compiler also rejects duplicate canonical paths with BatchUtilityScopeOverlapError.
    """
    from app.batch_utilities.digest import canonicalize_flatten_one_level_action
    from pydantic import ValidationError
    root = tmp_path / "root"
    wrapper = root / "W"
    wrapper.mkdir(parents=True)

    # In schema validation
    with pytest.raises(ValidationError):
        FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(wrapper), str(wrapper) + "/"])

    # In canonicalize_flatten_one_level_action with model_construct
    a_dup = FlattenOneLevelAction.model_construct(
        type="flatten_one_level",
        wrapper_paths=[str(wrapper), str(wrapper) + "/"],
    )
    with pytest.raises(BatchUtilityScopeOverlapError):
        canonicalize_flatten_one_level_action(a_dup)

    # In compiler preview
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    with pytest.raises(BatchUtilityScopeOverlapError):
        compile_flatten_one_level_preview(session=None, action=a_dup, safety_snapshot=snapshot)


def test_canonical_wrapper_symlink_dotdot_selection(tmp_path):
    """E3-hotfix7 Regression A:
    Symlink-sensitive dotdot traversal:
    root/
    ├── A/
    │   ├── B/
    │   └── W/
    │       └── intended.txt
    ├── W/
    │   └── wrong.txt
    └── link -> root/A/B

    Input: root/link/../W
    Expected:
    canonical wrapper == root/A/W
    Preview contains root/A/W/intended.txt
    Preview does NOT contain root/W/wrong.txt
    Generate Draft source: root/A/W/intended.txt
    """
    from app.batch_utilities.digest import canonicalize_wrapper_path, canonicalize_flatten_one_level_action
    import os

    root = tmp_path / "root"
    a_dir = root / "A"
    b_dir = a_dir / "B"
    b_dir.mkdir(parents=True)
    w_intended = a_dir / "W"
    w_intended.mkdir(parents=True)
    (w_intended / "intended.txt").write_text("intended")

    w_wrong = root / "W"
    w_wrong.mkdir(parents=True)
    (w_wrong / "wrong.txt").write_text("wrong")

    link = root / "link"
    os.symlink(str(b_dir), str(link))

    wrapper_input = str(link) + "/../W"

    # Canonical helper asserts
    canon_single = canonicalize_wrapper_path(wrapper_input)
    assert canon_single == str(w_intended.resolve(strict=True))

    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[wrapper_input])
    canon_action = canonicalize_flatten_one_level_action(action)
    assert canon_action["wrapper_paths"] == [str(w_intended.resolve(strict=True))]

    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
    assert comp.planned_operations_count == 1
    assert len(comp.rows) == 1
    assert comp.rows[0]["decision"] == "MOVE"
    assert comp.rows[0]["source_path"] == str(w_intended.resolve(strict=True) / "intended.txt")
    assert comp.rows[0]["wrapper_path"] == str(w_intended.resolve(strict=True))
    assert comp.rows[0]["target_path"] == str(a_dir.resolve(strict=True) / "intended.txt")

    assert len(comp.intents) == 1
    assert comp.intents[0].operation == "move"
    assert comp.intents[0].source_path == str(w_intended.resolve(strict=True) / "intended.txt")
    assert comp.intents[0].target_path == str(a_dir.resolve(strict=True) / "intended.txt")


def test_canonical_wrapper_trailing_space_directory(tmp_path):
    """E3-hotfix7 Regression B:
    Valid trailing-space directory:
    root/W/wrong.txt
    root/"W "/intended.txt
    Input: root/"W "
    Assert canonical wrapper remains the physical "W " directory.
    Preview/Generate must never switch to root/W.
    """
    from app.batch_utilities.digest import canonicalize_wrapper_path, canonicalize_flatten_one_level_action

    root = tmp_path / "root"
    w_wrong = root / "W"
    w_wrong.mkdir(parents=True)
    (w_wrong / "wrong.txt").write_text("wrong")

    w_space = root / "W "
    w_space.mkdir(parents=True)
    (w_space / "intended.txt").write_text("intended")

    wrapper_input = str(w_space)
    assert wrapper_input.endswith("W ")

    # Canonical helper asserts
    canon_single = canonicalize_wrapper_path(wrapper_input)
    assert canon_single == str(w_space.resolve(strict=True))
    assert canon_single.endswith("W ")

    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[wrapper_input])
    canon_action = canonicalize_flatten_one_level_action(action)
    assert canon_action["wrapper_paths"] == [str(w_space.resolve(strict=True))]
    assert canon_action["wrapper_paths"][0].endswith("W ")

    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    comp = compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
    assert comp.planned_operations_count == 1
    assert len(comp.rows) == 1
    assert comp.rows[0]["decision"] == "MOVE"
    assert comp.rows[0]["source_path"] == str(w_space.resolve(strict=True) / "intended.txt")
    assert comp.rows[0]["wrapper_path"] == str(w_space.resolve(strict=True))

    assert len(comp.intents) == 1
    assert comp.intents[0].source_path == str(w_space.resolve(strict=True) / "intended.txt")


def test_canonical_wrapper_strict_resolution_failure_fails_closed(tmp_path):
    """E3-hotfix7 Regression:
    If canonical strict resolution fails, fail closed with structured error.
    Must NOT silently fall back to lexical normpath.
    """
    from app.batch_utilities.digest import canonicalize_wrapper_path
    from app.batch_utilities.errors import BatchUtilityScopeNotFoundError

    root = tmp_path / "root"
    root.mkdir(parents=True)
    non_existent = str(root / "does_not_exist")

    with pytest.raises(BatchUtilityScopeNotFoundError):
        canonicalize_wrapper_path(non_existent)


def test_preflight_trailing_slash_symlink_blocked(tmp_path):
    """E3-hotfix6 Regression:
    Wrapper path with trailing slash on symlink is blocked with BatchUtilitySymlinkBlockedError.
    """
    from app.batch_utilities.errors import BatchUtilitySymlinkBlockedError
    import os
    root = tmp_path / "root"
    root.mkdir(parents=True)
    other = root / "other"
    other.mkdir(parents=True)
    sym = root / "sym_w"
    os.symlink(str(other), str(sym))

    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(sym) + "/"])
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    with pytest.raises(BatchUtilitySymlinkBlockedError):
        compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)


def test_compiler_snapshot_scandir_failure_empty_wrapper(tmp_path):
    """E3-hotfix6 Regression:
    Instrument scandir:
    scan #1 (discovery): succeeds
    scan #2 (snapshot direct_children): raises PermissionError(errno=13)
    Expected: BatchUtilityInvalidConfigError, HTTP 422, stage SNAPSHOT, errno 13
    """
    import os
    from unittest.mock import patch
    root = tmp_path / "root"
    wrapper = root / "W_empty"
    wrapper.mkdir(parents=True)

    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(wrapper)])
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 2:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert exc_info.value.code == "BATCH_UTILITY_INVALID_CONFIG"
        assert exc_info.value.status_code == 422
        assert exc_info.value.details.get("wrapper_path") == str(wrapper)
        assert exc_info.value.details.get("errno") == 13
        assert exc_info.value.details.get("stage") == "SNAPSHOT"


def test_compiler_snapshot_scandir_failure_nonempty_wrapper(tmp_path):
    """E3-hotfix6 Regression:
    Instrument scandir on nonempty wrapper:
    scan #1 (discovery): succeeds
    scan #2 (snapshot direct_children): raises PermissionError(errno=13)
    Expected: BatchUtilityInvalidConfigError, HTTP 422, stage SNAPSHOT, errno 13
    """
    import os
    from unittest.mock import patch
    root = tmp_path / "root"
    wrapper = root / "W_nonempty"
    wrapper.mkdir(parents=True)
    (wrapper / "a.txt").write_text("content")

    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(wrapper)])
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 2:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert exc_info.value.code == "BATCH_UTILITY_INVALID_CONFIG"
        assert exc_info.value.status_code == 422
        assert exc_info.value.details.get("wrapper_path") == str(wrapper)
        assert exc_info.value.details.get("errno") == 13
        assert exc_info.value.details.get("stage") == "SNAPSHOT"


def test_compiler_continuity_scandir_failure_empty_wrapper(tmp_path):
    """E3-hotfix6 Regression:
    Instrument scandir on empty wrapper:
    scan #1 (discovery): succeeds
    scan #2 (snapshot): succeeds
    scan #3 (continuity re-scan): raises PermissionError(errno=13)
    Expected: BatchUtilityInvalidConfigError, HTTP 422, stage CONTINUITY, errno 13
    """
    import os
    from unittest.mock import patch
    root = tmp_path / "root"
    wrapper = root / "W_empty_cont"
    wrapper.mkdir(parents=True)

    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(wrapper)])
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 3:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert exc_info.value.code == "BATCH_UTILITY_INVALID_CONFIG"
        assert exc_info.value.status_code == 422
        assert exc_info.value.details.get("wrapper_path") == str(wrapper)
        assert exc_info.value.details.get("errno") == 13
        assert exc_info.value.details.get("stage") == "CONTINUITY"


def test_compiler_continuity_scandir_failure_nonempty_wrapper(tmp_path):
    """E3-hotfix6 Regression:
    Instrument scandir on nonempty wrapper:
    scan #1 (discovery): succeeds
    scan #2 (snapshot): succeeds
    scan #3 (continuity re-scan): raises PermissionError(errno=13)
    Expected: BatchUtilityInvalidConfigError, HTTP 422, stage CONTINUITY, errno 13
    """
    import os
    from unittest.mock import patch
    root = tmp_path / "root"
    wrapper = root / "W_nonempty_cont"
    wrapper.mkdir(parents=True)
    (wrapper / "a.txt").write_text("content")

    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[str(wrapper)])
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 3:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
            compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
        assert exc_info.value.code == "BATCH_UTILITY_INVALID_CONFIG"
        assert exc_info.value.status_code == 422
        assert exc_info.value.details.get("wrapper_path") == str(wrapper)
        assert exc_info.value.details.get("errno") == 13
        assert exc_info.value.details.get("stage") == "CONTINUITY"




