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


@pytest.mark.parametrize("count,expected_groups", [(200, []), (201, [200, 1])])
def test_exact_two_hundred_boundary_end_to_end_is_idempotent(tmp_path, count, expected_groups):
    from collections import Counter
    unit = tmp_path / f"work{count}"
    unit.mkdir()
    payloads = Counter()
    for index in range(count):
        contents = f"synthetic-{index:04d}".encode()
        (unit / f"raw_{index:04d}.jpg").write_bytes(contents)
        payloads[contents] += 1
    before = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert before["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        unit, preview_record=before, allowed_roots=[tmp_path], job_id=1021,
    )
    frozen = tmp_path / "private" / "1021.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    stage_frozen_sources(manifest, frozen_manifest_path=frozen,
                         allowed_roots=[tmp_path], lease_fence=lambda: None)
    publish_frozen_stage(manifest, frozen_manifest_path=frozen,
                         allowed_roots=[tmp_path], lease_fence=lambda: None)
    retire_published_stage(manifest, frozen_manifest_path=frozen,
                           allowed_roots=[tmp_path], lease_fence=lambda: None)
    assert [group["count"] for group in manifest["groups"]] == expected_groups
    final_payloads = Counter(Path(row["final"]).read_bytes() for row in manifest["moves"])
    assert final_payloads == payloads
    final_preview = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert final_preview["status"] == "already_organized"
    assert final_preview["needed_moves"] == 0
    assert not (unit / manifest["stage_directory"]).exists()


def test_final_private_marker_gap_blocks_without_deleting_unwitnessed_directory(tmp_path):
    unit, manifest, frozen = published(tmp_path)
    stage = unit / manifest["stage_directory"]
    # Model power failure after all published identities are durable and
    # staging links/markers were retired, but before empty-stage rmdir.
    for row in manifest["moves"]:
        Path(row["target"]).unlink()
    for marker in (".nfc-stage-authority", ".nfc-stage-complete",
                   ".nfc-retirement-authority"):
        path = stage / marker
        if path.exists():
            path.unlink()
    with pytest.raises(RetirementConflict, match="witness|ownership|stage|receipt"):
        retire(tmp_path, manifest, frozen, resume=True)
    assert stage.is_dir()
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])


def test_crash_after_last_private_marker_before_rmdir_recovers_from_durable_receipt(
    tmp_path, monkeypatch,
):
    """No staged file can disappear: receipt must outlive the last marker."""
    from app.batch import media_organizer_retire as retirement
    unit, manifest, frozen = published(tmp_path)
    stage = unit / manifest["stage_directory"]
    original_rmdir = retirement.os.rmdir
    crash = []

    def interrupt_final_rmdir(name, *args, **kwargs):
        if name == stage.name and kwargs.get("dir_fd") is not None and not crash:
            crash.append(name)
            raise RuntimeError("synthetic power loss before last stage rmdir")
        return original_rmdir(name, *args, **kwargs)

    monkeypatch.setattr(retirement.os, "rmdir", interrupt_final_rmdir)
    with pytest.raises(RuntimeError, match="synthetic power loss"):
        retire(tmp_path, manifest, frozen)
    assert crash
    assert stage.is_dir()
    assert list(stage.iterdir()) == []
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
    receipt = frozen.with_name(frozen.name + ".retirement-receipt.json")
    assert receipt.is_file()
    assert receipt.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(retirement.os, "rmdir", original_rmdir)
    result = retire(tmp_path, manifest, frozen, resume=True)
    assert result["finalized"] is True
    assert not stage.exists()
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
    assert preview_semantic_unit(unit, allowed_roots=[tmp_path])["status"] == "already_organized"


def test_last_marker_gap_recovery_rejects_foreign_empty_stage_replacement(
    tmp_path, monkeypatch,
):
    from app.batch import media_organizer_retire as retirement
    unit, manifest, frozen = published(tmp_path)
    stage = unit / manifest["stage_directory"]
    original_rmdir = retirement.os.rmdir

    def fail(name, *args, **kwargs):
        if name == stage.name and kwargs.get("dir_fd") is not None:
            raise RuntimeError("synthetic crash")
        return original_rmdir(name, *args, **kwargs)

    monkeypatch.setattr(retirement.os, "rmdir", fail)
    with pytest.raises(RuntimeError):
        retire(tmp_path, manifest, frozen)
    monkeypatch.setattr(retirement.os, "rmdir", original_rmdir)
    moved = unit / "detached-old-stage"
    stage.rename(moved)
    stage.mkdir()
    with pytest.raises(RetirementConflict, match="receipt|identity|changed|stage"):
        retire(tmp_path, manifest, frozen, resume=True)
    assert stage.is_dir()
    assert moved.is_dir()
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])


def test_last_marker_gap_recovery_rejects_tampered_external_receipt(
    tmp_path, monkeypatch,
):
    from app.batch import media_organizer_retire as retirement
    unit, manifest, frozen = published(tmp_path)
    stage = unit / manifest["stage_directory"]
    original_rmdir = retirement.os.rmdir

    def fail(name, *args, **kwargs):
        if name == stage.name and kwargs.get("dir_fd") is not None:
            raise RuntimeError("synthetic crash")
        return original_rmdir(name, *args, **kwargs)

    monkeypatch.setattr(retirement.os, "rmdir", fail)
    with pytest.raises(RuntimeError):
        retire(tmp_path, manifest, frozen)
    monkeypatch.setattr(retirement.os, "rmdir", original_rmdir)
    receipt = frozen.with_name(frozen.name + ".retirement-receipt.json")
    assert receipt.exists()
    receipt.write_text("forged receipt", encoding="utf-8")
    with pytest.raises(RetirementConflict, match="receipt|invalid|changed|checksum"):
        retire(tmp_path, manifest, frozen, resume=True)
    assert stage.is_dir()
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])


def test_retirement_rejects_replaced_public_group_with_cloned_marker_and_hardlinks(
    tmp_path,
):
    """A foreign P/V directory must not be trusted even if contents look exact."""
    unit, manifest, frozen = published(tmp_path)
    group = unit / manifest["groups"][0]["name"]
    saved = unit / "detached-published-group"
    group.rename(saved)
    group.mkdir()
    for original in saved.iterdir():
        if original.name.startswith(".nfc-"):
            (group / original.name).write_bytes(original.read_bytes())
        else:
            (group / original.name).hardlink_to(original)
    with pytest.raises(RetirementConflict, match="receipt|identity|replaced|foreign"):
        retire(tmp_path, manifest, frozen)
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert saved.is_dir()
    assert group.is_dir()


def test_retirement_rejects_modified_group_identity_receipt(tmp_path):
    """Private proof must survive until the verified final publication retires."""
    unit, manifest, frozen = published(tmp_path)
    proof = frozen.with_name(frozen.name + ".group-000001.json")
    assert proof.is_file()
    proof.write_text("invalid identity receipt", encoding="utf-8")
    with pytest.raises(RetirementConflict, match="receipt|identity|corrupted|unsafe"):
        retire(tmp_path, manifest, frozen)
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
