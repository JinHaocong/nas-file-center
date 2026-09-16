from __future__ import annotations

from pathlib import PurePosixPath

from app.planning.dedupe_config import validate_and_canonicalize_config
from app.planning.dedupe_engine import (
    LCA_DIRECT,
    DedupeGroupSnapshot,
    DedupeMemberSnapshot,
    accumulate_recursive_released_bytes,
    compute_same_root_lca,
    derive_recursive_balance_bucket,
    directory_ancestors_to_scan_root,
    evaluate_group,
    run_advanced_dedupe,
)


def _member(
    absolute_path: str,
    *,
    scan_root_index: int,
    scan_root_path: str,
    mtime_ns: int = 100,
    size: int = 100,
) -> DedupeMemberSnapshot:
    relative = PurePosixPath(absolute_path).relative_to(PurePosixPath(scan_root_path)).as_posix()
    return DedupeMemberSnapshot(
        absolute_path=absolute_path,
        relative_path=relative,
        scan_root_index=scan_root_index,
        scan_root_path=scan_root_path,
        mtime_ns=mtime_ns,
        size=size,
    )


def _config(*, mtime: bool = False):
    factors = {"mtime": {"mode": "newest", "weight": 100}} if mtime else {}
    return validate_and_canonicalize_config(
        {
            "schema_version": 1,
            "selection_mode": "recursive_directory_balanced_by_bytes",
            "factors": factors,
        }
    )


def _two_root_group(*, left_mtime: int = 100, right_mtime: int = 100) -> DedupeGroupSnapshot:
    return DedupeGroupSnapshot(
        provenance_id="gate6b-task5",
        content_hash="a" * 64,
        file_size=100,
        members=(
            _member(
                "/zroot/z.dat",
                scan_root_index=0,
                scan_root_path="/zroot",
                mtime_ns=left_mtime,
            ),
            _member(
                "/aroot/a.dat",
                scan_root_index=1,
                scan_root_path="/aroot",
                mtime_ns=right_mtime,
            ),
        ),
    )


def _same_root_group(
    *paths: str,
    provenance_id: str = "same-root",
    file_size: int = 100,
    mtimes: tuple[int, ...] | None = None,
) -> DedupeGroupSnapshot:
    mtimes = mtimes or tuple(100 for _ in paths)
    return DedupeGroupSnapshot(
        provenance_id=provenance_id,
        content_hash=(provenance_id.encode("utf-8").hex() + "0" * 64)[:64],
        file_size=file_size,
        members=tuple(
            _member(
                path,
                scan_root_index=0,
                scan_root_path="/root",
                mtime_ns=mtimes[idx],
                size=file_size,
            )
            for idx, path in enumerate(paths)
        ),
    )


def _cross_root_group(
    members: tuple[tuple[str, int, str, int], ...],
    *,
    provenance_id: str,
    file_size: int = 100,
) -> DedupeGroupSnapshot:
    return DedupeGroupSnapshot(
        provenance_id=provenance_id,
        content_hash=(provenance_id.encode("utf-8").hex() + "0" * 64)[:64],
        file_size=file_size,
        members=tuple(
            _member(
                path,
                scan_root_index=root_index,
                scan_root_path=root_path,
                mtime_ns=mtime_ns,
                size=file_size,
            )
            for path, root_index, root_path, mtime_ns in members
        ),
    )


def test_historical_weighted_fixture_keeps_lexical_tie_break():
    config = validate_and_canonicalize_config(
        {"schema_version": 1, "selection_mode": "weighted", "factors": {}}
    )

    result = evaluate_group(
        _two_root_group(),
        config,
        scan_roots=["/zroot", "/aroot"],
        current_released_bytes={0: 500, 1: 0},
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/aroot/a.dat"
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.selection_reason == "deterministic_path_tie_break"
    assert winner.balance_info is None


def test_historical_balanced_by_bytes_fixture_keeps_scan_root_balance():
    config = validate_and_canonicalize_config(
        {"schema_version": 1, "selection_mode": "balanced_by_bytes", "factors": {}}
    )

    result = evaluate_group(
        _two_root_group(),
        config,
        scan_roots=["/zroot", "/aroot"],
        current_released_bytes={0: 500, 1: 0},
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/zroot/z.dat"
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.selection_reason == "balanced_by_bytes"
    assert winner.balance_info == {"spread_before": 500, "spread_after": 400}


def test_recursive_mode_unique_highest_scorer_wins_even_when_balance_prefers_other_root():
    config = validate_and_canonicalize_config(
        {
            "schema_version": 1,
            "selection_mode": "recursive_directory_balanced_by_bytes",
            "factors": {"mtime": {"mode": "newest", "weight": 100}},
        }
    )

    result = evaluate_group(
        _two_root_group(left_mtime=200, right_mtime=100),
        config,
        scan_roots=["/zroot", "/aroot"],
        current_released_bytes={0: 10_000, 1: 0},
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/zroot/z.dat"
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.total_score == 100
    assert winner.selection_reason == "unique_top_score"


def test_recursive_mode_path_priority_beats_balance():
    config = validate_and_canonicalize_config(
        {
            "schema_version": 1,
            "selection_mode": "recursive_directory_balanced_by_bytes",
            "factors": {
                "path_priority": {
                    "enabled": True,
                    "weight": 1000,
                    "rules": [{"scope": "absolute", "pattern": "/zroot/*"}],
                }
            },
        }
    )

    result = evaluate_group(
        _two_root_group(),
        config,
        scan_roots=["/zroot", "/aroot"],
        current_released_bytes={0: 10_000, 1: 0},
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/zroot/z.dat"
    winner = next(m for m in result.members if m.recommended_keep)
    loser = next(m for m in result.members if not m.recommended_keep)
    assert winner.total_score == 1000
    assert loser.total_score == 0
    assert winner.selection_reason == "unique_top_score"


def test_same_root_lca_and_bucket_follow_actual_branch_point():
    parents = ["/root/library/show/A", "/root/library/show/B/deep"]
    lca = compute_same_root_lca(parents, "/root")

    assert lca == "/root/library/show"
    assert derive_recursive_balance_bucket(parents[0], lca) == "/root/library/show/A"
    assert derive_recursive_balance_bucket(parents[1], lca) == "/root/library/show/B"


def test_parent_equal_lca_uses_synthetic_lca_direct_bucket():
    lca = compute_same_root_lca(["/root/library", "/root/library/branch"], "/root")

    assert lca == "/root/library"
    assert derive_recursive_balance_bucket("/root/library", lca) == LCA_DIRECT
    assert derive_recursive_balance_bucket("/root/library/branch", lca) == "/root/library/branch"


def test_recursive_released_bytes_accumulate_parent_through_scan_root_without_mutation():
    original = {"/root": 10, "/root/A": 20}
    updated = accumulate_recursive_released_bytes(
        original,
        file_path="/root/A/deep/file.bin",
        scan_root_path="/root",
        file_size=7,
    )

    assert original == {"/root": 10, "/root/A": 20}
    assert updated == {
        "/root": 17,
        "/root/A": 27,
        "/root/A/deep": 7,
    }
    assert directory_ancestors_to_scan_root(
        "/root/A/deep/file.bin", "/root"
    ) == ("/root/A/deep", "/root/A", "/root")


def test_recursive_same_root_two_branches_uses_directory_bytes_not_scan_root_only():
    group = _same_root_group(
        "/root/A/dup.bin",
        "/root/B/dup.bin",
        provenance_id="two-branches",
    )

    result = evaluate_group(
        group,
        _config(),
        scan_roots=["/root"],
        current_released_bytes={0: 5000},
        current_released_bytes_by_directory={"/root/A": 1000, "/root/B": 0},
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/root/A/dup.bin"
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.selection_reason == "recursive_directory_balanced_by_bytes"
    assert winner.balance_info["lca"] == "/root"
    assert winner.balance_info["bucket"] == "/root/A"
    assert winner.balance_info["bucket_released_bytes_before"] == {
        "/root/A": 1000,
        "/root/B": 0,
    }
    assert winner.balance_info["bucket_released_bytes_after"] == {
        "/root/A": 1000,
        "/root/B": 100,
    }


def test_recursive_deep_branch_lca_is_below_scan_root():
    group = _same_root_group(
        "/root/media/show/Season A/a.mkv",
        "/root/media/show/Season B/b.mkv",
        provenance_id="deep-lca",
    )

    result = evaluate_group(
        group,
        _config(),
        scan_roots=["/root"],
        current_released_bytes_by_directory={
            "/root/media/show/Season A": 900,
            "/root/media/show/Season B": 0,
        },
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/root/media/show/Season A/a.mkv"
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.balance_info["lca"] == "/root/media/show"
    assert winner.balance_info["bucket"] == "/root/media/show/Season A"


def test_three_buckets_and_multiple_members_in_one_bucket_are_balanced_by_bytes():
    group = _same_root_group(
        "/root/A/a1.bin",
        "/root/A/deep/a2.bin",
        "/root/B/b.bin",
        "/root/C/c.bin",
        provenance_id="three-buckets",
        file_size=50,
    )

    result = evaluate_group(
        group,
        _config(),
        scan_roots=["/root"],
        current_released_bytes_by_directory={
            "/root/A": 500,
            "/root/B": 0,
            "/root/C": 0,
        },
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/root/A/a1.bin"
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.balance_info["lca"] == "/root"
    assert set(winner.balance_info["bucket_released_bytes_after"]) == {
        "/root/A",
        "/root/B",
        "/root/C",
    }


def test_lca_direct_is_not_replaced_by_recursive_lca_aggregate():
    group = _same_root_group(
        "/root/direct.bin",
        "/root/A/a.bin",
        provenance_id="lca-direct",
        file_size=25,
    )

    result = evaluate_group(
        group,
        _config(),
        scan_roots=["/root"],
        current_released_bytes_by_directory={
            "/root": 10_000,
            "/root/A": 0,
        },
    )

    assert result.recommended_keep is not None
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.balance_info["lca"] == "/root"
    before = winner.balance_info["bucket_released_bytes_before"]
    assert before[LCA_DIRECT] == 0
    assert before["/root/A"] == 0
    assert "/root" not in before


def test_sequential_groups_balance_bytes_not_item_counts():
    config = _config(mtime=True)
    groups = [
        _same_root_group(
            "/root/A/large.bin",
            "/root/B/large.bin",
            provenance_id="01-large",
            file_size=900,
            mtimes=(200, 100),
        ),
        _same_root_group(
            "/root/A/small-1.bin",
            "/root/A/deep/small-2.bin",
            "/root/B/small-3.bin",
            provenance_id="02-small",
            file_size=100,
            mtimes=(100, 100, 200),
        ),
        _same_root_group(
            "/root/A/final.bin",
            "/root/B/final.bin",
            provenance_id="03-final",
            file_size=100,
            mtimes=(100, 100),
        ),
    ]

    result = run_advanced_dedupe(groups, config, scan_roots=["/root"])
    final_group = next(g for g in result.groups if g.group_provenance_id == "03-final")

    # Prior planned releases are A=200 bytes (2 files), B=900 bytes (1 file).
    # Byte balance therefore keeps B and quarantines A. Item-count balancing
    # would choose A instead, so this fixture distinguishes the objectives.
    assert final_group.recommended_keep is not None
    assert final_group.recommended_keep.absolute_path == "/root/B/final.bin"


def test_zero_byte_tie_uses_normalized_path_deterministically():
    group = _same_root_group(
        "/root/B/zero.bin",
        "/root/A/zero.bin",
        provenance_id="zero-byte",
        file_size=0,
    )

    result = evaluate_group(
        group,
        _config(),
        scan_roots=["/root"],
        current_released_bytes_by_directory={},
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/root/A/zero.bin"


def test_lca_helpers_preserve_unicode_spaces_and_long_legal_components():
    long_component = "x" * 120
    left_parent = f"/root/媒体 库/{long_component}/左 分支"
    right_parent = f"/root/媒体 库/{long_component}/右 分支"

    lca = compute_same_root_lca([left_parent, right_parent], "/root")

    assert lca == f"/root/媒体 库/{long_component}"
    assert derive_recursive_balance_bucket(left_parent, lca) == f"{lca}/左 分支"
    assert derive_recursive_balance_bucket(right_parent, lca) == f"{lca}/右 分支"


def test_cross_root_balance_selects_root_before_directory_and_never_builds_cross_root_lca():
    group = _cross_root_group(
        (
            ("/root0/A/a.bin", 0, "/root0", 100),
            ("/root0/Z/z.bin", 0, "/root0", 100),
            ("/root1/M/m.bin", 1, "/root1", 100),
        ),
        provenance_id="cross-root-hierarchy",
    )

    result = evaluate_group(
        group,
        _config(),
        scan_roots=["/root0", "/root1"],
        current_released_bytes={0: 1000, 1: 0},
        current_released_bytes_by_directory={
            "/root0/A": 0,
            "/root0/Z": 1000,
            "/root1/M": 0,
        },
    )

    assert result.recommended_keep is not None
    # Root 0 wins the existing Scan Root byte objective. Within root 0,
    # recursive directory balance then keeps Z even though A is lexical-first.
    assert result.recommended_keep.absolute_path == "/root0/Z/z.bin"
    winner = next(m for m in result.members if m.recommended_keep)
    info = winner.balance_info
    assert info["selected_scan_root_index"] == 0
    assert info["lca"] == "/root0"
    assert info["bucket"] == "/root0/Z"
    assert info["lca"].startswith("/root0")
    assert not info["lca"].startswith("/root1")


def test_cross_root_hierarchy_uses_normalized_path_only_after_root_and_directory_ties():
    group = _cross_root_group(
        (
            ("/root0/B/b.bin", 0, "/root0", 100),
            ("/root0/A/a.bin", 0, "/root0", 100),
            ("/root1/M/m.bin", 1, "/root1", 100),
        ),
        provenance_id="cross-root-final-tie",
        file_size=0,
    )

    result = evaluate_group(
        group,
        _config(),
        scan_roots=["/root0", "/root1"],
        current_released_bytes={0: 0, 1: 100},
        current_released_bytes_by_directory={
            "/root0/A": 0,
            "/root0/B": 0,
        },
    )

    assert result.recommended_keep is not None
    assert result.recommended_keep.absolute_path == "/root0/A/a.bin"
    winner = next(m for m in result.members if m.recommended_keep)
    assert winner.balance_info["selected_scan_root_index"] == 0
    assert winner.balance_info["lca"] == "/root0"


def test_run_accumulates_scan_root_and_directory_bytes_for_later_cross_root_group():
    groups = [
        _cross_root_group(
            (
                ("/root0/A/history.bin", 0, "/root0", 100),
                ("/root0/B/keep.bin", 0, "/root0", 200),
                ("/root1/C/history.bin", 1, "/root1", 100),
            ),
            provenance_id="01-history",
            file_size=500,
        ),
        _cross_root_group(
            (
                ("/root0/A/a2.bin", 0, "/root0", 100),
                ("/root0/B/b2.bin", 0, "/root0", 100),
                ("/root1/D/d2.bin", 1, "/root1", 100),
            ),
            provenance_id="02-later",
            file_size=100,
        ),
    ]

    result = run_advanced_dedupe(
        groups,
        _config(mtime=True),
        scan_roots=["/root0", "/root1"],
    )
    later = next(g for g in result.groups if g.group_provenance_id == "02-later")

    # First group releases 500 bytes in root0/A and root1/C. For the later
    # group the root objective selects root0, then directory balance observes
    # A=500/B=0 and therefore keeps A.
    assert later.recommended_keep is not None
    assert later.recommended_keep.absolute_path == "/root0/A/a2.bin"
    winner = next(m for m in later.members if m.recommended_keep)
    assert winner.balance_info["selected_scan_root_index"] == 0
    assert winner.balance_info["bucket_released_bytes_before"] == {
        "/root0/A": 500,
        "/root0/B": 0,
    }
    assert result.released_bytes_by_scan_root == {0: 600, 1: 600}
