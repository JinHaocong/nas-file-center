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
    assert "CYCLE_DETECTED" in types


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
    assert "CYCLE_DETECTED" in types


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
    assert "TARGET_COLLISION" in types


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
    assert "CASE_COLLISION" in types


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
    assert "NAME_MAX_EXCEEDED" in types


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
    assert "TARGET_IS_SYMLINK" in types
