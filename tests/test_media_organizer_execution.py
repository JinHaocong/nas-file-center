"""TDD contract for execution authorization. Never moves any source media."""
from copy import deepcopy
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_manifest import build_frozen_preview_manifest
from app.batch.media_organizer_execution import (
    ExecutionPreflightError, validate_execution_preflight,
)


def candidate(tmp_path):
    unit = tmp_path / "synthetic-work"
    unit.mkdir()
    (unit / "img.jpg").write_bytes(b"photo")
    (unit / "clip.mp4").write_bytes(b"video")
    snapshot = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert snapshot["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        unit, preview_record=snapshot, allowed_roots=[tmp_path], job_id=271,
    )
    return unit, manifest


def check(manifest, root):
    return validate_execution_preflight(manifest, allowed_roots=[root])


def test_preflight_accepts_exact_frozen_inputs_without_filesystem_mutation(tmp_path):
    unit, manifest = candidate(tmp_path)
    result = check(manifest, tmp_path)
    assert result["unit"] == str(unit)
    assert result["file_count"] == 2
    assert result["ready"] is True
    assert (unit / "img.jpg").read_bytes() == b"photo"
    assert (unit / "clip.mp4").read_bytes() == b"video"
    assert not (unit / manifest["stage_directory"]).exists()


def test_preflight_rejects_changed_source_contents_before_any_move(tmp_path):
    unit, manifest = candidate(tmp_path)
    (unit / "img.jpg").write_bytes(b"edited-image")
    with pytest.raises(ExecutionPreflightError, match="changed"):
        check(manifest, tmp_path)
    assert not (unit / manifest["stage_directory"]).exists()


def test_preflight_rejects_foreign_target_occupancy(tmp_path):
    unit, manifest = candidate(tmp_path)
    destination = Path(manifest["moves"][0]["final"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"foreign")
    with pytest.raises(ExecutionPreflightError, match="changed|occupied|foreign"):
        check(manifest, tmp_path)
    assert destination.read_bytes() == b"foreign"


def test_preflight_rejects_forged_final_path_outside_unit(tmp_path):
    unit, manifest = candidate(tmp_path)
    forged = deepcopy(manifest)
    forged["moves"][0]["final"] = str(tmp_path / "elsewhere.jpg")
    with pytest.raises(ExecutionPreflightError, match="target|path|changed"):
        check(forged, tmp_path)
    assert (unit / "img.jpg").exists()


def test_preflight_rejects_existing_untrusted_stage_directory(tmp_path):
    unit, manifest = candidate(tmp_path)
    stage = unit / manifest["stage_directory"]
    stage.mkdir()
    (stage / "unknown.jpg").write_bytes(b"preserve")
    with pytest.raises(ExecutionPreflightError, match="stage|workspace"):
        check(manifest, tmp_path)
    assert (stage / "unknown.jpg").read_bytes() == b"preserve"


def test_preflight_rejects_forged_file_identity(tmp_path):
    _, manifest = candidate(tmp_path)
    forged = deepcopy(manifest)
    forged["moves"][0]["identity"][1] += 1
    with pytest.raises(ExecutionPreflightError, match="identity|changed"):
        check(forged, tmp_path)


def test_preflight_rejects_out_of_scope_allowed_roots(tmp_path):
    _, manifest = candidate(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(ExecutionPreflightError, match="outside|scope|allowed"):
        check(manifest, elsewhere)


def test_preflight_rejects_symlink_replacement_at_source(tmp_path):
    unit, manifest = candidate(tmp_path)
    photo = unit / "img.jpg"
    photo.unlink()
    photo.symlink_to(unit / "clip.mp4")
    with pytest.raises(ExecutionPreflightError, match="changed|symlink"):
        check(manifest, tmp_path)
    assert photo.is_symlink()
