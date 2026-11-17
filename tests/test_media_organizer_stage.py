"""Synthetic staging TDD: frozen custody, no replacement, and interruption recovery."""
from pathlib import Path

import pytest

from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_stage import stage_frozen_sources, StagingConflict


def fixture(tmp_path):
    unit = tmp_path / "work"
    unit.mkdir()
    (unit / "photo.jpg").write_bytes(b"image-a")
    (unit / "video.mp4").write_bytes(b"movie-a")
    (unit / "cover.png").write_bytes(b"image-b")
    snapshot = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert snapshot["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        unit, preview_record=snapshot, allowed_roots=[tmp_path], job_id=801,
    )
    frozen = tmp_path / "private" / "801.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    return unit, manifest, frozen


def stage(manifest, frozen, root, *, resume=False, lease=None):
    return stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[root],
        lease_fence=lease or (lambda: None), resume=resume,
    )


def test_stage_moves_exact_frozen_files_without_publishing_any_targets(tmp_path):
    unit, manifest, frozen = fixture(tmp_path)
    payloads = {m["source"]: Path(m["source"]).read_bytes() for m in manifest["moves"]}
    result = stage(manifest, frozen, tmp_path)
    assert result["staged"] == 3
    assert result["reconciled"] == 0
    assert result["ready_to_publish"] is True
    for move in manifest["moves"]:
        assert not Path(move["source"]).exists()
        assert Path(move["target"]).read_bytes() == payloads[move["source"]]
        assert not Path(move["final"]).exists()
    assert (unit / manifest["stage_directory"] / ".nfc-stage-complete").is_file()


def test_stage_requires_persisted_unmodified_frozen_authority(tmp_path):
    unit, manifest, frozen = fixture(tmp_path)
    frozen.unlink()
    with pytest.raises(StagingConflict, match="frozen|manifest"):
        stage(manifest, frozen, tmp_path)
    assert all(Path(m["source"]).exists() for m in manifest["moves"])
    assert not (unit / manifest["stage_directory"]).exists()


def test_stage_rejects_foreign_existing_stage_without_touching_it(tmp_path):
    unit, manifest, frozen = fixture(tmp_path)
    stage_dir = unit / manifest["stage_directory"]
    stage_dir.mkdir()
    (stage_dir / "do-not-touch.txt").write_bytes(b"foreign")
    with pytest.raises(StagingConflict, match="stage|workspace"):
        stage(manifest, frozen, tmp_path)
    assert (stage_dir / "do-not-touch.txt").read_bytes() == b"foreign"
    assert all(Path(m["source"]).exists() for m in manifest["moves"])


def test_stage_denied_lease_does_not_allocate_workspace(tmp_path):
    unit, manifest, frozen = fixture(tmp_path)
    def denied():
        raise RuntimeError("lost lease")
    with pytest.raises(RuntimeError, match="lost lease"):
        stage(manifest, frozen, tmp_path, lease=denied)
    assert not (unit / manifest["stage_directory"]).exists()
    assert all(Path(m["source"]).exists() for m in manifest["moves"])


def test_resume_requires_owner_marker_and_never_adopts_unknown_stage(tmp_path):
    unit, manifest, frozen = fixture(tmp_path)
    stage_dir = unit / manifest["stage_directory"]
    stage_dir.mkdir()
    with pytest.raises(StagingConflict, match="owner|stage|workspace"):
        stage(manifest, frozen, tmp_path, resume=True)
    assert all(Path(m["source"]).exists() for m in manifest["moves"])


def test_resume_only_reconciles_exact_incomplete_stage(tmp_path, monkeypatch):
    from app.batch import media_organizer_stage as staging
    unit, manifest, frozen = fixture(tmp_path)
    actual_move = staging._move_one
    n = 0
    def stop_after_one(*args, **kwargs):
        nonlocal n
        n += 1
        if n == 2:
            raise RuntimeError("simulated interruption")
        return actual_move(*args, **kwargs)
    monkeypatch.setattr(staging, "_move_one", stop_after_one)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        stage(manifest, frozen, tmp_path)
    assert sum(Path(m["target"]).exists() for m in manifest["moves"]) == 1
    assert sum(Path(m["source"]).exists() for m in manifest["moves"]) == 2
    monkeypatch.setattr(staging, "_move_one", actual_move)
    result = stage(manifest, frozen, tmp_path, resume=True)
    assert result["ready_to_publish"] is True
    assert result["staged"] == 2
    assert result["reconciled"] == 1
    assert all(Path(m["target"]).exists() for m in manifest["moves"])
    assert all(not Path(m["source"]).exists() for m in manifest["moves"])


def test_resume_refuses_modified_staged_inode_or_unlisted_file(tmp_path):
    unit, manifest, frozen = fixture(tmp_path)
    stage(manifest, frozen, tmp_path)
    Path(manifest["moves"][0]["target"]).write_bytes(b"unexpected new bytes")
    with pytest.raises(StagingConflict, match="changed|identity"):
        stage(manifest, frozen, tmp_path, resume=True)
    assert Path(manifest["moves"][0]["target"]).read_bytes() == b"unexpected new bytes"


def test_stage_rejects_source_mutated_since_freeze(tmp_path):
    unit, manifest, frozen = fixture(tmp_path)
    Path(manifest["moves"][0]["source"]).write_bytes(b"changed after freeze")
    with pytest.raises(StagingConflict, match="changed|preview"):
        stage(manifest, frozen, tmp_path)
    assert not (unit / manifest["stage_directory"]).exists()


def test_staging_rejects_workspace_swap_before_file_move_without_exposing_source(tmp_path, monkeypatch):
    """An outsider cannot replace the stage with another empty directory after its witness."""
    from app.batch import media_organizer_stage as staging
    unit, manifest, frozen = fixture(tmp_path)
    stage_path = unit / manifest["stage_directory"]
    detached = unit / "detached-owned-stage"
    original = staging._move_one
    injected = []

    def swap_before_move(*args, **kwargs):
        if not injected:
            stage_path.rename(detached)
            stage_path.mkdir()
            (stage_path / "foreign.txt").write_bytes(b"foreign-owner")
            injected.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(staging, "_move_one", swap_before_move)
    with pytest.raises(StagingConflict, match="stage|workspace|identity|owner|binding"):
        stage(manifest, frozen, tmp_path)
    assert injected
    assert all(Path(row["source"]).read_bytes() in (b"image-a", b"image-b", b"movie-a")
               for row in manifest["moves"])
    assert all(not Path(row["target"]).exists() for row in manifest["moves"])
    assert (stage_path / "foreign.txt").read_bytes() == b"foreign-owner"
    assert (detached / ".nfc-stage-authority").is_file()
    assert list(stage_path.iterdir()) == [stage_path / "foreign.txt"]


def test_staging_rejects_empty_replacement_with_forged_owner_marker(tmp_path, monkeypatch):
    """Even an exact copied witness cannot replace the original stage inode."""
    from app.batch import media_organizer_stage as staging
    unit, manifest, frozen = fixture(tmp_path)
    stage_path = unit / manifest["stage_directory"]
    detached = unit / "detached-private-stage"
    original = staging._move_one
    injected = []

    def swap_empty_with_cloned_marker(*args, **kwargs):
        if not injected:
            stage_path.rename(detached)
            stage_path.mkdir()
            (stage_path / ".nfc-stage-authority").write_bytes(
                (detached / ".nfc-stage-authority").read_bytes())
            injected.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(staging, "_move_one", swap_empty_with_cloned_marker)
    with pytest.raises(StagingConflict, match="stage|workspace|identity|binding"):
        stage(manifest, frozen, tmp_path)
    assert injected
    assert all(Path(row["source"]).is_file() for row in manifest["moves"])
    assert all(not Path(row["target"]).exists() for row in manifest["moves"])
