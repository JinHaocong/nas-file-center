"""Verify the narrow Luolcy short-video classification through the Batch API."""
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import iter_organizing_previews
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture


def _put(path: Path, contents: bytes = b"item") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)


@pytest.mark.parametrize("peer_name", ["独立命名作品", "3v"])
def test_short_video_wrapper_moves_only_its_own_media_at_author_root(tmp_path, peer_name):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    short = author / "短视频"
    peer = author / peer_name / "001.mp4"
    _put(author / "001.jpg", b"photo")
    _put(short / "001.mp4", b"short")
    _put(peer, b"independent")

    preview = _preview(client, settings, author)
    assert {(row["unit"], row["status"]) for row in preview["units"]} == {
        (str(author), "ready"), (str(peer.parent), "already_organized"),
    }
    proposed = next(row for row in preview["units"] if row["unit"] == str(author))
    assert proposed["totals"] == {"P": 1, "V": 1, "Other": 0}
    assert proposed["needed_moves"] == 2

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["success_count"] == 1, report
    assert report["summary"]["conflict_count"] == 0, report
    assert (author / "P [1 5B]/001.jpg").read_bytes() == b"photo"
    assert (author / "V [1 5B]/001.mp4").read_bytes() == b"short"
    assert peer.read_bytes() == b"independent"
    assert not short.exists()
    again = _preview(client, settings, author)
    assert again["summary"]["ready_count"] == 0
    assert again["summary"]["blocked_count"] == 0


@pytest.mark.parametrize("late_branch", ["短视频/说明.md", "16分钟 1.12G/001.mp4"])
def test_short_video_wrapper_refuses_a_stale_preview_with_changed_scope(tmp_path, late_branch):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    files = {"001.jpg": b"photo", "短视频/001.mp4": b"short", "命名作品/001.mp4": b"independent"}
    for name, contents in files.items():
        _put(author / name, contents)

    preview = _preview(client, settings, author)
    assert preview["summary"]["ready_count"] == 1
    _put(author / late_branch, b"changed")
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()

    assert report["summary"]["conflict_count"] == 1, report
    assert {p.relative_to(author).as_posix(): p.read_bytes() for p in author.rglob("*") if p.is_file()} == {
        **files, late_branch: b"changed",
    }


@pytest.mark.parametrize(("root_file", "short_file", "sibling"), [
    ("001.jpg", "001.mp4", "261103/001.mp4"),
    ("001.jpg", "001.mp4", "1.5GB/001.mp4"),
    ("001.jpg", "001.mp4", "New 15分钟 1.2G/001.mp4"),
    ("001.jpg", "subfolder/001.mp4", "命名作品/001.mp4"),
    ("001.jpg", "001.jpg", "命名作品/001.mp4"),
    ("readme.txt", "001.mp4", "命名作品/001.mp4"),
    (None, "001.mp4", "命名作品/001.mp4"),
])
def test_short_video_wrapper_preserves_ordinary_packages_outside_its_narrow_scope(
    tmp_path, root_file, short_file, sibling,
):
    root = tmp_path / "Luolcy"
    author = root / "2511/251104/作者"
    if root_file is not None:
        _put(author / root_file)
    _put(author / "短视频" / short_file)
    if sibling is not None:
        _put(author / sibling)

    rows = list(iter_organizing_previews(author, allowed_roots=[root], media_package_root=root))

    assert any(row["unit"] == str(author / "短视频") for row in rows)
    assert all(row["unit"] != str(author) or row["status"] != "ready" for row in rows)


@pytest.mark.parametrize(("root_name", "peer", "totals"), [
    ("001.jpg", "3p/001.jpg", {"P": 3, "V": 0, "Other": 0}),
    ("001.mp4", None, {"P": 1, "V": 1, "Other": 0}),
])
def test_ineligible_short_video_label_preserves_preexisting_leaf_inference(tmp_path, root_name, peer, totals):
    root = tmp_path / "Luolcy"
    author = root / "2511/251104/作者"
    _put(author / root_name, b"direct")
    _put(author / "短视频/001.jpg", b"photo")
    if peer:
        _put(author / peer, b"photo")

    row, = iter_organizing_previews(author, allowed_roots=[root], media_package_root=root)
    assert row["unit"] == str(author)
    assert row["status"] == "ready"
    assert row["totals"] == totals


def test_short_video_wrapper_does_not_compete_with_an_existing_video_bucket(tmp_path):
    root = tmp_path / "Luolcy"
    author = root / "2511/251104/作者"
    _put(author / "001.jpg")
    _put(author / "短视频/001.mp4")
    _put(author / "V [1 4B]/001.mp4")

    rows = list(iter_organizing_previews(author, allowed_roots=[root], media_package_root=root))

    assert {(row["unit"], row["status"]) for row in rows} == {
        (str(folder), "already_organized") for folder in (author, author / "短视频", author / "V [1 4B]")
    }
