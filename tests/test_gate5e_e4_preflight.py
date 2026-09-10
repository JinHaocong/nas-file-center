import os
import stat
from pathlib import Path
import pytest
from unittest.mock import patch

from app.batch_utilities.empty_dirs import (
    ScopeBinding,
    validate_remove_empty_scopes_preflight,
)
from app.batch_utilities.errors import (
    BatchUtilityScopeNotFoundError,
    BatchUtilityScopeOverlapError,
    BatchUtilitySymlinkBlockedError,
    BatchUtilityCrossRootError,
    BatchUtilityInvalidConfigError,
)


def test_preflight_accepts_valid_scope_inside_allowed_roots(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    d1 = root / "dir1"
    d1.mkdir()

    bindings = validate_remove_empty_scopes_preflight([str(d1)], [root], None)
    assert len(bindings) == 1
    b = bindings[0]
    assert b.requested_path == str(d1)
    assert b.canonical_path == str(d1.resolve())
    st = os.stat(d1)
    assert (b.device, b.inode) == (st.st_dev, st.st_ino)


def test_preflight_allows_scope_equal_to_allowed_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    # Freeze §5: Unlike E3 Flatten wrappers, an E4 scope root may equal an ALLOWED_ROOT
    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    assert len(bindings) == 1
    assert bindings[0].canonical_path == str(root.resolve())


def test_preflight_blocks_leaf_symlink_with_and_without_trailing_slash(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    real_dir = root / "real_dir"
    real_dir.mkdir()
    link = root / "link_to_dir"
    os.symlink(str(real_dir), str(link))

    with pytest.raises(BatchUtilitySymlinkBlockedError):
        validate_remove_empty_scopes_preflight([str(link)], [root], None)

    with pytest.raises(BatchUtilitySymlinkBlockedError):
        validate_remove_empty_scopes_preflight([str(link) + "/"], [root], None)


def test_preflight_physical_traversal_semantics_for_symlink_dotdot(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    a = root / "A"
    a.mkdir()
    b = a / "B"
    b.mkdir()
    target = a / "target_dir"
    target.mkdir()

    link = root / "link"
    os.symlink(str(b), str(link))

    # link/../target_dir physically traverses through A/B/.. -> A/target_dir
    input_path = str(link) + "/../target_dir"
    bindings = validate_remove_empty_scopes_preflight([input_path], [root], None)
    assert len(bindings) == 1
    assert bindings[0].canonical_path == str(target.resolve())


def test_preflight_rejects_physical_duplicate_scopes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    d = root / "data"
    d.mkdir()
    link = root / "data_link"
    os.symlink(str(d), str(link))

    with pytest.raises(BatchUtilityScopeOverlapError):
        validate_remove_empty_scopes_preflight([str(d), str(link) + "/../data"], [root], None)


def test_preflight_rejects_physical_ancestor_descendant_overlap(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    parent = root / "parent"
    parent.mkdir()
    child = parent / "child"
    child.mkdir()

    with pytest.raises(BatchUtilityScopeOverlapError):
        validate_remove_empty_scopes_preflight([str(parent), str(child)], [root], None)

    with pytest.raises(BatchUtilityScopeOverlapError):
        validate_remove_empty_scopes_preflight([str(child), str(parent)], [root], None)


def test_preflight_rejects_quarantine_scope(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    quarantine = root / ".quarantine"
    quarantine.mkdir()
    q_sub = quarantine / "sub"
    q_sub.mkdir()

    with pytest.raises(BatchUtilityCrossRootError):
        validate_remove_empty_scopes_preflight([str(quarantine)], [root], quarantine)

    with pytest.raises(BatchUtilityCrossRootError):
        validate_remove_empty_scopes_preflight([str(q_sub)], [root], quarantine)


def test_preflight_rejects_scope_outside_allowed_roots(tmp_path):
    root1 = tmp_path / "root1"
    root1.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(BatchUtilityCrossRootError):
        validate_remove_empty_scopes_preflight([str(outside)], [root1], None)


def test_preflight_rejects_missing_scope(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    missing = root / "non_existent"

    with pytest.raises(BatchUtilityScopeNotFoundError):
        validate_remove_empty_scopes_preflight([str(missing)], [root], None)


def test_preflight_identity_capture_failure_fails_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    d = root / "data"
    d.mkdir()
    d_phys_str = str(d.resolve())

    real_stat = os.stat
    def failing_stat(path, *args, **kwargs):
        if str(path) == d_phys_str:
            raise OSError("I/O error during identity capture")
        return real_stat(path, *args, **kwargs)

    with patch("os.stat", side_effect=failing_stat):
        with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
            validate_remove_empty_scopes_preflight([str(d)], [root], None)
        assert exc_info.value.details.get("stage") == "PREFLIGHT"
