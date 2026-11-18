"""Deferred-cleanup acceptance: preserve every original directory and stage link.

All changes occur inside disposable pytest fixtures. This is a safer
publication mode than the older auto-retirement library path.
"""
import os
from pathlib import Path

import pytest

from app.batch.media_organizer_deferred_cleanup import (
    DeferredCleanupConflict, validate_deferred_publication,
    record_deferred_cleanup_evidence,
)
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_publish import publish_frozen_stage
from app.batch.media_organizer_stage import stage_frozen_sources


def prepare(tmp_path, *, old_wrapper=False):
    work = tmp_path / "work"
    work.mkdir()
    if old_wrapper:
        (work / "P1").mkdir()
        (work / "P1" / "a.jpg").write_bytes(b"image")
    else:
        (work / "a.jpg").write_bytes(b"image")
    (work / "b.mp4").write_bytes(b"video")
    preview = preview_semantic_unit(work, allowed_roots=[tmp_path])
    assert preview["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        work, preview_record=preview, allowed_roots=[tmp_path], job_id=3331,
    )
    manifest["cleanup_policy"] = "deferred"
    frozen = tmp_path / "private" / "3331.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    return work, manifest, frozen


def execute_deferred(tmp_path, manifest, frozen):
    validate_deferred_publication(manifest)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, defer_directory_cleanup=True,
    )


def test_deferred_publication_preserves_old_empty_wrapper_and_stage_payloads(tmp_path):
    work, manifest, frozen = prepare(tmp_path, old_wrapper=True)
    execute_deferred(tmp_path, manifest, frozen)
    assert (work / "P1").is_dir()
    assert list((work / "P1").iterdir()) == []
    assert all(Path(row["final"]).read_bytes() in (b"image", b"video")
               for row in manifest["moves"])
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert (work / manifest["stage_directory"] / ".nfc-stage-authority").is_file()
    outcome = record_deferred_cleanup_evidence(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    assert outcome["manual_cleanup_required"] is True
    assert outcome["files_published"] == 2
    assert outcome["old_wrapper_count"] == 1
    assert outcome["staged_links_retained"] == 2
    assert (work / "P1").is_dir()
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    report = frozen.with_name(frozen.name + ".manual-cleanup.json")
    assert report.is_file()
    assert report.stat().st_mode & 0o777 == 0o600
    assert preview_semantic_unit(work, allowed_roots=[tmp_path])["status"] == "blocked"


def test_manual_cleanup_evidence_is_idempotent_and_never_unlinks_staging(tmp_path):
    work, manifest, frozen = prepare(tmp_path)
    execute_deferred(tmp_path, manifest, frozen)
    one = record_deferred_cleanup_evidence(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    two = record_deferred_cleanup_evidence(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    assert one == two
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])


def test_replaced_public_group_blocks_deferred_evidence_without_removing_links(tmp_path):
    work, manifest, frozen = prepare(tmp_path)
    execute_deferred(tmp_path, manifest, frozen)
    folder = work / manifest["groups"][0]["name"]
    folder.rename(work / "detached-group")
    folder.mkdir()
    with pytest.raises(DeferredCleanupConflict, match="identity|receipt|foreign"):
        record_deferred_cleanup_evidence(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            lease_fence=lambda: None,
        )
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert not frozen.with_name(frozen.name + ".manual-cleanup.json").exists()


def test_group_requiring_unsafe_old_wrapper_removal_is_rejected_before_any_move(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "clip.mp4").write_bytes(b"video")
    old = work / "P [1 5B]"
    old.mkdir()
    (old / "001.jpg").write_bytes(b"image")
    preview = preview_semantic_unit(work, allowed_roots=[tmp_path])
    assert preview["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        work, preview_record=preview, allowed_roots=[tmp_path], job_id=3341,
    )
    manifest["cleanup_policy"] = "deferred"
    with pytest.raises(DeferredCleanupConflict, match="group|wrapper|occupied|cleanup"):
        validate_deferred_publication(manifest)
    assert (old / "001.jpg").read_bytes() == b"image"
    assert (work / "clip.mp4").read_bytes() == b"video"
    assert not (work / manifest["stage_directory"]).exists()


def test_report_refuses_tampered_private_journal_and_preserves_media(tmp_path):
    work, manifest, frozen = prepare(tmp_path)
    execute_deferred(tmp_path, manifest, frozen)
    record_deferred_cleanup_evidence(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    report = frozen.with_name(frozen.name + ".manual-cleanup.json")
    report.write_bytes(b"foreign-journal")
    with pytest.raises(DeferredCleanupConflict, match="journal|evidence|changed|invalid"):
        record_deferred_cleanup_evidence(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            lease_fence=lambda: None,
        )
    assert report.read_bytes() == b"foreign-journal"
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])


def test_deferred_manifest_forbids_legacy_publication_that_renames_old_wrappers(tmp_path):
    from app.batch.media_organizer_publish import PublishingConflict
    work, manifest, frozen = prepare(tmp_path, old_wrapper=True)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    with pytest.raises(PublishingConflict, match="deferred|automatic|cleanup"):
        publish_frozen_stage(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            lease_fence=lambda: None,
        )
    assert (work / "P1").is_dir()
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert not any(Path(row["final"]).is_file() for row in manifest["moves"])


def test_deferred_manifest_forbids_legacy_stage_retirement_and_directory_deletion(tmp_path):
    from app.batch.media_organizer_retire import (
        RetirementConflict, retire_published_stage,
    )
    work, manifest, frozen = prepare(tmp_path, old_wrapper=True)
    execute_deferred(tmp_path, manifest, frozen)
    with pytest.raises(RetirementConflict, match="deferred|automatic|cleanup"):
        retire_published_stage(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            lease_fence=lambda: None,
        )
    assert (work / "P1").is_dir()
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
