import os
from pathlib import Path

import pytest

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
from app.batch_utilities.errors import BatchUtilityPreviewChangedError, BatchUtilitySymlinkBlockedError
from app.batch_utilities.single_child_wrapper import discover_single_child_wrappers


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_discovers_strict_single_child_wrappers_without_mutation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B1" / "C1").mkdir(parents=True)
    (root / "B2" / "C2").mkdir(parents=True)
    before = _tree(root)

    decisions = discover_single_child_wrappers(str(root), str(root))

    assert [(d.wrapper_path, d.child_path, d.target_path, d.state) for d in decisions] == [
        (str(root / "B1"), str(root / "B1" / "C1"), str(root / "C1"), "READY"),
        (str(root / "B2"), str(root / "B2" / "C2"), str(root / "C2"), "READY"),
    ]
    assert all(d.selectable for d in decisions)
    assert before == _tree(root)


def test_hidden_file_or_second_entry_blocks_candidate(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B1" / "C1").mkdir(parents=True)
    (root / "B1" / ".hidden").write_text("x")
    (root / "B2" / "C2").mkdir(parents=True)
    (root / "B2" / "extra").mkdir()

    decisions = discover_single_child_wrappers(str(root), str(root))

    assert [d.state for d in decisions] == ["NOT_SINGLE_CHILD", "NOT_SINGLE_CHILD"]
    assert all(not d.selectable for d in decisions)


def test_wrapper_and_child_symlinks_are_never_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").mkdir()

    os.symlink(outside, root / "B_link")
    (root / "B_real").mkdir()
    os.symlink(outside / "secret", root / "B_real" / "C_link")

    decisions = discover_single_child_wrappers(str(root), str(root))
    by_name = {Path(d.wrapper_path).name: d for d in decisions}

    assert by_name["B_link"].state == "WRAPPER_SYMLINK"
    assert by_name["B_real"].state == "CHILD_SYMLINK"
    assert all(not d.selectable for d in decisions)
    assert not any("secret" in (d.child_path or "") for d in decisions)


def test_regular_file_sole_child_is_ready_while_special_child_is_blocked(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B_file").mkdir()
    (root / "B_file" / "001").write_text("payload")
    (root / "B_fifo").mkdir()
    os.mkfifo(root / "B_fifo" / "pipe")

    decisions = discover_single_child_wrappers(str(root), str(root))
    by_name = {Path(d.wrapper_path).name: d for d in decisions}

    file_candidate = by_name["B_file"]
    assert file_candidate.state == "READY"
    assert file_candidate.selectable is True
    assert file_candidate.child_object_type == "file"
    assert file_candidate.child_path == str(root / "B_file" / "001")
    assert file_candidate.target_path == str(root / "001")

    fifo_candidate = by_name["B_fifo"]
    assert fifo_candidate.state == "UNSUPPORTED_CHILD"
    assert fifo_candidate.selectable is False
    assert fifo_candidate.child_object_type == "special"


def test_regular_file_can_use_compat_move_when_native_noreplace_is_unavailable(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B_file").mkdir()
    (root / "B_file" / "001").write_text("payload")
    (root / "B_dir" / "C").mkdir(parents=True)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )

    decisions = discover_single_child_wrappers(str(root), str(root))
    by_name = {Path(d.wrapper_path).name: d for d in decisions}

    assert by_name["B_file"].state == "READY"
    assert by_name["B_file"].selectable is True
    assert by_name["B_file"].child_object_type == "file"

    assert by_name["B_dir"].state == "UNSUPPORTED_FILESYSTEM"
    assert by_name["B_dir"].selectable is False
    assert by_name["B_dir"].child_object_type == "directory"


def test_regular_file_existing_target_remains_nonselectable(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B" ).mkdir()
    (root / "B" / "001").write_text("source")
    (root / "001").write_text("existing-target")

    decisions = discover_single_child_wrappers(str(root), str(root))
    decision = next(d for d in decisions if Path(d.wrapper_path).name == "B")

    assert decision.state == "TARGET_EXISTS"
    assert decision.selectable is False
    assert decision.child_object_type == "file"
    assert decision.target_path == str(root / "001")


def test_existing_target_is_explicit_nonselectable_conflict(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B" / "C").mkdir(parents=True)
    (root / "C").mkdir()

    decisions = discover_single_child_wrappers(str(root), str(root))
    decision = next(d for d in decisions if Path(d.wrapper_path).name == "B")

    assert decision.state == "TARGET_EXISTS"
    assert decision.target_path == str(root / "C")
    assert decision.selectable is False


def test_duplicate_virtual_targets_are_fail_closed_and_ids_are_deterministic(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B1" / "Same").mkdir(parents=True)
    (root / "B2" / "Same").mkdir(parents=True)

    first = discover_single_child_wrappers(str(root), str(root))
    second = discover_single_child_wrappers(str(root), str(root))

    assert [d.state for d in first] == ["DUPLICATE_TARGET", "DUPLICATE_TARGET"]
    assert [d.candidate_id for d in first] == [d.candidate_id for d in second]
    assert len(set(d.candidate_id for d in first)) == 2
    assert all(not d.selectable for d in first)


def test_authoritative_root_aba_fails_closed_instead_of_following_replacement_symlink(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B" / "C").mkdir(parents=True)

    attacker = tmp_path / "attacker"
    (attacker / "EVIL" / "PWN").mkdir(parents=True)
    detached = tmp_path / "detached-root"

    real_scandir = os.scandir
    swapped = False

    def swap_root_before_first_scan(path):
        nonlocal swapped
        if not swapped:
            swapped = True
            root.rename(detached)
            os.symlink(attacker, root)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_root_before_first_scan)

    with pytest.raises(BatchUtilitySymlinkBlockedError):
        discover_single_child_wrappers(str(root), str(root))


def test_intermediate_subpath_component_aba_fails_closed_instead_of_following_replacement_symlink(tmp_path, monkeypatch):
    root = tmp_path / "root"
    managed = root / "managed"
    scope = managed / "scope"
    scope.mkdir(parents=True)
    (scope / "B" / "C").mkdir(parents=True)

    attacker = tmp_path / "attacker"
    (attacker / "scope" / "EVIL" / "PWN").mkdir(parents=True)
    detached = root / "detached-managed"

    real_scandir = os.scandir
    swapped = False

    def swap_parent_before_first_scan(path):
        nonlocal swapped
        if not swapped:
            swapped = True
            managed.rename(detached)
            os.symlink(attacker, managed)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_parent_before_first_scan)

    with pytest.raises(BatchUtilitySymlinkBlockedError):
        discover_single_child_wrappers(str(scope), str(root))


def test_wrapper_detach_after_open_before_scan_fails_closed(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    wrapper = root / "B"
    (wrapper / "C").mkdir(parents=True)
    detached = tmp_path / "detached-wrapper"

    real_scandir = os.scandir
    scandir_count = 0
    swapped = False

    def swap_wrapper_before_wrapper_scan(path):
        nonlocal scandir_count, swapped
        scandir_count += 1
        if scandir_count == 2:
            swapped = True
            wrapper.rename(detached)
            (wrapper / "C").mkdir(parents=True)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_wrapper_before_wrapper_scan)

    with pytest.raises(BatchUtilityPreviewChangedError, match="WRAPPER_IDENTITY_CHANGED") as exc:
        discover_single_child_wrappers(str(root), str(root))

    assert exc.value.code == "PREVIEW_CHANGED"
    assert swapped is True
    assert (detached / "C").is_dir()
    assert (wrapper / "C").is_dir()


def test_child_replacement_after_stat_before_decision_fails_closed(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    wrapper = root / "B"
    child = wrapper / "C"
    child.mkdir(parents=True)
    detached = tmp_path / "detached-child"

    real_entry_exists_at = single_child_wrapper_module._entry_exists_at
    swapped = False

    def swap_child_before_target_check(scope_fd, entry_name, target_path):
        nonlocal swapped
        if not swapped:
            swapped = True
            child.rename(detached)
            child.mkdir()
        return real_entry_exists_at(scope_fd, entry_name, target_path)

    monkeypatch.setattr(single_child_wrapper_module, "_entry_exists_at", swap_child_before_target_check)

    with pytest.raises(BatchUtilityPreviewChangedError, match="CHILD_IDENTITY_CHANGED") as exc:
        discover_single_child_wrappers(str(root), str(root))

    assert exc.value.code == "PREVIEW_CHANGED"
    assert swapped is True
    assert detached.is_dir()
    assert child.is_dir()
