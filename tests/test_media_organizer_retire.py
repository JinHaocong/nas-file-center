"""TDD: completed publication must retire staging without losing recovery safety."""
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_stage import stage_frozen_sources
from app.batch.media_organizer_publish import publish_frozen_stage
from app.batch.media_organizer_retire import (
    RetirementConflict, retire_published_stage,
)


def published(tmp_path, *, flat=False):
    unit = tmp_path / "work"
    unit.mkdir()
    files = {"P1/photo.jpg": b"image", "second.jpg": b"another"} if flat else {
        "photo.jpg": b"image", "clip.mp4": b"video",
    }
    for name, data in files.items():
        p = unit / name
        p.parent.mkdir(exist_ok=True, parents=True)
        p.write_bytes(data)
    preview = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert preview["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        unit, preview_record=preview, allowed_roots=[tmp_path], job_id=1020,
    )
    frozen = tmp_path / "private" / "1020.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    return unit, manifest, frozen


def retire(tmp_path, manifest, frozen, *, resume=False, lease=None):
    return retire_published_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lease or (lambda: None), resume=resume,
    )


@pytest.mark.parametrize("flat", [True, False])
def test_retire_published_files_and_markers_produces_canonical_noop(tmp_path, flat):
    unit, manifest, frozen = published(tmp_path, flat=flat)
    result = retire(tmp_path, manifest, frozen)
    assert result["retired_stage_links"] == len(manifest["moves"])
    assert result["finalized"] is True
    assert not (unit / manifest["stage_directory"]).exists()
    for group in manifest["groups"]:
        folder = unit / group["name"]
        assert not any(child.name.startswith(".nfc-") for child in folder.iterdir())
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
    check = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert check["status"] == "already_organized", check
    assert check["needed_moves"] == 0


def test_retirement_requires_all_outputs_before_unlinking_stage(tmp_path):
    unit, manifest, frozen = published(tmp_path)
    missing = Path(manifest["moves"][0]["final"])
    missing.unlink()
    with pytest.raises(RetirementConflict, match="public|missing|identity"):
        retire(tmp_path, manifest, frozen)
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])


def test_public_target_changed_after_publication_blocks_retirement(tmp_path):
    unit, manifest, frozen = published(tmp_path)
    target = Path(manifest["moves"][0]["final"])
    target.unlink()
    target.write_bytes(b"foreign")
    with pytest.raises(RetirementConflict, match="changed|identity|foreign"):
        retire(tmp_path, manifest, frozen)
    assert all(Path(row["target"]).exists() for row in manifest["moves"])


def test_unlisted_public_group_entry_blocks_retirement(tmp_path):
    unit, manifest, frozen = published(tmp_path)
    group = unit / manifest["groups"][0]["name"]
    (group / "foreign.txt").write_bytes(b"foreign")
    with pytest.raises(RetirementConflict, match="foreign|unlisted"):
        retire(tmp_path, manifest, frozen)
    assert (group / "foreign.txt").read_bytes() == b"foreign"
    assert all(Path(row["target"]).exists() for row in manifest["moves"])


def test_partial_retirement_resumes_after_interruption(tmp_path, monkeypatch):
    from app.batch import media_organizer_retire as retirement
    unit, manifest, frozen = published(tmp_path)
    actual = retirement._retire_stage_link
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic crash")
        return actual(*args, **kwargs)

    monkeypatch.setattr(retirement, "_retire_stage_link", interrupted)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        retire(tmp_path, manifest, frozen)
    assert sum(Path(row["target"]).exists() for row in manifest["moves"]) == 1
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
    monkeypatch.setattr(retirement, "_retire_stage_link", actual)
    result = retire(tmp_path, manifest, frozen, resume=True)
    assert result["retired_stage_links"] == 1
    assert result["reconciled_stage_links"] == 1
    assert result["finalized"] is True
    assert preview_semantic_unit(unit, allowed_roots=[tmp_path])["status"] == "already_organized"


def test_retirement_lease_loss_preserves_all_stage_links(tmp_path):
    unit, manifest, frozen = published(tmp_path)
    def reject():
        raise RuntimeError("lease unavailable")
    with pytest.raises(RuntimeError, match="lease unavailable"):
        retire(tmp_path, manifest, frozen, lease=reject)
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])


def test_second_retirement_is_safe_noop(tmp_path):
    unit, manifest, frozen = published(tmp_path)
    retire(tmp_path, manifest, frozen)
    result = retire(tmp_path, manifest, frozen, resume=True)
    assert result["retired_stage_links"] == 0
    assert result["reconciled_stage_links"] == len(manifest["moves"])
    assert result["finalized"] is True


def test_foreign_stage_entry_blocks_retirement_without_deleting_it(tmp_path):
    unit, manifest, frozen = published(tmp_path)
    foreign = unit / manifest["stage_directory"] / "unknown.txt"
    foreign.write_bytes(b"keep")
    with pytest.raises(RetirementConflict, match="foreign|stage"):
        retire(tmp_path, manifest, frozen)
    assert foreign.read_bytes() == b"keep"
    assert all(Path(row["target"]).exists() for row in manifest["moves"])
