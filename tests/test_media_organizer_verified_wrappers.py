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


def test_legacy_counted_buckets_become_standard_within_each_work(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2610/261014/作者"
    works = {
        "030 冬日 [2P1V-3MB]": {"Pic [2P-2MB]/001.JPG": b"one", "Pic [2P-2MB]/002.png": b"two",
                              "Video [1V-1MB]/001.mp4": b"film"},
        "031 冬日 2 [1P1V-3MB]": {"Pic [1P-2MB]/001.jpg": b"next", "Video [1V-1MB]/001.MOV": b"video"},
    }
    for name, files in works.items():
        put_files(scope / name, files)

    preview = _preview(client, settings, scope)
    assert preview["summary"]["ready_count"] == 2 and preview["summary"]["file_count"] == 5, preview
    assert {row["unit"]: [group["name"] for group in row["groups"]] for row in preview["units"]} == {
        str(scope / "030 冬日 [2P1V-3MB]"): ["P [2 6B]", "V [1 4B]"],
        str(scope / "031 冬日 2 [1P1V-3MB]"): ["P [1 4B]", "V [1 5B]"],
    }
    assert all(row["renamed_count"] == 0 for row in preview["units"])
    assert _execute(client, settings, preview)["success_count"] == 2
    assert {path.relative_to(scope).as_posix(): path.read_bytes() for path in scope.rglob("*") if path.is_file()} == {
        "030 冬日 [2P1V-3MB]/P [2 6B]/001.JPG": b"one",
        "030 冬日 [2P1V-3MB]/P [2 6B]/002.png": b"two",
        "030 冬日 [2P1V-3MB]/V [1 4B]/001.mp4": b"film",
        "031 冬日 2 [1P1V-3MB]/P [1 4B]/001.jpg": b"next",
        "031 冬日 2 [1P1V-3MB]/V [1 5B]/001.MOV": b"video",
    }
    assert all(not folder.name.startswith(("Pic [", "Video ["))
               for folder in scope.rglob("*") if folder.is_dir())
    again = _preview(client, settings, scope)
    assert again["summary"]["ready_count"] == again["summary"]["blocked_count"] == 0, again


@pytest.mark.parametrize(("title", "photo", "video", "extra"), [
    ("030 冬日", "Pic [1P-2MB]/001.jpg", "Video [1V-1MB]/001.mp4", None),
    ("030 冬日 [2P1V-3MB]", "Pic [1P-2MB]/001.jpg", "Video [1V-1MB]/001.mp4", None),
    ("030 冬日 [1P1V-3MB]", "Pic [2P-2MB]/001.jpg", "Video [1V-1MB]/001.mp4", None),
    ("030 冬日 [1P1V-3MB]", "Pic [1V-2MB]/001.jpg", "Video [1V-1MB]/001.mp4", None),
    ("030 冬日 [1P1V-3MB]", "Pic [1P-2MB]/001.mp4", "Video [1V-1MB]/001.jpg", None),
    ("030 冬日 [1P1V-3MB]", "Pic [1P-2MB]/002.jpg", "Video [1V-1MB]/001.mp4", None),
    ("030 冬日 [1P1V-3MB]", "Pic [1P-2MB]/001.jpg", "Video [1V-1MB]/001.mp4", "4K/001.mp4"),
])
def test_legacy_counted_buckets_require_exact_work_scope(tmp_path, title, photo, video, extra):
    work = tmp_path / "2610/261014/作者" / title
    files = {photo: b"image", video: b"video"}
    if extra is not None:
        files[extra] = b"extra"
    put_files(work, files)
    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path]))
    assert all(row["unit"] != str(work) for row in rows)


def test_legacy_counted_buckets_keep_sources_when_a_target_appears_after_preview(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "Else/2610/261014/作者/030 冬日 [1P1V-3MB]"
    put_files(work, {"Pic [1P-2MB]/001.jpg": b"pic", "Video [1V-1MB]/001.mp4": b"film"})
    preview = _preview(client, settings, work)
    assert preview["summary"]["ready_count"] == 1
    put_files(work, {"P [1 3B]/001.jpg": b"new"})

    assert _execute(client, settings, preview)["conflict_count"] == 1
    assert (work / "Pic [1P-2MB]/001.jpg").read_bytes() == b"pic"
    assert (work / "Video [1V-1MB]/001.mp4").read_bytes() == b"film"
    assert (work / "P [1 3B]/001.jpg").read_bytes() == b"new"


@pytest.mark.parametrize(("name", "wrapper", "direct", "target"), [
    ("17.12.07 会员更新2P1V", "2017-12-7-3BM28895V", "001.jpg", "P [2 7B]/001.jpg"),
    ("2021-02-03 冬日 [1P2V]", "2021_02_03_Z12951X3", "001.MOV", "V [2 8B]/001.MOV"),
    ("海边小屋2", "✅ 全部文件 第 1_2 页-14237579948279325", "001.MOV", "V [2 8B]/001.MOV"),
])
def test_verified_export_wrapper_is_rebuilt_only_in_its_work(tmp_path, name, wrapper, direct, target):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2610/261014/作者/网盘/WJJ-07/2017.12【来源】"
    work = scope / name
    puts = {direct: b"root", f"{wrapper}/P [1 3B]/001.jpg": b"pic", f"{wrapper}/V [1 4B]/001.mp4": b"film"}
    put_files(work, puts)
    sibling = scope / "17.12.07 另一套作品"
    put_files(sibling, {"001.mp4": b"peer"})

    preview = _preview(client, settings, scope)
    assert preview["summary"]["ready_count"] == 1 and preview["summary"]["file_count"] == 4, preview
    row, = [row for row in preview["units"] if row["status"] == "ready"]
    assert row["unit"] == str(work)
    assert row["renamed_count"] == 1
    assert any(move["source"] == str(work / direct) and move["target"] == str(work / target)
               for move in row["sample_moves"])

    assert _execute(client, settings, preview)["success_count"] == 1
    expected = ("P [2 7B]/002.jpg", "V [1 4B]/001.mp4") if direct.endswith(".jpg") else (
        "P [1 3B]/001.jpg", "V [2 8B]/002.mp4",
    )
    assert {path.relative_to(work).as_posix(): path.read_bytes() for path in work.rglob("*") if path.is_file()} == {
        target: b"root", expected[0]: b"pic", expected[1]: b"film",
    }
    assert not (work / wrapper).exists()
    assert (sibling / "001.mp4").read_bytes() == b"peer"
    again = _preview(client, settings, scope)
    assert again["summary"]["ready_count"] == again["summary"]["blocked_count"] == 0, again


@pytest.mark.parametrize(("name", "wrapper", "extra", "has_direct"), [
    ("17.12.07 更新2P1V", "2017-12-8-X812679", None, True),
    ("17.12.07 更新3P1V", "2017-12-7-X812679", None, True),
    ("19.02.29 更新2P1V", "2019-02-29-X812679", None, True),
    ("海边小屋2", "✅ 全部文件 第 2_1 页-14237579948279325", None, True),
    ("海边小屋2", "✅ 全部文件 第 1_2 页-14237579948279325", None, False),
    ("海边小屋2", "✅ 全部文件 第 1_2 页-14237579948279325", "另一套作品/001.mp4", True),
    ("海边小屋2 [1P2V]", "✅ 全部文件 第 1_2 页-14237579948279325", None, True),
    ("海边小屋合集", "✅ 全部文件 第 1_2 页-14237579948279325", None, True),
])
def test_export_rule_does_not_claim_unverified_siblings_or_dates(tmp_path, name, wrapper, extra, has_direct):
    work = tmp_path / "2610/261014/作者/网盘" / name
    put_files(work, {f"{wrapper}/P [1 3B]/001.jpg": b"pic", f"{wrapper}/V [1 4B]/001.mp4": b"film"})
    if has_direct:
        put_files(work, {"001.jpg": b"root"})
    if extra:
        put_files(work, {extra: b"peer"})

    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True))
    assert all(row["status"] == "already_organized" for row in rows)
    assert any(row["unit"] == str(work / wrapper) for row in rows)


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
