from __future__ import annotations

from pathlib import Path

import pytest

from scripts.organizer_advanced_c5_acceptance import (
    EXPECTED_ROOT_NAME,
    _validate_project_test_root,
    run_acceptance,
)


def test_c5_acceptance_harness_runs_full_stage_a_to_stage_b_and_leaves_zero_residue(
    tmp_path: Path,
):
    project_root = tmp_path / EXPECTED_ROOT_NAME
    project_root.mkdir()

    evidence = run_acceptance(project_root)

    assert evidence["result"] == "PASS"
    assert evidence["allow_delete"] is False
    assert evidence["stage_a"]["operations"] == ["move", "rmdir_empty"]
    assert evidence["stage_a"]["status"] == "completed"
    assert evidence["stage_a"]["old_digest_rejected"] is True
    assert evidence["stage_b"]["operations"] == ["rename", "rename"]
    assert evidence["stage_b"]["status"] == "completed"
    assert evidence["stage_b"]["final_names"] == ["001.JPG", "002.JPG"]
    assert evidence["stage_a"]["preview_digest"] != evidence["stage_b"]["preview_digest"]
    assert evidence["zero_residue"] is True
    assert list(project_root.iterdir()) == []


def test_c5_acceptance_root_guard_rejects_non_dedicated_or_nonempty_root(
    tmp_path: Path,
):
    wrong_name = tmp_path / "production-data"
    wrong_name.mkdir()
    with pytest.raises(RuntimeError, match="basename"):
        _validate_project_test_root(wrong_name, "YES")

    project_root = tmp_path / EXPECTED_ROOT_NAME
    project_root.mkdir()
    (project_root / "foreign.txt").write_text("do not touch")

    with pytest.raises(RuntimeError, match="must be empty"):
        _validate_project_test_root(project_root, "YES")

    assert (project_root / "foreign.txt").read_text() == "do not touch"


def test_c5_acceptance_root_guard_requires_explicit_synthetic_confirmation(
    tmp_path: Path,
):
    project_root = tmp_path / EXPECTED_ROOT_NAME
    project_root.mkdir()

    with pytest.raises(RuntimeError, match="confirm-synthetic-only"):
        _validate_project_test_root(project_root, "NO")
