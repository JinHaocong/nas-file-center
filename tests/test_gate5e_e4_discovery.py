import os
import stat
from pathlib import Path
import pytest
from unittest.mock import patch

from app.batch_utilities.empty_dirs import (
    ScopeBinding,
    DirectoryDecision,
    validate_remove_empty_scopes_preflight,
    discover_remove_empty_dirs,
)
from app.batch_utilities.errors import (
    BatchUtilitySymlinkBlockedError,
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
)


def test_discovery_empty_leaf_directory(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    d1 = root / "empty_dir"
    d1.mkdir()

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    decisions = discover_remove_empty_dirs(bindings, quarantine_root=None)

    assert len(decisions) == 1
    d = decisions[0]
    assert d.path == str(d1.resolve())
    assert d.relative_path == "empty_dir"
    assert d.depth == 1
    assert d.removable is True
    assert d.scope_root == str(root.resolve())


def test_discovery_nested_empty_chains_deepest_first(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    a = root / "A"
    a.mkdir()
    b = a / "B"
    b.mkdir()
    c = b / "C"
    c.mkdir()

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    decisions = discover_remove_empty_dirs(bindings, quarantine_root=None)

    # Removable should be deepest first: C, then B, then A
    removable = [d for d in decisions if d.removable]
    assert len(removable) == 3
    assert [d.relative_path for d in removable] == ["A/B/C", "A/B", "A"]
    assert [d.depth for d in removable] == [3, 2, 1]

    # Scope root itself must NEVER be emitted
    paths = [d.path for d in decisions]
    assert str(root.resolve()) not in paths


def test_discovery_file_blocks_ancestor_removability(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    a = root / "A"
    a.mkdir()
    b = a / "B"
    b.mkdir()
    # A has file.txt, B is empty
    (a / "file.txt").write_text("content")

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    decisions = discover_remove_empty_dirs(bindings, quarantine_root=None)

    # B is removable, but A is NOT removable because it contains file.txt
    removable = [d for d in decisions if d.removable]
    assert len(removable) == 1
    assert removable[0].relative_path == "A/B"

    # A was examined and is marked non-removable
    non_removable = [d for d in decisions if not d.removable]
    assert any(d.relative_path == "A" for d in non_removable)


def test_discovery_hidden_file_and_ds_store_block_removability(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    a = root / "A"
    a.mkdir()
    (a / ".DS_Store").write_text("not empty")

    b = root / "B"
    b.mkdir()
    (b / ".hidden").write_text("not empty")

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    decisions = discover_remove_empty_dirs(bindings, quarantine_root=None)

    removable = [d for d in decisions if d.removable]
    assert len(removable) == 0


def test_discovery_symlink_blocks_emptiness_and_is_not_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target_empty = tmp_path / "target_empty"
    target_empty.mkdir()

    a = root / "A"
    a.mkdir()
    os.symlink(str(target_empty), str(a / "link_to_empty"))

    # Broken symlink in B
    b = root / "B"
    b.mkdir()
    os.symlink(str(tmp_path / "nonexistent"), str(b / "broken_link"))

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    decisions = discover_remove_empty_dirs(bindings, quarantine_root=None)

    # Neither A nor B is empty; symlink is not followed
    removable = [d for d in decisions if d.removable]
    assert len(removable) == 0
    # target_empty was NOT traversed as a child of A
    assert not any("target_empty" in d.path for d in decisions)


def test_discovery_quarantine_boundary_never_traversed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    quarantine = root / ".quarantine"
    quarantine.mkdir()
    q_empty = quarantine / "empty_inside_q"
    q_empty.mkdir()

    a = root / "A"
    a.mkdir()

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], quarantine)
    decisions = discover_remove_empty_dirs(bindings, quarantine_root=quarantine)

    # A is removable
    removable_paths = [d.path for d in decisions if d.removable]
    assert str(a.resolve()) in removable_paths

    # Nothing inside quarantine is emitted
    assert not any(str(quarantine.resolve()) in d.path for d in decisions)


def test_discovery_deterministic_ordering_for_independent_trees(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "Z" / "sub").mkdir(parents=True)
    (root / "A" / "sub").mkdir(parents=True)
    (root / "M" / "sub").mkdir(parents=True)

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    decisions = discover_remove_empty_dirs(bindings, quarantine_root=None)
    removable = [d for d in decisions if d.removable]

    # Expected order: depth 2 first (sorted by relative_path: A/sub, M/sub, Z/sub), then depth 1 (A, M, Z)
    rel_paths = [d.relative_path for d in removable]
    assert rel_paths == ["A/sub", "M/sub", "Z/sub", "A", "M", "Z"]


def test_discovery_limit_exceeded_fails_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for i in range(10):
        (root / f"dir_{i}").mkdir()

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)
    with pytest.raises(BatchUtilityLimitExceededError):
        discover_remove_empty_dirs(bindings, quarantine_root=None, limit=5)


def test_discovery_child_replacement_symlink_race_fails_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    sub = root / "sub"
    sub.mkdir()
    real_secret = tmp_path / "real_secret"
    real_secret.mkdir()
    (real_secret / "secret.txt").write_text("secret")

    bindings = validate_remove_empty_scopes_preflight([str(root)], [root], None)

    # Hook entry.stat / os.open: immediately after stat sees real directory, swap sub with symlink
    orig_open = os.open
    def racing_open(path, flags, *args, **kwargs):
        if path == "sub" and "dir_fd" in kwargs:
            os.rmdir(sub)
            os.symlink(str(real_secret), str(sub))
        return orig_open(path, flags, *args, **kwargs)

    with patch("os.open", side_effect=racing_open):
        with pytest.raises((BatchUtilitySymlinkBlockedError, BatchUtilityInvalidConfigError)):
            discover_remove_empty_dirs(bindings, quarantine_root=None)
