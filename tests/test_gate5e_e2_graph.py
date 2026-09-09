from pathlib import Path
import pytest

from app.batch_utilities.graph import (
    TargetItemCandidate,
    BlockingConflict,
    GraphResolutionResult,
    resolve_suffix_transform_graph,
)


def make_cand(source: str, target: str, root_id: int = 1, root_path: str = "/allowed") -> TargetItemCandidate:
    rel = Path(source).name
    return TargetItemCandidate(
        source_path=source,
        target_path=target,
        index_root_id=root_id,
        index_root_path=root_path,
        relative_path=rel,
        size=100,
        mtime_ns=1000,
        device=1,
        inode=1,
        original_cand_id=1,
    )


def test_independent_ordering(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    # Two items with no dependencies
    c1 = make_cand(str(root / "b.txt"), str(root / "b.bak"), root_path=str(root))
    c2 = make_cand(str(root / "a.txt"), str(root / "a.bak"), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1, c2],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert not result.has_blocking_conflicts
    assert len(result.conflicts) == 0
    # Lexical order: a.txt before b.txt
    assert [x.source_path for x in result.ordered_items] == [str(root / "a.txt"), str(root / "b.txt")]


def test_vacating_occupant_ordering(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    # On disk, a and a.txt exist
    f_a = root / "a"
    f_a.write_text("hello a")
    f_atxt = root / "a.txt"
    f_atxt.write_text("hello a.txt")

    c1 = make_cand(str(f_a), str(root / "a.txt"), root_path=str(root))
    c2 = make_cand(str(f_atxt), str(root / "a.txt.txt"), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1, c2],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert not result.has_blocking_conflicts
    # c2 (a.txt -> a.txt.txt) MUST execute before c1 (a -> a.txt)
    assert [x.source_path for x in result.ordered_items] == [str(f_atxt), str(f_a)]


def test_cycle_detection_2_nodes(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    f_a = root / "a"
    f_a.write_text("a")
    f_b = root / "b"
    f_b.write_text("b")

    # A -> B and B -> A
    c1 = make_cand(str(f_a), str(f_b), root_path=str(root))
    c2 = make_cand(str(f_b), str(f_a), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1, c2],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "RENAME_CYCLE" in types



def test_cycle_detection_3_nodes(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    f_a = root / "a"
    f_a.write_text("a")
    f_b = root / "b"
    f_b.write_text("b")
    f_c = root / "c"
    f_c.write_text("c")

    # A -> B, B -> C, C -> A
    c1 = make_cand(str(f_a), str(f_b), root_path=str(root))
    c2 = make_cand(str(f_b), str(f_c), root_path=str(root))
    c3 = make_cand(str(f_c), str(f_a), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1, c2, c3],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "RENAME_CYCLE" in types


def test_cycle_detection_3_nodes(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    f_a = root / "a"
    f_a.write_text("a")
    f_b = root / "b"
    f_b.write_text("b")
    f_c = root / "c"
    f_c.write_text("c")

    # A -> B, B -> C, C -> A
    c1 = make_cand(str(f_a), str(f_b), root_path=str(root))
    c2 = make_cand(str(f_b), str(f_c), root_path=str(root))
    c3 = make_cand(str(f_c), str(f_a), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1, c2, c3],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "RENAME_CYCLE" in types


def test_planned_target_collision(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    c1 = make_cand(str(root / "a.jpg"), str(root / "target.txt"), root_path=str(root))
    c2 = make_cand(str(root / "b.png"), str(root / "target.txt"), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1, c2],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "PLANNED_TARGET_COLLISION" in types


def test_existing_unvacating_target(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    # Target already exists on disk, but is NOT an item in the plan
    target = root / "existing.txt"
    target.write_text("occupied")

    c1 = make_cand(str(root / "src.jpg"), str(target), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "TARGET_EXISTS" in types


def test_case_only_rename_blocked(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    # Case-only rename: a.txt -> A.txt
    c1 = make_cand(str(root / "a.txt"), str(root / "A.txt"), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "CASE_ONLY_COLLISION" in types


def test_name_max_exceeded(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    long_name = "x" * 256 + ".txt"
    c1 = make_cand(str(root / "a.txt"), str(root / long_name), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "NAME_TOO_LONG" in types


def test_target_is_symlink_blocked(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    other = tmp_path / "other"
    other.write_text("other")

    target_link = root / "symlink_target.txt"
    target_link.symlink_to(other)

    c1 = make_cand(str(root / "source.txt"), str(target_link), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "TARGET_SYMLINK" in types


def test_existing_directory_casefold_occupant_linux(tmp_path):
    """Reviewer reproduction B: existing A.TXT on disk blocks src.jpg -> a.txt with CASE_ONLY_COLLISION."""
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    # Existing file with uppercase extension on disk
    f_existing = root / "A.TXT"
    f_existing.write_text("existing content")

    f_src = root / "src.jpg"
    f_src.write_text("source content")

    # Planned rename: src.jpg -> a.txt
    c1 = make_cand(str(f_src), str(root / "a.txt"), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "CASE_ONLY_COLLISION" in types


def test_blocked_occupant_propagation_phase_g5(tmp_path):
    """Reviewer reproduction C: a.txt -> a.txt.txt blocked, causing a -> a.txt to also block with TARGET_EXISTS."""
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    f_a = root / "a"
    f_a.write_text("a")
    f_atxt = root / "a.txt"
    f_atxt.write_text("a.txt")
    f_atxttxt = root / "a.txt.txt"
    f_atxttxt.write_text("existing a.txt.txt unvacating")

    # a.txt -> a.txt.txt (blocked because a.txt.txt exists and is not vacating)
    c1 = make_cand(str(f_atxt), str(f_atxttxt), root_path=str(root))
    # a -> a.txt (occupant a.txt cannot vacate, so this must also be TARGET_EXISTS)
    c2 = make_cand(str(f_a), str(f_atxt), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1, c2],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    conflicts_by_src = {c.source_path: c for c in result.conflicts}
    assert str(f_atxt) in conflicts_by_src
    assert conflicts_by_src[str(f_atxt)].conflict_type == "TARGET_EXISTS"
    assert str(f_a) in conflicts_by_src
    assert conflicts_by_src[str(f_a)].conflict_type == "TARGET_EXISTS"


def test_safe_and_conflict_coexistence(tmp_path):
    """Reviewer reproduction D: safe.jpg -> safe.txt (RENAME) survives in graph alongside bad.jpg -> occupied.txt."""
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    f_occupied = root / "occupied.txt"
    f_occupied.write_text("already here")

    f_safe = root / "safe.jpg"
    f_safe.write_text("safe")
    f_bad = root / "bad.jpg"
    f_bad.write_text("bad")

    c_safe = make_cand(str(f_safe), str(root / "safe.txt"), root_path=str(root))
    c_bad = make_cand(str(f_bad), str(f_occupied), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c_safe, c_bad],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    # Surviving unblocked item must be in ordered_items
    assert len(result.ordered_items) == 1
    assert result.ordered_items[0].source_path == str(f_safe)
    # Bad item has TARGET_EXISTS
    assert len(result.conflicts) == 1
    assert result.conflicts[0].source_path == str(f_bad)
    assert result.conflicts[0].conflict_type == "TARGET_EXISTS"


def test_canonical_alias_identity(tmp_path):
    """Reviewer reproduction E: real/a.jpg and alias/a.jpg resolve to same physical source -> PLANNED_TARGET_COLLISION."""
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    real_dir = root / "real"
    real_dir.mkdir()
    f_real_a = real_dir / "a.jpg"
    f_real_a.write_text("real content")

    alias_dir = root / "alias"
    alias_dir.symlink_to(real_dir, target_is_directory=True)
    f_alias_a = alias_dir / "a.jpg"

    c1 = make_cand(
        str(f_real_a),
        str(real_dir / "a.txt"),
        root_path=str(root),
    )
    c2 = make_cand(
        str(f_alias_a),
        str(alias_dir / "a.txt"),
        root_path=str(root),
    )

    result = resolve_suffix_transform_graph(
        items=[c1, c2],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "PLANNED_TARGET_COLLISION" in types


def test_dynamic_name_max_via_pathconf(tmp_path, monkeypatch):
    """Reviewer reproduction F: dynamic NAME_MAX from pathconf (e.g. 10) causes NAME_TOO_LONG for 11 bytes target."""
    import os
    root = tmp_path / "allowed"
    root.mkdir()
    allowed_roots = [root]

    orig_pathconf = os.pathconf

    def fake_pathconf(path, name):
        if name == "PC_NAME_MAX":
            return 10
        return orig_pathconf(path, name)

    monkeypatch.setattr(os, "pathconf", fake_pathconf)

    # 11-byte target filename: "a123456.txt" (11 bytes)
    c1 = make_cand(str(root / "a.txt"), str(root / "a123456.txt"), root_path=str(root))

    result = resolve_suffix_transform_graph(
        items=[c1],
        allowed_roots=allowed_roots,
        quarantine_root=None,
    )
    assert result.has_blocking_conflicts
    types = [c.conflict_type for c in result.conflicts]
    assert "NAME_TOO_LONG" in types

