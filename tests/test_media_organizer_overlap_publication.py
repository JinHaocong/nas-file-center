"""Prepared overlap publication preserves every original until confirmation.

Only disposable POSIX fixtures receive synthetic namespace custody. The
production issuer is untouched, and these tests never run final cleanup.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.batch import media_organizer_publish as publishing
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_stage import _authority, stage_frozen_sources


class ScopedCustody:
    def __init__(self, root):
        self.root = root
        self.allowed = True

    def assert_exclusive(self, parent):
        if not self.allowed or not Path(parent).is_relative_to(self.root):
            raise ValueError("synthetic custody revoked")


def _prepared(tmp_path, files, *, policy=True):
    unit = tmp_path / "work"
    unit.mkdir(mode=0o700)
    for name, contents in files.items():
        source = unit / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(contents)
    preview = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert preview["status"] == "ready", preview
    manifest = build_frozen_preview_manifest(
        unit, preview_record=preview, allowed_roots=[tmp_path], job_id=4101,
    )
    manifest["cleanup_policy"] = "deferred"
    if policy:
        manifest["path_role_policy"] = "confirmed_relayout_v1"
    frozen = tmp_path / "private" / "manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    return unit, manifest, frozen, ScopedCustody(tmp_path)


def _publish(tmp_path, manifest, frozen, proof, *, resume=False):
    return publishing.publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, defer_directory_cleanup=True,
        namespace_custody=proof, resume=resume,
    )


def _originals_and_stage_intact(manifest, originals):
    for row in manifest["moves"]:
        source, staged = Path(row["source"]), Path(row["target"])
        assert source.read_bytes() == originals[str(source)]
        assert staged.read_bytes() == originals[str(source)]
        for path in (source, staged):
            info = path.stat()
            assert [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns] == row["identity"]


@pytest.mark.parametrize(("files", "retained", "deferred"), [
    ({"001.jpg": b"a", "z.jpg": b"z"}, 1, 0),
    ({"P [1 5B]/001.jpg": b"photo", "movie.mp4": b"video"}, 1, 0),
    ({"V [1 5B]/001.mp4": b"video", "photo.jpg": b"photo"}, 1, 0),
    ({"P [1 5B]/old.jpg": b"photo", "movie.mp4": b"video"}, 0, 0),
    ({"000.jpg": b"a", "001.jpg": b"b", "002.jpg": b"c"}, 0, 2),
    ({"P [2 2B]/000.jpg": b"a", "P [2 2B]/001.jpg": b"b",
      "movie.mp4": b"v"}, 0, 1),
    ({"000.JPG": b"a", "001.jpg": b"b"}, 0, 1),
], ids=["flat-self", "existing-P", "existing-V", "reused-noncanonical-group",
        "flat-collision-chain", "group-collision-chain", "casefold-collision"])
def test_prepared_publication_retains_sources_and_defers_only_conflicting_finals(
    tmp_path, files, retained, deferred,
):
    unit, manifest, frozen, proof = _prepared(tmp_path, files)
    originals = {row["source"]: Path(row["source"]).read_bytes()
                 for row in manifest["moves"]}
    old_directories = {name: os.lstat(name).st_ino
                       for name in manifest["wrapper_identities"]}
    result = _publish(tmp_path, manifest, frozen, proof)
    assert result["retained_files"] == retained
    assert result["deferred_files"] == deferred
    assert result["publication_complete"] is (deferred == 0)
    assert result["published_files"] + result["reconciled_files"] + deferred == len(files)
    _originals_and_stage_intact(manifest, originals)
    for name, inode in old_directories.items():
        assert os.lstat(name).st_ino == inode
    verified = publishing.verify_prepared_publication(
        manifest, frozen_manifest_path=frozen,
    )
    assert verified["retained_files"] == retained
    assert verified["deferred_files"] == deferred
    assert verified["publication_complete"] is (deferred == 0)
    if deferred and manifest["groups"]:
        assert not (unit / "P [2 2B]" / ".nfc-publish-complete").exists()
        assert (unit / "P [2 2B]" / ".nfc-publish-owner").is_file()


def test_existing_200_file_bucket_survives_201_to_202_growth(tmp_path):
    files = {f"P [200 200B]/{i:03d}.jpg": b"p" for i in range(1, 201)}
    files.update({"P_1 [1 1B]/001.jpg": b"q", "z.jpg": b"z"})
    unit, manifest, frozen, proof = _prepared(tmp_path, files)
    old_inode = (unit / "P [200 200B]").stat().st_ino
    result = _publish(tmp_path, manifest, frozen, proof)
    assert result["retained_files"] == 200
    assert result["published_files"] == 2
    assert result["deferred_files"] == 0
    assert (unit / "P [200 200B]").stat().st_ino == old_inode
    assert (unit / "P_1 [2 2B]/001.jpg").read_bytes() == b"q"
    assert (unit / "P_1 [2 2B]/002.jpg").read_bytes() == b"z"
    for name, value in files.items():
        assert (unit / name).read_bytes() == value


def test_overlap_without_explicit_policy_keeps_existing_refusal(tmp_path):
    unit, manifest, frozen, proof = _prepared(
        tmp_path, {"001.jpg": b"a", "z.jpg": b"z"}, policy=False,
    )
    with pytest.raises(publishing.PublishingConflict, match="retained original"):
        _publish(tmp_path, manifest, frozen, proof)
    assert not (unit / "002.jpg").exists()


def test_reused_group_replacement_is_never_adopted(tmp_path):
    unit, manifest, frozen, proof = _prepared(
        tmp_path, {"P [1 5B]/001.jpg": b"photo", "movie.mp4": b"video"},
    )
    group = unit / "P [1 5B]"
    moved = unit / "detached-input"
    group.rename(moved)
    group.mkdir()
    os.link(moved / "001.jpg", group / "001.jpg")
    with pytest.raises(publishing.PublishingConflict):
        _publish(tmp_path, manifest, frozen, proof)
    assert (group / "001.jpg").read_bytes() == b"photo"
    assert not (group / ".nfc-publish-owner").exists()
    assert not list(frozen.parent.glob("*.group-*.json"))


@pytest.mark.parametrize("foreign", ["extra-file", "copied-owner", "occupied-flat"])
def test_prepared_publication_never_adopts_foreign_entries(tmp_path, foreign):
    if foreign == "occupied-flat":
        unit, manifest, frozen, proof = _prepared(
            tmp_path, {"001.jpg": b"a", "z.jpg": b"z"},
        )
        injected = unit / "002.jpg"
        injected.write_bytes(b"foreign")
    else:
        unit, manifest, frozen, proof = _prepared(
            tmp_path, {"P [1 5B]/001.jpg": b"photo", "movie.mp4": b"video"},
        )
        group = unit / "P [1 5B]"
        injected = group / ("private.txt" if foreign == "extra-file"
                            else ".nfc-publish-owner")
        injected.write_bytes(b"foreign" if foreign == "extra-file" else _authority(manifest))
        injected.chmod(0o600)
    before = injected.read_bytes()
    with pytest.raises(publishing.PublishingConflict):
        _publish(tmp_path, manifest, frozen, proof)
    assert injected.read_bytes() == before
    assert not list(frozen.parent.glob("*.group-*.json"))


@pytest.mark.parametrize("stop", ["receipt", "owner"])
def test_reused_group_recovers_interruption_without_replacing_original_inode(
    tmp_path, monkeypatch, stop,
):
    unit, manifest, frozen, proof = _prepared(
        tmp_path, {"P [1 5B]/001.jpg": b"photo", "movie.mp4": b"video"},
    )
    group = unit / "P [1 5B]"
    original_inode = group.stat().st_ino
    helper_name = "_write_group_receipt" if stop == "receipt" else "_write_marker"
    original = getattr(publishing, helper_name)

    def interrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        if stop == "receipt" or args[1] == ".nfc-publish-owner":
            raise RuntimeError("synthetic interruption")
        return result

    monkeypatch.setattr(publishing, helper_name, interrupt)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        _publish(tmp_path, manifest, frozen, proof)
    monkeypatch.setattr(publishing, helper_name, original)
    result = _publish(tmp_path, manifest, frozen, proof, resume=True)
    assert result["publication_complete"] is True
    assert group.stat().st_ino == original_inode
    assert (group / "001.jpg").read_bytes() == b"photo"
    assert (unit / "V [1 5B]/001.mp4").read_bytes() == b"video"


def test_reused_group_rechecks_custody_between_receipt_and_marker(tmp_path, monkeypatch):
    unit, manifest, frozen, proof = _prepared(
        tmp_path, {"P [1 5B]/001.jpg": b"photo", "movie.mp4": b"video"},
    )
    original = publishing._write_group_receipt

    def revoke_after_receipt(*args, **kwargs):
        original(*args, **kwargs)
        proof.allowed = False

    monkeypatch.setattr(publishing, "_write_group_receipt", revoke_after_receipt)
    with pytest.raises(publishing.PublishingConflict, match="custody"):
        _publish(tmp_path, manifest, frozen, proof)
    assert not (unit / "P [1 5B]/.nfc-publish-owner").exists()
    assert not (unit / "V [1 5B]").exists()
    assert (unit / "P [1 5B]/001.jpg").read_bytes() == b"photo"


@pytest.mark.parametrize("change", ["original", "stage", "final", "extra"])
def test_prepared_reader_rejects_changed_role_without_mutation(tmp_path, change):
    unit, manifest, frozen, proof = _prepared(
        tmp_path, {"P [2 2B]/000.jpg": b"a", "P [2 2B]/001.jpg": b"b",
                   "movie.mp4": b"v"},
    )
    _publish(tmp_path, manifest, frozen, proof)
    target = {
        "original": unit / "P [2 2B]/001.jpg",
        "stage": Path(manifest["moves"][0]["target"]),
        "final": unit / "P [2 2B]/002.jpg",
        "extra": unit / "P [2 2B]/unknown.txt",
    }[change]
    if target.exists():
        target.unlink()
    target.write_bytes(b"foreign")
    before = {p: p.read_bytes() for p in unit.rglob("*") if p.is_file()}
    with pytest.raises(publishing.PublishingConflict):
        publishing.verify_prepared_publication(manifest, frozen_manifest_path=frozen)
    assert {p: p.read_bytes() for p in unit.rglob("*") if p.is_file()} == before
