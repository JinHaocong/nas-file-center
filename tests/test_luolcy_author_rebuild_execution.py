import errno
import os
from pathlib import Path

import pytest

import app.batch.media_package_execution as execution
from app.batch.media_organizer_link_intent import LinkIntent
from app.batch.media_organizer_planner import preview_organizing_unit
from app.batch.media_package_execution import (
    MediaPackageExecutionConflict,
    execute_frozen_manifest,
    load_frozen_manifest,
    prepare_organizer_manifest,
    save_frozen_manifest,
)
from tests.test_media_package_zfuse_publish import force_zos_no_directory_rename


def _preview(author: Path, root: Path) -> dict:
    record = preview_organizing_unit(
        author, media_package_root=root, allowed_roots=[root], mode="luolcy", whole_author=True,
    )
    assert record["status"] == "ready"
    # Preview reports display logical changes; the frozen move engine stages all plan rows.
    return {**record, "needed_moves": record["actual_moves"]}


def _prepare(author: Path, root: Path, record: dict) -> dict:
    return prepare_organizer_manifest(
        author, media_package_root=root, allowed_roots=[root], mode="luolcy",
        quarantine_root=None, preview_record=record, job_id=170,
    )


@pytest.fixture
def mixed_author(tmp_path):
    root = tmp_path / "Luolcy"
    author = root / "2611" / "261123" / "author"
    bucket = author / "P [200 200B]"
    bucket.mkdir(parents=True)
    for number in range(1, 201):
        (bucket / f"{number:03}.jpg").write_bytes(bytes([number]))
    (author / "000.jpg").write_bytes(b"r")
    (author / "clip.mp4").write_bytes(b"v")
    sibling = author / "Named work"
    sibling.mkdir()
    (sibling / "001.jpg").write_bytes(b"independent")
    return root, author, bucket, sibling


@pytest.mark.parametrize("fuse_compat", [False, True])
def test_rebuild_recovers_published_bucket_that_reoccupies_a_staged_sources_name(
    mixed_author, tmp_path, monkeypatch, fuse_compat,
):
    root, author, bucket, sibling = mixed_author
    manifest = _prepare(author, root, _preview(author, root))
    saved = tmp_path / "frozen.json"
    save_frozen_manifest(saved, manifest)
    publish = execution._publish_group
    if fuse_compat:
        force_zos_no_directory_rename(monkeypatch)

    def interrupt_after_first_group(*args, **kwargs):
        publish(*args, **kwargs)
        raise RuntimeError("interrupted after publishing first bucket")

    with monkeypatch.context() as patch:
        patch.setattr(execution, "_publish_group", interrupt_after_first_group)
        with pytest.raises(RuntimeError, match="after publishing first bucket"):
            execute_frozen_manifest(manifest, lease_fence=lambda: None, allow_fuse_compat=fuse_compat)

    # This exact original pathname now belongs to a different frozen photo.
    assert (bucket / "200.jpg").read_bytes() == bytes([199])
    manifest = load_frozen_manifest(saved, job_id=170, package=author)
    result = execute_frozen_manifest(manifest, lease_fence=lambda: None, allow_fuse_compat=fuse_compat)

    assert result["groups_published"] == 2
    assert (bucket / "001.jpg").read_bytes() == b"r"
    assert (author / "P_1 [1 1B]" / "001.jpg").read_bytes() == bytes([200])
    assert (author / "V [1 1B]" / "001.mp4").read_bytes() == b"v"
    assert (sibling / "001.jpg").read_bytes() == b"independent"
    assert {child.name for child in author.iterdir()} == {
        bucket.name, "P_1 [1 1B]", "V [1 1B]", sibling.name,
    }
    assert execute_frozen_manifest(manifest, lease_fence=lambda: pytest.fail("Unexpected mutation"))[
        "files_reconciled"
    ] == 202


def test_rebuild_rejects_foreign_file_in_verified_bucket_before_staging(mixed_author):
    root, author, bucket, _ = mixed_author
    manifest = _prepare(author, root, _preview(author, root))
    foreign = bucket / "unreviewed.jpg"
    foreign.write_bytes(b"new")
    expected = sorted(author.rglob("*"))

    with pytest.raises(MediaPackageExecutionConflict):
        execute_frozen_manifest(manifest, lease_fence=lambda: pytest.fail("Unexpected mutation"))

    assert sorted(author.rglob("*")) == expected
    assert foreign.read_bytes() == b"new"


def test_frozen_author_accepts_unlabelled_source_that_complements_root(tmp_path):
    root = tmp_path / "Luolcy"
    author = root / "2611" / "261123" / "author"
    source = author / "Named set"
    source.mkdir(parents=True)
    (source / "photo.jpg").write_bytes(b"photo")
    (author / "clip.mp4").write_bytes(b"clip")
    manifest = _prepare(author, root, _preview(author, root))
    saved = tmp_path / "frozen.json"
    save_frozen_manifest(saved, manifest)

    manifest = load_frozen_manifest(saved, job_id=170, package=author)
    execute_frozen_manifest(manifest, lease_fence=lambda: None)

    assert (author / "P [1 5B]" / "001.jpg").read_bytes() == b"photo"
    assert not source.exists()


@pytest.mark.parametrize("after_freeze", [False, True])
def test_rebuild_rejects_reviewed_named_work_replaced_at_same_path(mixed_author, tmp_path, after_freeze):
    root, author, _, sibling = mixed_author
    preview = _preview(author, root)
    manifest = _prepare(author, root, preview) if after_freeze else None
    original = tmp_path / "Moved named work"
    sibling.rename(original)
    sibling.mkdir()
    (sibling / "001.jpg").write_bytes(b"other work")

    with pytest.raises(MediaPackageExecutionConflict):
        if after_freeze:
            execute_frozen_manifest(manifest, lease_fence=lambda: pytest.fail("Unexpected mutation"))
        else:
            _prepare(author, root, preview)

    assert (original / "001.jpg").read_bytes() == b"independent"
    assert (sibling / "001.jpg").read_bytes() == b"other work"
    assert (author / "000.jpg").read_bytes() == b"r"


def test_unowned_staging_hardlink_stops_before_other_groups_can_be_created(mixed_author):
    root, author, _, _ = mixed_author
    manifest = _prepare(author, root, _preview(author, root))
    stage = author / ".nfc-media_package-stage-170-0"
    stage.mkdir()
    os.link(author / "000.jpg", stage / "001.jpg")

    with pytest.raises(MediaPackageExecutionConflict):
        execute_frozen_manifest(manifest, lease_fence=lambda: pytest.fail("Unexpected mutation"))

    assert (author / "000.jpg").read_bytes() == b"r"
    assert not (author / ".nfc-media_package-stage-170-1").exists()


@pytest.mark.parametrize("interrupt_file", ["photo.jpg", "001.jpg"])
def test_flat_rebuild_recovers_owned_fuse_link_and_removes_nested_classification(
    tmp_path, monkeypatch, interrupt_file,
):
    root = tmp_path / "Luolcy"
    author = root / "2611" / "261123" / "author"
    nested = author / "pv" / "P2"
    nested.mkdir(parents=True)
    (nested / "photo.jpg").write_bytes(b"nested")
    (author / "000.jpg").write_bytes(b"root")
    manifest = _prepare(author, root, _preview(author, root))
    intent = LinkIntent(tmp_path / "staged-link.json")
    original_link = os.link

    def unsupported_rename(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "FUSE cannot rename without replacement")

    def interrupt_after_link(source, target, *args, **kwargs):
        original_link(source, target, *args, **kwargs)
        if source == interrupt_file:
            raise RuntimeError("interrupted before retiring the link")

    monkeypatch.setattr(execution, "rename_noreplace_at", unsupported_rename)
    with monkeypatch.context() as patch:
        patch.setattr(execution.os, "link", interrupt_after_link)
        with pytest.raises(RuntimeError, match="before retiring the link"):
            execute_frozen_manifest(manifest, lease_fence=lambda: None, link_intent=intent)

    execute_frozen_manifest(manifest, lease_fence=lambda: None, link_intent=intent)

    assert (author / "001.jpg").read_bytes() == b"root"
    assert (author / "002.jpg").read_bytes() == b"nested"
    assert {child.name for child in author.iterdir()} == {"001.jpg", "002.jpg"}
