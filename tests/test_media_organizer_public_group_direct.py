"""SEC-12: public group creation without renaming a mutable source basename.

These are disposable tmp_path-only tests. A tested helper is NOT sufficient
to enable grouping under uncooperative same-UID/root NAS writers: the
mkdirat→openat gap still requires independently proven namespace custody.
"""
from pathlib import Path

import pytest

from app.batch import media_organizer_publish as publishing
from app.batch.media_organizer_stage import stage_frozen_sources, _authority
from tests.test_media_organizer_pending_group_race import _grouped


def _prepare(tmp_path):
    unit, manifest, frozen = _grouped(tmp_path)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    return unit, manifest, frozen


def test_public_group_direct_creation_never_moves_a_source_directory(
    tmp_path, monkeypatch,
):
    unit, manifest, frozen = _prepare(tmp_path)
    name = manifest["groups"][0]["name"]
    source_snapshot = {
        str(row["source"]): Path(row["source"]).read_bytes()
        for row in manifest["moves"]
    }

    def forbid_source_rename(*_args, **_kwargs):
        raise AssertionError(
            "production grouped publishing must never rename a source directory"
        )

    monkeypatch.setattr(publishing, "rename_noreplace_at", forbid_source_rename)
    publishing._create_public_group_direct(
        unit, name, manifest, _authority(manifest), lambda: None,
        frozen_manifest_path=frozen,
    )
    group = unit / name
    assert group.is_dir()
    assert publishing._owned_public(group, _authority(manifest))
    receipt = publishing._group_receipt_path(frozen, 1)
    bound = publishing._read_group_receipt(receipt, manifest, name, 1)
    assert (group.stat().st_dev, group.stat().st_ino) == bound
    assert all(Path(path).read_bytes() == value for path, value in source_snapshot.items())
    assert not list((unit / manifest["stage_directory"]).glob(".nfc-publish-pending-*"))


def test_public_group_direct_creation_refuses_existing_foreign_folder(
    tmp_path, monkeypatch,
):
    unit, manifest, frozen = _prepare(tmp_path)
    name = manifest["groups"][0]["name"]
    foreign = unit / name
    foreign.mkdir()
    (foreign / "keep.txt").write_bytes(b"foreign-bytes")
    original_rename = publishing.rename_noreplace_at

    def forbid_source_rename(*_args, **_kwargs):
        raise AssertionError("wrong source-directory rename")

    monkeypatch.setattr(publishing, "rename_noreplace_at", forbid_source_rename)
    with pytest.raises(publishing.PublishingConflict):
        publishing._create_public_group_direct(
            unit, name, manifest, _authority(manifest), lambda: None,
            frozen_manifest_path=frozen,
        )
    assert (foreign / "keep.txt").read_bytes() == b"foreign-bytes"
    assert not publishing._group_receipt_path(frozen, 1).exists()
    assert original_rename is not None


def test_direct_group_alone_does_not_bypass_sec12_execution_gate(tmp_path):
    unit, manifest, frozen = _prepare(tmp_path)
    with pytest.raises(publishing.PublishingConflict, match="SEC-12"):
        publishing.publish_frozen_stage(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            lease_fence=lambda: None, defer_directory_cleanup=True,
        )
    assert all(not Path(group["destination"]).exists() for group in manifest["groups"])
