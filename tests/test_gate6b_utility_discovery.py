import os
from pathlib import Path

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


def test_regular_or_special_sole_child_is_not_directory_candidate(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "B_file").mkdir()
    (root / "B_file" / "file.jpg").write_text("x")
    (root / "B_fifo").mkdir()
    os.mkfifo(root / "B_fifo" / "pipe")

    decisions = discover_single_child_wrappers(str(root), str(root))
    by_name = {Path(d.wrapper_path).name: d for d in decisions}

    assert by_name["B_file"].state == "CHILD_NOT_DIRECTORY"
    assert by_name["B_fifo"].state == "UNSUPPORTED_CHILD"
    assert all(not d.selectable for d in decisions)


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


def test_authoritative_root_aba_cannot_redirect_discovery_outside_root(tmp_path, monkeypatch):
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

    decisions = discover_single_child_wrappers(str(root), str(root))

    assert [Path(d.wrapper_path).name for d in decisions] == ["B"]
    assert all("EVIL" not in d.wrapper_path and "PWN" not in (d.child_path or "") for d in decisions)


def test_subpath_component_aba_cannot_redirect_discovery_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    scope = root / "managed" / "scope"
    scope.mkdir(parents=True)
    (scope / "B" / "C").mkdir(parents=True)

    attacker = tmp_path / "attacker"
    (attacker / "EVIL" / "PWN").mkdir(parents=True)
    detached = root / "managed" / "detached-scope"

    real_scandir = os.scandir
    swapped = False

    def swap_scope_before_first_scan(path):
        nonlocal swapped
        if not swapped:
            swapped = True
            scope.rename(detached)
            os.symlink(attacker, scope)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_scope_before_first_scan)

    decisions = discover_single_child_wrappers(str(scope), str(root))

    assert [Path(d.wrapper_path).name for d in decisions] == ["B"]
    assert all("EVIL" not in d.wrapper_path and "PWN" not in (d.child_path or "") for d in decisions)
