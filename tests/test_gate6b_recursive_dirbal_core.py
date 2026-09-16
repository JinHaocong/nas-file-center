from __future__ import annotations

from pathlib import PurePosixPath

from app.planning.dedupe_config import validate_and_canonicalize_config
from app.planning.dedupe_engine import (
    DedupeGroupSnapshot,
    DedupeMemberSnapshot,
    evaluate_group,
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
