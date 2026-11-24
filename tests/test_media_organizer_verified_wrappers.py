"""Verified media wrappers merge within their work or classification boundary."""

import os
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import iter_organizing_previews
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_organizer_split_work import put_files
from tests.test_media_package_execute_jobs import _fixture


def _execute(client, settings, preview):
    job = _batch(client, preview)
    assert _run_next(settings, job)
    return client.get(f"/api/media-organizer/batches/{job}").json()["summary"]


def test_default_photo_wrapper_appends_to_the_dated_work(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2610/261008/作者/存档"
    work = scope / "WJJ-04/2017.05【来源】/17.05.01 海边小屋"
    put_files(work, {"001.jpg": b"root", "新建文件夹/001.jpg": b"child", "新建文件夹/002.png": b"second"})
    root_file = work / "001.jpg"
    before = root_file.stat()

    preview = _preview(client, settings, scope)
    assert preview["summary"]["ready_count"] == 1, preview
    candidate, = preview["units"]
    assert candidate["unit"] == str(work) and candidate["groups"] == []
    assert [Path(move["target"]).name for move in candidate["sample_moves"]] == ["002.jpg", "003.png"]

    assert _execute(client, settings, preview)["success_count"] == 1
    assert {entry.name: entry.read_bytes() for entry in work.iterdir()} == {
        "001.jpg": b"root", "002.jpg": b"child", "003.png": b"second",
    }
    assert root_file.stat().st_ino == before.st_ino
    assert _preview(client, settings, scope)["summary"]["ready_count"] == 0


@pytest.mark.parametrize("select_v", [False, True])
def test_video_classification_wrapper_appends_and_retains_named_work(tmp_path, select_v):
    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2610/261017/作者"
    videos = author / "V"
    put_files(author, {"001.jpg": b"photo", "V/001.mp4": b"root", "V/002.MOV": b"old",
                       "V/Video/001.mov": b"child", "V/Video/002.mp4": b"new",
                       "V/最新4v/001.mp4": b"separate"})
    scope = videos if select_v else author
    preview = _preview(client, settings, scope)
    assert preview["summary"]["ready_count"] == 1, preview
    candidate, = [row for row in preview["units"] if row["status"] == "ready"]
    assert candidate["unit"] == str(videos) and candidate["groups"] == []
    assert [Path(move["target"]).name for move in candidate["sample_moves"]] == ["003.mov", "004.mp4"]
    assert any(row["unit"] == str(videos / "最新4v") for row in preview["units"])

    assert _execute(client, settings, preview)["success_count"] == 1
    assert not (videos / "Video").exists()
    assert (videos / "001.mp4").read_bytes() == b"root"
    assert (videos / "003.mov").read_bytes() == b"child"
    assert (videos / "004.mp4").read_bytes() == b"new"
    assert (videos / "最新4v/001.mp4").read_bytes() == b"separate"
    assert (author / "001.jpg").read_bytes() == b"photo"
    assert _preview(client, settings, scope)["summary"]["ready_count"] == 0


def test_titled_photo_wrapper_lifts_existing_buckets_to_its_work_root(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2610/261001/作者/合集/绿幕篇"
    work = scope / "29小妮"
    photos = {f"P [200 200B]/{i:03}.jpg": b"p" for i in range(1, 201)} | {"P_1 [1 1B]/001.jpg": b"q"}
    put_files(work / "小妮图", photos)
    put_files(work, {"001.mp4": b"film"})
    sibling = scope / "30小张"
    put_files(sibling, {"001.mp4": b"film", "小张图/001.jpg": b"p"})
    version = scope / "31小陶"
    put_files(version / "小陶图", photos)
    put_files(version, {"001.mp4": b"film", "第二次/001.mp4": b"second"})

    preview = _preview(client, settings, scope)
    candidate, = [row for row in preview["units"] if row["status"] == "ready"]
    assert candidate["unit"] == str(work)
    assert [(group["name"], group["count"]) for group in candidate["groups"]] == [
        ("P [200 200B]", 200), ("P_1 [1 1B]", 1), ("V [1 4B]", 1),
    ]
    assert candidate["renamed_count"] == 0
    assert _execute(client, settings, preview)["success_count"] == 1
    assert {p.relative_to(work).as_posix(): p.read_bytes() for p in work.rglob("*") if p.is_file()} == (
        photos | {"V [1 4B]/001.mp4": b"film"}
    )
    assert (sibling / "小张图/001.jpg").is_file() and (version / "第二次/001.mp4").is_file()
    assert (version / "小陶图/P_1 [1 1B]/001.jpg").is_file()
    assert _preview(client, settings, scope)["summary"]["ready_count"] == 0


def test_unnumbered_video_wrapper_is_processed_locally_before_it_can_append(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2610/261015"
    root = scope / "来源目录"
    put_files(root, {"V/root.mp4": b"clip", "V/Video/a.mp4": b"alt ", "V/最新4v/001.mp4": b"work"})

    original = _preview(client, settings, scope)
    assert original["summary"]["file_count"] == 3 and original["summary"]["blocked_count"] == 0
    assert _execute(client, settings, original)["success_count"] == 2
    assert (root / "V/001.mp4").read_bytes() == b"clip"
    assert (root / "V/Video/001.mp4").read_bytes() == b"alt "

    next_preview = _preview(client, settings, scope)
    assert next_preview["summary"]["ready_count"] == 1
    assert _execute(client, settings, next_preview)["success_count"] == 1
    assert (root / "V/002.mp4").read_bytes() == b"alt "
    assert (root / "V/最新4v/001.mp4").read_bytes() == b"work"
    assert _preview(client, settings, scope)["summary"]["ready_count"] == 0


def test_video_append_reports_a_casefolded_target_directory_conflict(tmp_path, monkeypatch):
    root = tmp_path / "2610/261015/作者"
    videos = root / "V"
    put_files(videos, {"001.mp4": b"old", "Video/001.mov": b"new", "002.MOV/001.mp4": b"separate"})
    actual_lexists = os.path.lexists
    # The distinct lowercase path is absent on a case-sensitive NAS mount.
    monkeypatch.setattr(os.path, "lexists", lambda path: (
        False if Path(path) == videos / "002.mov" else actual_lexists(path)
    ))
    records = list(iter_organizing_previews(root, allowed_roots=[tmp_path], include_mapping=True))
    row, = [row for row in records if row["unit"] == str(videos)]
    assert row["status"] == "blocked"
    assert row["conflicts"][0]["reason"] == "target_path_exists"


def test_preserves_default_folder_at_a_date_and_classification_containers(tmp_path):
    scope = tmp_path / "2610/261008"
    put_files(scope, {
        "作者甲/261007/001.jpg": b"root",
        "作者甲/261007/新建文件夹/001.jpg": b"separate",
        "作者甲/261006/p/套图甲/001.jpg": b"a",
        "作者乙/photo/生活照/001.jpg": b"b",
    })
    rows = list(iter_organizing_previews(scope, allowed_roots=[tmp_path], include_mapping=True))
    assert all(row["status"] == "already_organized" for row in rows)
    assert {(move["source"], move["target"]) for row in rows for move in row["_mapping_items"]} == {
        (str(path), str(path)) for path in scope.rglob("*.jpg")
    }
