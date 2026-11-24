"""Confirmed photo ranges and an exact same-work JPEG wrapper."""

from pathlib import Path

import pytest

from app.batch.media_organizer_planner import iter_organizing_previews
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture


def put_files(unit: Path, files: dict[str, bytes]) -> None:
    for relative, data in files.items():
        path = unit / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


@pytest.mark.parametrize(("name", "sources", "destinations"), [
    ("合集 追光-05A4K [3P1V12B]", {
        "追光05A 4K【照片1-2】/001.jpg": b"img1",
        "追光05A 4K【照片1-2】/002.jpg": b"img2",
        "追光05A 4K【照片3-3】/001.jpg": b"img3",
        "追光05A 4K【视频+花絮】/001.mp4": b"film",
    }, {
        "P [3 12B]/001.jpg": b"img1",
        "P [3 12B]/002.jpg": b"img2",
        "P [3 12B]/003.jpg": b"img3",
        "V [1 4B]/001.mp4": b"film",
    }),
    ("作品集 X-061 星光 [2P1V-12B]", {
        "作品集 X-061-R16-JPG/001.JPG": b"img1",
        "作品集 X-061-R16-JPG/002.jpeg": b"img2",
        "001.mp4": b"film",
    }, {
        "P [2 8B]/001.JPG": b"img1",
        "P [2 8B]/002.jpeg": b"img2",
        "V [1 4B]/001.mp4": b"film",
    }),
])
def test_batch_merges_only_verified_components_and_converges(tmp_path, name, sources, destinations):
    client, settings, _ = _fixture(tmp_path)
    collection = settings.data_mount / "Else/来源集合"
    work = collection / name
    peer = collection / "另一套独立作品"
    put_files(work, sources)
    put_files(peer, {"001.jpg": b"peer"})

    preview = _preview(client, settings, collection)
    assert {(row["unit"], row["status"]) for row in preview["units"]} == {
        (str(work), "ready"), (str(peer), "already_organized"),
    }
    job_id = _batch(client, preview)
    assert _run_next(settings, job_id)
    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    assert result["summary"]["success_count"] == 1, result
    assert {path.relative_to(work).as_posix(): path.read_bytes()
            for path in work.rglob("*") if path.is_file()} == destinations
    assert set(work.iterdir()) == {work / Path(path).parent for path in destinations}
    assert (peer / "001.jpg").read_bytes() == b"peer"
    again = _preview(client, settings, collection)
    assert {(row["unit"], row["status"]) for row in again["units"]} == {
        (str(work), "already_organized"), (str(peer), "already_organized"),
    }


@pytest.mark.parametrize(("album", "first", "second", "video"), [
    ("追光-05A4K [3P1V12B]", "追光05A 4K【照片1-1】", "追光05A 4K【照片3-3】", "追光05A 4K【视频+花絮】"),
    ("追光-05A4K [3P1V12B]", "追光05A 4K【照片1-1】", "追光05A 4K【照片1-1】 (副本)", "追光05A 4K【视频+花絮】"),
    ("追光-05A4K [3P1V12B]", "追光05A 4K【照片1-1】", "追光05A 4K【照片2-3】", "追光05A 2K【视频+花絮】"),
    ("别套04D4K [2P1V12B]", "追光05A 4K【照片1-1】", "追光05A 4K【照片2-2】", "追光05A 4K【视频+花絮】"),
    ("追光-05A4K 压缩版 [2P1V12B]", "追光05A 4K【照片1-1】", "追光05A 4K【照片2-2】", "追光05A 4K【视频+花絮】"),
])
def test_ranges_keep_independent_units_without_ownership_proof(tmp_path, album, first, second, video):
    work = tmp_path / album
    put_files(work, {f"{first}/001.jpg": b"img1", f"{second}/001.jpg": b"img2", f"{video}/001.mp4": b"film"})
    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path]))
    assert {(Path(row["unit"]).name, row["status"]) for row in rows} == {
        (name, "already_organized") for name in (first, second, video)
    }


@pytest.mark.parametrize(("child", "name", "declared"), [
    ("作品集 X-061-R18-JPG", "001.jpg", "1P1V"),
    ("作品集 X-062-R16-JPG", "001.jpg", "1P1V"),
    ("作品集 X-061-R16-JPG", "001.png", "1P1V"),
    ("作品集 X-061-R16-JPG", "001.jpg", "2P1V"),
    ("作品集 X-061-R16", "001.jpg", "1P1V"),
])
def test_version_jpeg_keeps_independent_units_when_name_or_counts_differ(tmp_path, child, name, declared):
    work = tmp_path / f"作品集 X-061 星光 [{declared}-8B]"
    put_files(work, {f"{child}/{name}": b"img1", "001.mp4": b"film"})
    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path]))
    assert {(row["unit"], row["status"]) for row in rows} == {
        (str(work), "already_organized"), (str(work / child), "already_organized"),
    }


def test_r16_jpeg_never_absorbs_video_labelled_as_a_different_edition(tmp_path):
    work = tmp_path / "作品集 X-061 星光 [1P1V-8B]"
    jpeg = "作品集 X-061-R16-JPG"
    put_files(work, {f"{jpeg}/001.jpg": b"img1", "星光 R18.mp4": b"film"})
    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True))

    assert {row["unit"] for row in rows} == {str(work), str(work / jpeg)}
    root = next(row for row in rows if row["unit"] == str(work))
    assert root["totals"] == {"P": 0, "V": 1, "Other": 0}


def test_batch_rejects_split_work_when_confirmed_leaf_changes(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "Else/作品集 X-061 星光 [1P1V-8B]"
    files = {"作品集 X-061-R16-JPG/001.jpg": b"img1", "001.mp4": b"film"}
    put_files(work, files)
    preview = _preview(client, settings, work)
    assert preview["summary"]["ready_count"] == 1
    added = {"作品集 X-061-R16-JPG/002.jpg": b"late"}
    put_files(work, added)

    job_id = _batch(client, preview)
    assert _run_next(settings, job_id)
    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    assert result["summary"]["conflict_count"] == 1, result
    assert {path.relative_to(work).as_posix(): path.read_bytes()
            for path in work.rglob("*") if path.is_file()} == files | added


def test_photo_ranges_keep_numeric_segment_order(tmp_path):
    work = tmp_path / "追光-05A4K [10P1V44B]"
    put_files(work, {
        "追光05A 4K【照片1-1】/001.jpg": b"img1",
        **{f"追光05A 4K【照片2-9】/{index:03}.jpg": b"part" for index in range(1, 9)},
        "追光05A 4K【照片10-10】/001.jpg": b"last",
        "追光05A 4K【视频+花絮】/001.mp4": b"film",
    })
    row, = iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True)

    destinations = {Path(move["source"]).parent.name: Path(move["target"]).name
                    for move in row["_mapping_items"] if move["kind"] == "P"}
    assert destinations == {
        "追光05A 4K【照片1-1】": "001.jpg",
        "追光05A 4K【照片2-9】": "009.jpg",
        "追光05A 4K【照片10-10】": "010.jpg",
    }
