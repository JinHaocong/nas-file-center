"""SEC-11: adversarial source-basename fault injections on disposable POSIX trees.

These tests target ONLY cleanup_policy=deferred, the V1.6 WorkJob path.
They must never access original NAS media or require real filesystem mutation
outside pytest's tmp_path. Destination NOREPLACE by itself does not pin source.
"""
import errno
from pathlib import Path

import pytest

from app.batch import media_organizer_stage as staging
from app.batch import media_organizer_publish as publishing
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import preview_semantic_unit


def _frozen(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "photo.jpg").write_bytes(b"frozen-photo")
    (work / "video.mp4").write_bytes(b"frozen-video")
    preview = preview_semantic_unit(work, allowed_roots=[tmp_path])
    assert preview["status"] == "ready"
    manifest = build_frozen_preview_manifest(
        work, preview_record=preview, allowed_roots=[tmp_path], job_id=1401,
    )
    manifest["cleanup_policy"] = "deferred"
    frozen = tmp_path / "private" / "manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    return work, manifest, frozen


def _stage(tmp_path, manifest, frozen):
    return staging.stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )


def _publish(tmp_path, manifest, frozen):
    return publishing.publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, defer_directory_cleanup=True,
    )


def test_deferred_staging_preserves_all_original_source_names_and_inodes(
    tmp_path, monkeypatch,
):
    _, manifest, frozen = _frozen(tmp_path)

    def no_rename(*_args, **_kwargs):
        raise AssertionError("deferred staging must never rename a source name")

    monkeypatch.setattr(staging, "rename_noreplace_at", no_rename)
    _stage(tmp_path, manifest, frozen)
    for row in manifest["moves"]:
        source, staged = Path(row["source"]), Path(row["target"])
        assert source.is_file()
        assert source.stat().st_ino == row["identity"][1]
        assert staged.is_file()
        assert staged.stat().st_ino == source.stat().st_ino
        assert staged.read_bytes() == source.read_bytes()


def test_deferred_staging_never_unlinks_source_on_unsupported_rename(
    tmp_path, monkeypatch,
):
    _, manifest, frozen = _frozen(tmp_path)
    original_unlink = staging.os.unlink

    def unsupported(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "synthetic rename unsupported")

    def prohibit_source_unlink(path, *args, **kwargs):
        if kwargs.get("dir_fd") is not None and str(path) in {"photo.jpg", "video.mp4"}:
            raise AssertionError("deferred mode must not unlink original source")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(staging, "rename_noreplace_at", unsupported)
    monkeypatch.setattr(staging.os, "unlink", prohibit_source_unlink)
    _stage(tmp_path, manifest, frozen)
    for row in manifest["moves"]:
        assert Path(row["source"]).is_file()
        assert Path(row["target"]).is_file()


def test_deferred_stage_source_swap_after_final_check_never_moves_foreign(
    tmp_path, monkeypatch,
):
    _, manifest, frozen = _frozen(tmp_path)
    row = manifest["moves"][0]
    source, staged = Path(row["source"]), Path(row["target"])
    detached = source.with_name("detached-frozen-original.jpg")
    original_check = staging._check_identity
    seen = 0
    swapped = False

    def swap_after_last_check(info, identity, path):
        nonlocal seen, swapped
        original_check(info, identity, path)
        if str(path) == str(source):
            seen += 1
            if seen == 3 and not swapped:
                source.rename(detached)
                source.write_bytes(b"foreign-raced-photo")
                swapped = True

    monkeypatch.setattr(staging, "_check_identity", swap_after_last_check)
    with pytest.raises(staging.StagingConflict):
        _stage(tmp_path, manifest, frozen)
    assert swapped
    assert detached.read_bytes() == b"frozen-photo"
    assert source.read_bytes() == b"foreign-raced-photo", "foreign source name was MOVED or removed"
    if staged.exists():
        assert staged.read_bytes() == b"frozen-photo", "foreign file entered the stage"


def test_deferred_publication_source_swap_never_links_foreign_to_public(
    tmp_path, monkeypatch,
):
    _, manifest, frozen = _frozen(tmp_path)
    _stage(tmp_path, manifest, frozen)
    row = manifest["moves"][0]
    staged, final = Path(row["target"]), Path(row["final"])
    detached = staged.with_name("detached-staged-authentic.jpg")
    original_check = publishing._check_identity
    seen = 0
    swapped = False

    def swap_staged_after_check(info, identity, path):
        nonlocal seen, swapped
        original_check(info, identity, path)
        if str(path) == str(staged):
            seen += 1
            if seen == 2 and not swapped:
                staged.rename(detached)
                staged.write_bytes(b"foreign-raced-stage")
                swapped = True

    monkeypatch.setattr(publishing, "_check_identity", swap_staged_after_check)
    with pytest.raises(publishing.PublishingConflict):
        _publish(tmp_path, manifest, frozen)
    assert swapped
    assert detached.read_bytes() == b"frozen-photo"
    assert staged.read_bytes() == b"foreign-raced-stage"
    assert Path(row["source"]).read_bytes() == b"frozen-photo"
    if final.exists():
        assert final.read_bytes() == b"frozen-photo", "foreign inode was publicly linked"

def test_pinned_hardlink_rejects_unsafe_destination_names(tmp_path):
    from app.batch.media_organizer_fd_link import link_pinned_inode_noreplace
    source = tmp_path / "original.bin"
    source.write_bytes(b"verified")
    src_fd = __import__("os").open(source, __import__("os").O_RDONLY)
    folder_fd = __import__("os").open(tmp_path, __import__("os").O_RDONLY | __import__("os").O_DIRECTORY)
    try:
        for name in ("../escape", ".", "", "file\\x00suffix"):
            with pytest.raises(ValueError, match="unsafe"):
                link_pinned_inode_noreplace(src_fd, folder_fd, name)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["original.bin"]
    finally:
        __import__("os").close(folder_fd)
        __import__("os").close(src_fd)
