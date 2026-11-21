"""#402 synthetic grouped-output acceptance against the actual publication engine.

These tests pass an explicit tmp_path-scoped custody fixture to the real
publishing library; this does not certify actual NAS namespace exclusion.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_stage import stage_frozen_sources
from app.batch.media_organizer_publish import publish_frozen_stage
from app.batch import media_organizer_publish as publisher
from app.batch import media_organizer_deferred_cleanup as deferred


@pytest.mark.parametrize(
    ("picture_count", "video_count", "expected_counts"),
    [
        (1, 1, [("P", 1), ("V", 1)]),
        (201, 0, [("P", 200), ("P_1", 1)]),
        (401, 0, [("P", 200), ("P_1", 200), ("P_2", 1)]),
        (200, 1, [("P", 200), ("V", 1)]),
    ],
)
def test_grouped_direct_publication_preserves_every_original_and_file_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    picture_count: int, video_count: int, expected_counts: list[tuple[str, int]],
) -> None:
    unit = tmp_path / "work"
    unit.mkdir(mode=0o700)
    expected_bytes: dict[str, bytes] = {}
    for i in range(picture_count):
        f = unit / f"image-{i:04d}.JpG"
        value = f"image:{i:05d}".encode()
        f.write_bytes(value)
        expected_bytes[str(f)] = value
    for i in range(video_count):
        f = unit / f"video-{i:04d}.Mp4"
        value = f"video:{i:05d}".encode()
        f.write_bytes(value)
        expected_bytes[str(f)] = value

    planned = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert planned["status"] == "ready"
    assert len(planned["items"]) == picture_count + video_count
    assert [(group["kind"], group["count"]) for group in planned["groups"]] == [
        ("P" if name.startswith("P") else "V", amount)
        for name, amount in expected_counts
    ]
    assert [g["name"].split(" [")[0] for g in planned["groups"]] == [
        name for name, _ in expected_counts
    ]
    for group in planned["groups"]:
        assert group["name"].startswith(("P", "V"))
        assert group["count"] <= 200

    manifest = build_frozen_preview_manifest(
        unit, preview_record=planned, allowed_roots=[tmp_path],
        job_id=4028,
    )
    manifest["cleanup_policy"] = "deferred"
    frozen = tmp_path / "evidence" / "4028.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    # Explicit tmp_path-scoped custody: not a production issuer.
    class ScopedFixtureCustody:
        def assert_exclusive(self, folder):
            assert Path(folder).is_relative_to(tmp_path)

    proof = ScopedFixtureCustody()

    def forbid_directory_source_rename(*args, **kwargs):
        raise AssertionError("deferred grouped engine reached source-name rename")

    monkeypatch.setattr(publisher, "rename_noreplace_at", forbid_directory_source_rename)
    result = publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, defer_directory_cleanup=True,
        namespace_custody=proof,
    )
    assert result["file_count"] == picture_count + video_count
    assert result["published_files"] + result["reconciled_files"] == (
        picture_count + video_count
    )

    for row in manifest["moves"]:
        source = Path(row["source"])
        staged = Path(row["target"])
        final = Path(row["final"])
        assert source.read_bytes() == staged.read_bytes() == final.read_bytes()
        assert final.read_bytes() == expected_bytes[str(source)]
        si, ti, fi = source.stat(), staged.stat(), final.stat()
        assert (si.st_dev, si.st_ino) == (ti.st_dev, ti.st_ino) == (fi.st_dev, fi.st_ino)
        assert final.suffix == source.suffix, "last extension case must be preserved"

    for group in manifest["groups"]:
        dest = Path(group["destination"])
        assert dest.is_dir()
        files = [item for item in dest.iterdir() if item.is_file()
                 and not item.name.startswith(".nfc-")]
        assert len(files) == group["count"]
        assert sum(item.stat().st_size for item in files) == group["bytes"]
        assert sorted(item.stem for item in files) == [
            f"{index:03d}" for index in range(1, group["count"] + 1)
        ]
    assert all(Path(literal).read_bytes() == data for literal, data in expected_bytes.items())
    assert not list((unit / manifest["stage_directory"]).glob(".nfc-publish-pending-*"))


def test_grouped_worker_guard_remains_closed_even_with_feature_flags(tmp_path):
    from tests.test_media_organizer_pending_group_race import _grouped
    from app.batch.media_organizer_deferred_cleanup import (
        DeferredCleanupConflict, validate_deferred_publication,
    )

    unit, manifest, frozen = _grouped(tmp_path)
    with pytest.raises(DeferredCleanupConflict, match="SEC-12"):
        validate_deferred_publication(manifest)
    assert all(not Path(group["destination"]).exists() for group in manifest["groups"])
    assert not (unit / manifest["stage_directory"]).exists()
