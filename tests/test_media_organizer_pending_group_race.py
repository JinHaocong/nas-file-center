"""SEC-12: pending-directory source-name competition must fail closed.

Only synthetic disposable pytest paths. This documents a physical POSIX
constraint: RENAME_NOREPLACE protects the destination, NOT a swapped source.
Until enforceable namespace exclusion or inode-bound directory promotion is
independently validated, deferred grouped publication MUST NOT be reachable.
"""
import os
from pathlib import Path

import pytest

from app.batch.media_organizer_deferred_cleanup import (
    DeferredCleanupConflict, validate_deferred_publication,
)
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch import media_organizer_publish as publishing
from app.batch.media_organizer_stage import stage_frozen_sources


def _grouped(tmp_path):
    unit = tmp_path / "work"
    unit.mkdir()
    (unit / "picture.jpg").write_bytes(b"picture-original")
    (unit / "movie.mp4").write_bytes(b"movie-original")
    preview = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert preview["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        unit, preview_record=preview, allowed_roots=[tmp_path], job_id=4021,
    )
    manifest["cleanup_policy"] = "deferred"
    assert manifest["groups"], "test requires mixed-media grouped publication"
    frozen = tmp_path / "private" / "4021.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    return unit, manifest, frozen


def test_deferred_grouped_plan_fails_before_any_staging_or_public_directory(tmp_path):
    unit, manifest, frozen = _grouped(tmp_path)
    with pytest.raises(DeferredCleanupConflict, match="directory|group|namespace|SEC-12"):
        validate_deferred_publication(manifest)
    assert (unit / "picture.jpg").read_bytes() == b"picture-original"
    assert (unit / "movie.mp4").read_bytes() == b"movie-original"
    assert not (unit / manifest["stage_directory"]).exists()
    assert all(not Path(row["final"]).exists() for row in manifest["moves"])


def test_deferred_publisher_does_not_relocate_a_swapped_private_pending_group(
    tmp_path, monkeypatch,
):
    """Inject at the exact final-check -> rename boundary; no foreign move."""
    unit, manifest, frozen = _grouped(tmp_path)
    # Pre-existing frozen staging is valid; the prohibited next step must
    # still fail BEFORE any public-group promotion.
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    original = publishing.rename_noreplace_at
    observed = []

    def replace_pending_and_rename(src_fd, source_name, dst_fd, final_name):
        if str(source_name).startswith(".nfc-publish-pending-"):
            observed.append(str(final_name))
            detached = "detached-owned-pending-for-audit"
            os.rename(source_name, detached, src_dir_fd=src_fd, dst_dir_fd=src_fd)
            os.mkdir(source_name, mode=0o700, dir_fd=src_fd)
            # A foreign empty replacement is sufficient; a copied marker
            # is not needed to demonstrate the source-name race.
            return original(src_fd, source_name, dst_fd, final_name)
        return original(src_fd, source_name, dst_fd, final_name)

    monkeypatch.setattr(publishing, "rename_noreplace_at", replace_pending_and_rename)
    with pytest.raises(publishing.PublishingConflict, match="group|directory|namespace|SEC-12"):
        publishing.publish_frozen_stage(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            lease_fence=lambda: None, defer_directory_cleanup=True,
        )

    # The SAFE behavior is to reject before invoking any source-name
    # directory rename. In RED the helper is called, moves the injected
    # foreign directory to final_name, then post-hoc inode checking raises.
    assert observed == [], "unsafe grouped directory rename was attempted"
    assert all(not Path(row["final"]).parent.exists() for row in manifest["moves"])
    assert (unit / "picture.jpg").read_bytes() == b"picture-original"
    assert (unit / "movie.mp4").read_bytes() == b"movie-original"
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
