import errno
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import create_engine_and_session
from app.exceptions import StateConflictError
from app.tasks.recovery import recover_interrupted_jobs
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture
from tests.test_media_package_zfuse_publish import force_zos_no_directory_rename


def _library(tmp_path):
    client, settings, root = _fixture(tmp_path)
    day = root / "2611/261123"
    author = day / "作者"
    package = author / "原有资源包"
    package.mkdir(parents=True)
    (package / "old.jpg").write_bytes(b"original")
    empty_author = day / "无子包作者"
    empty_author.mkdir()
    (empty_author / "独立图片.jpg").write_bytes(b"solo")
    (author / "a.jpg").write_bytes(b"image")
    (author / "b.mp4").write_bytes(b"video")
    (author / "c.txt").write_bytes(b"details")
    return client, settings, root, author, empty_author, package


def _loose_route(preview, author):
    unit = next(row for row in preview["units"] if row["unit"] == str(author))
    assert unit["status"] == "needs_assignment"
    return f"/api/media-organizer/previews/{preview['job_id']}/loose-files/{unit['loose_id']}"


def test_luolcy_scan_pages_real_loose_files_and_keeps_package_analysis(tmp_path):
    client, settings, root, author, empty_author, package = _library(tmp_path)
    preview = _preview(client, settings, root)
    assert preview["summary"]["needs_assignment_count"] == 1
    assert preview["summary"]["file_count"] == 5
    assert {row["unit"]: row["status"] for row in preview["units"]} == {
        str(author): "needs_assignment", str(empty_author): "ready", str(package): "ready",
    }
    route = _loose_route(preview, author)
    first = client.get(route, params={"page_size": 2}).json()
    assert first["files"] == [
        {"source": str(author / "a.jpg"), "kind": "P", "bytes": 5},
        {"source": str(author / "b.mp4"), "kind": "V", "bytes": 5},
    ]
    assert first["total_files"] == 3
    assert first["packages"] == [package.name]
    assert client.get(route, params={"page": 2, "page_size": 2}).json()["files"] == [
        {"source": str(author / "c.txt"), "kind": "Other", "bytes": 7},
    ]
    filtered = client.get(f"/api/media-organizer/previews/{preview['job_id']}",
                          params={"status_filter": "needs_assignment"}).json()
    assert filtered["filtered_total"] == 1

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    assert (author / "a.jpg").read_bytes() == b"image"
    assert (empty_author / "001.jpg").read_bytes() == b"solo"
    assert (package / "001.jpg").read_bytes() == b"original"


@pytest.mark.parametrize(("image_count", "video_count", "groups"), [
    (1, 0, {}),
    (1, 1, {"P [1 1B]": 1, "V [1 1B]": 1}),
    (350, 0, {"P [200 200B]": 200, "P_1 [150 150B]": 150}),
])
def test_luolcy_direct_author_media_organizes_in_place(tmp_path, image_count, video_count, groups):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251115/DDchunbild"
    author.mkdir(parents=True)
    sources = {f"photo-{i:03d}.jpg": b"p" for i in range(image_count)}
    sources.update({f"clip-{i:03d}.mp4": b"v" for i in range(video_count)})
    for name, payload in sources.items():
        (author / name).write_bytes(payload)

    preview = _preview(client, settings, author.parent)
    unit, = preview["units"]
    assert (unit["unit"], unit["status"], unit["needed_moves"]) == (str(author), "ready", len(sources))
    assert {group["name"]: group["count"] for group in unit["groups"]} == groups
    assert {path.name for path in author.iterdir()} == sources.keys()

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert [(item["unit"], item["status"]) for item in report["items"]] == [(str(author), "success")]
    if groups:
        assert {path.name for path in author.iterdir()} == groups.keys()
        for name, count in groups.items():
            extension, payload = (".jpg", b"p") if name.startswith("P") else (".mp4", b"v")
            assert {path.name: path.read_bytes() for path in (author / name).iterdir()} == {
                f"{i:03d}{extension}": payload for i in range(1, count + 1)
            }
    else:
        assert {path.name: path.read_bytes() for path in author.iterdir()} == {"001.jpg": b"p"}
    again = _preview(client, settings, author)
    assert again["summary"]["needed_moves"] == 0
    assert again["summary"]["already_organized_count"] == (len(groups) or 1)


def test_luolcy_lifts_verified_buckets_without_changing_names_or_root_files(tmp_path):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    sources = {
        "图片/P [2 2B]/001.png": b"a",
        "图片/P [2 2B]/002.JPG": b"b",
        "图片/P_1 [1 1B]/001.png": b"c",
        "001.mp4": b"root video",
        "命名作品/001.jpg": b"work",
    }
    for relative, content in sources.items():
        path = author / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    untouched = {name: (author / name).stat().st_ino for name in ("001.mp4", "命名作品/001.jpg")}

    preview = _preview(client, settings, author)
    author_row, work = preview["units"]
    assert (author_row["unit"], author_row["status"], author_row["needed_moves"], author_row["renamed_count"]) == (
        str(author), "ready", 3, 0,
    )
    assert work["unit"] == str(author / "命名作品")
    assert {Path(move["source"]).relative_to(author).as_posix():
            Path(move["target"]).relative_to(author).as_posix() for move in author_row["sample_moves"]} == {
        name: name.removeprefix("图片/") for name in sources if name.startswith("图片/")
    }

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"] == {"success_count": 1, "skipped_count": 1, "conflict_count": 0, "failed_count": 0}, report
    assert not (author / "图片").exists()
    for relative, content in sources.items():
        assert (author / relative.removeprefix("图片/")).read_bytes() == content
    assert all((author / name).stat().st_ino == inode for name, inode in untouched.items())
    rescan = _preview(client, settings, author)
    assert not rescan["summary"]["ready_count"] and not rescan["summary"]["blocked_count"]


@pytest.mark.parametrize("root_label", ["P [1 1B]", "P [1 2B]"])
def test_luolcy_rebuilds_verified_root_and_nested_buckets_with_the_same_ordinal(tmp_path, root_label):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251120/作者"
    root_photo = b"a" if root_label == "P [1 1B]" else b"aa"
    video = author / "V [1 1B]/001.mp4"
    for path, content in {
        author / root_label / "001.jpg": root_photo,
        author / "p/P [1 1B]/001.png": b"b",
        video: b"v",
    }.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    original_video = video.stat().st_ino

    preview = _preview(client, settings, author)
    row, = preview["units"]
    assert (row["status"], row["totals"]) == ("ready", {"P": 2, "V": 1, "Other": 0}), row
    output = author / f"P [2 {len(root_photo) + 1}B]"
    assert {group["destination"] for group in row["groups"]} == {str(output), str(video.parent)}

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["success_count"] == 1, report
    assert set(author.iterdir()) == {output, video.parent}
    assert sorted(path.read_bytes() for path in output.iterdir()) == [root_photo, b"b"]
    assert video.read_bytes() == b"v" and video.stat().st_ino == original_video
    assert _preview(client, settings, author)["summary"]["ready_count"] == 0


@pytest.mark.parametrize(("source", "other", "status"), [
    ("P/P [1 1B]/001.jpg", "P [2 2B]/001.jpg", "blocked"),
    ("P/P [1 1B]/001.jpg", "P [1 1B]/001.jpg", "blocked"),
    ("P/P [1 1B]/001.jpg", "268MB/001.mp4", None),
    ("P/P [1 1B]/001.jpg", "11.19/001.mp4", None),
    ("P/V [1 1B]/001.mp4", None, None),
    ("P/P [2 1B]/001.jpg", None, None),
    ("P/P [1 2B]/001.jpg", None, None),
    ("P/P [1 1B]/002.jpg", None, None),
    ("P/P [1 1B]/001.jpg", "P/独立作品/001.jpg", None),
    ("P/P [1 1B]/001.jpg", "P/002.jpg", None),
    ("P/P [1 1B]/001.jpg", "001.jpg", "blocked"),
])
def test_luolcy_lift_requires_verified_numbered_buckets_and_free_targets(tmp_path, source, other, status):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    files = {source: b"a"}
    if other:
        files[other] = b"bb"
    for relative, contents in files.items():
        path = author / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    preview = _preview(client, settings, author)
    units = {row["unit"]: row for row in preview["units"]}
    if status is None:
        assert str(author) not in units
    else:
        row = units[str(author)]
        assert row["status"] == status
        assert row["reason"] == ("作者根已有同类型散件，需单独确认如何合并" if other == "001.jpg"
                                 else "作者根的目标桶编号已占用")
        assert row["sample_moves"] == []
        assert str(author / "P") not in units


def test_luolcy_author_rebuild_combines_classification_contents_and_keeps_named_work(tmp_path):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    sources = {
        "photo.jpg": b"a", "P/001.jpg": b"b", "V/001.mp4": b"c", "V2/001.mp4": b"d",
        "命名作品/001.jpg": b"e",
    }
    for relative, content in sources.items():
        path = author / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    preview = _preview(client, settings, author)
    assert [(row["unit"], row["status"]) for row in preview["units"]] == [
        (str(author), "ready"), (str(author / "命名作品"), "already_organized"),
    ]
    author_row = preview["units"][0]
    assert author_row["totals"] == {"P": 2, "V": 2, "Other": 0}
    assert {move["source"] for move in author_row["sample_moves"]} == {
        str(author / path) for path in sources if not path.startswith("命名作品/")
    }
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"] == {"success_count": 1, "skipped_count": 1, "conflict_count": 0, "failed_count": 0}, result
    assert {
        path.relative_to(author).as_posix(): path.read_bytes()
        for path in author.glob("*/*") if path.is_file()
    } == {
        "P [2 2B]/001.jpg": b"b", "P [2 2B]/002.jpg": b"a",
        "V [2 2B]/001.mp4": b"c", "V [2 2B]/002.mp4": b"d",
        "命名作品/001.jpg": b"e",
    }
    assert {path.name for path in author.iterdir()} == {"P [2 2B]", "V [2 2B]", "命名作品"}
    assert _preview(client, settings, author)["summary"]["needed_moves"] == 0


def test_luolcy_author_rebuild_accepts_pv_classifications_and_preserves_uncertain_wrappers(tmp_path):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    for name, data in {
        "pv/P [1 1B]/001.jpg": b"p",
        "pv/V [1 1B]/001.mp4": b"v",
        "V2/001.jpg": b"x",
        "图片/001.jpg": b"y",
    }.items():
        path = author / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    preview = _preview(client, settings, author)
    assert [(row["unit"], row["status"]) for row in preview["units"]] == [
        (str(author), "ready"), (str(author / "V2"), "already_organized"),
    ]
    row = preview["units"][0]
    assert row["totals"] == {"P": 2, "V": 1, "Other": 0}
    assert {Path(move["source"]).relative_to(author).as_posix() for move in row["sample_moves"]} == {
        "pv/P [1 1B]/001.jpg", "pv/V [1 1B]/001.mp4", "图片/001.jpg",
    }
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"]["success_count"] == 1, result
    assert not (author / "pv").exists()
    assert not (author / "图片").exists()
    assert (author / "V2/001.jpg").read_bytes() == b"x"
    assert _preview(client, settings, author)["summary"]["needed_moves"] == 0


@pytest.mark.parametrize(("direct", "children", "totals"), [
    ("cover.jpg", {"门槛/01.mp4": b"v"}, {"P": 1, "V": 1, "Other": 0}),
    ("clip.mp4", {"独立标题/01.jpg": b"p"}, {"P": 1, "V": 1, "Other": 0}),
    ("cover.jpg", {"新建文件夹/01.mp4": b"v", "片段合集/01.mp4": b"x"}, {"P": 1, "V": 2, "Other": 0}),
    ("cover.jpg", {"短名1v/01.mp4": b"v", "片段合集/01.mp4": b"x"}, {"P": 1, "V": 2, "Other": 0}),
])
def test_luolcy_promotes_a_few_unstructured_media_leaves(tmp_path, direct, children, totals):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    for relative, content in {direct: b"root", **children}.items():
        path = author / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    preview = _preview(client, settings, author)
    row, = preview["units"]
    assert (row["unit"], row["status"], row["totals"]) == (str(author), "ready", totals)
    assert {Path(move["source"]).relative_to(author).as_posix() for move in row["sample_moves"]} == {
        direct, *children,
    }
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"]["success_count"] == 1, result
    assert {path.read_bytes() for path in author.glob("*/*")} == {b"root", *children.values()}
    assert not any((author / name.split("/")[0]).exists() for name in children)
    assert _preview(client, settings, author)["summary"]["needed_moves"] == 0


@pytest.mark.parametrize("children", [
    ["主题一/001.mp4", "主题二/001.mp4"],
    ["只有图的作品/001.jpg"],
    ["含子目录/原版/001.mp4"],
    ["新建文件夹/001.mp4", "主题一/001.mp4", "主题二/001.mp4"],
    ["新建文件夹/001.mp4", "说明也在包内/readme.txt"],
    ["2026-11-12/001.mp4"],
])
def test_luolcy_keeps_media_outside_the_small_leaf_rule_independent(tmp_path, children):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251104/作者"
    for relative in ["cover.jpg", *children]:
        path = author / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"file")

    preview = _preview(client, settings, author)
    rows = {row["unit"]: row for row in preview["units"]}
    assert rows[str(author)]["totals"] == {"P": 1, "V": 0, "Other": 0}
    assert all(Path(move["source"]).parent == author for move in rows[str(author)]["sample_moves"])
    assert sorted(key for key in rows if key != str(author)) == sorted(
        str(author / name.split("/")[0]) for name in children
    )


@pytest.mark.parametrize(("label", "extension", "count"), [
    ("268MB", "mp4", 2),
    ("New 20分钟 1.37G", "jpg", 4),
    ("251104", "jpg", 4),
    ("2025-11", "jpg", 1),
    ("11.19", "jpg", 1),
])
def test_luolcy_with_labelled_batches_organizes_only_direct_media(tmp_path, label, extension, count):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251115/作者"
    protected = [author / label / "001.jpg", author / "V2/001.mp4"]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"package")
    for index in range(1, count + 1):
        (author / f"source ({index}).{extension}").write_bytes(bytes([index]))

    preview = _preview(client, settings, author)
    assert preview["summary"]["needs_assignment_count"] == 0
    rows = {row["unit"]: row for row in preview["units"]}
    row = rows[str(author)]
    assert (row["status"], row["needed_moves"]) == ("ready", count)
    assert all(Path(move["source"]).parent == Path(move["target"]).parent == author
               for move in row["sample_moves"])
    assert {key for key in rows if key != str(author)} == {str(path.parent) for path in protected}
    identity = [path.stat().st_ino for path in protected]

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"] == {"success_count": 1, "skipped_count": 2, "conflict_count": 0, "failed_count": 0}, report
    assert {path.name: path.read_bytes() for path in author.iterdir() if path.is_file()} == {
        f"{index:03d}.{extension}": bytes([index]) for index in range(1, count + 1)
    }
    assert [path.stat().st_ino for path in protected] == identity
    assert all(path.read_bytes() == b"package" for path in protected)
    assert _preview(client, settings, author)["summary"]["already_organized_count"] == 3


def test_luolcy_labelled_batches_without_direct_media_have_no_author_root_plan(tmp_path):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251115/作者"
    for relative in ("268MB/001.mp4", "P/001.jpg"):
        file = author / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"package")

    preview = _preview(client, settings, author)
    assert {row["unit"] for row in preview["units"]} == {str(author / "268MB"), str(author / "P")}
    assert preview["summary"]["already_organized_count"] == 2


def test_luolcy_new_labelled_batch_invalidates_a_preview_that_would_merge_children(tmp_path):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251115/作者"
    (author / "V").mkdir(parents=True)
    (author / "V/001.mp4").write_bytes(b"video")
    (author / "cover.jpg").write_bytes(b"cover")
    preview = _preview(client, settings, author)
    row, = preview["units"]
    assert row["status"] == "ready"
    assert {move["source"] for move in row["sample_moves"]} == {
        str(author / "V/001.mp4"), str(author / "cover.jpg"),
    }

    (author / "268MB").mkdir()
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["conflict_count"] == 1, report
    assert (author / "V/001.mp4").read_bytes() == b"video"
    assert (author / "cover.jpg").read_bytes() == b"cover"
    assert set(author.iterdir()) == {author / "V", author / "cover.jpg", author / "268MB"}


@pytest.mark.parametrize("entry", ["symlink", "nonmedia", "fifo"])
def test_luolcy_author_with_unreviewed_entries_keeps_manual_assignment(tmp_path, entry):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251115/作者"
    author.mkdir(parents=True)
    (author / "cover.jpg").write_bytes(b"p")
    if entry == "symlink":
        (author / "link.jpg").symlink_to(author / "cover.jpg")
    elif entry == "nonmedia":
        (author / "notes.txt").write_bytes(b"notes")
    else:
        os.mkfifo(author / "cover-old.jpg")
    preview = _preview(client, settings, author)
    files = client.get(_loose_route(preview, author)).json()["files"]
    assert {row["source"] for row in files} == (
        {str(author / "cover.jpg"), str(author / "notes.txt")} if entry == "nonmedia"
        else {str(author / "cover.jpg")}
    )
    assert all(row["unit"] != str(author) or not row["sample_moves"] for row in preview["units"])


@pytest.mark.parametrize("after_freeze", [False, True])
def test_luolcy_author_batch_stops_if_an_independent_directory_appears(tmp_path, monkeypatch, after_freeze):
    from app.batch import media_package_execution

    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251115/作者"
    author.mkdir(parents=True)
    source = author / "cover.jpg"
    source.write_bytes(b"p")
    preview = _preview(client, settings, author)
    assert preview["summary"]["ready_count"] == 1

    if after_freeze:
        save = media_package_execution.save_frozen_manifest

        def add_package_at_freeze(path, manifest):
            save(path, manifest)
            (author / "独立包").mkdir()

        monkeypatch.setattr(media_package_execution, "save_frozen_manifest", add_package_at_freeze)
    else:
        (author / "独立包").mkdir()

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["conflict_count"] == 1
    assert {path.name for path in author.iterdir()} == {"cover.jpg", "独立包"}
    assert source.read_bytes() == b"p"


def test_luolcy_direct_author_cannot_cross_a_mounted_calendar_directory(tmp_path, monkeypatch):
    client, settings, root = _fixture(tmp_path)
    author = root / "2511/251115/作者"
    author.mkdir(parents=True)
    source = author / "cover.jpg"
    source.write_bytes(b"p")
    mounted = author.parent.stat()
    real_fstat = os.fstat

    def fstat_with_mounted_day(fd):
        info = real_fstat(fd)
        if (info.st_dev, info.st_ino) == (mounted.st_dev, mounted.st_ino):
            return SimpleNamespace(st_dev=mounted.st_dev + 1)
        return info

    monkeypatch.setattr(os, "fstat", fstat_with_mounted_day)
    preview = _preview(client, settings, root)
    unit, = preview["units"]
    assert (unit["unit"], unit["status"]) == (str(author), "blocked")
    assert "Cross-device" in unit["reason"]
    assert source.read_bytes() == b"p"


@pytest.mark.parametrize("phase", [
    "one_bucket", "all_buckets", "fuse_partial", "foreign_directory", "foreign_bucket", "protected_bucket",
])
def test_luolcy_author_recovery_validates_exact_published_buckets(tmp_path, monkeypatch, phase):
    from app.batch import media_package_execution

    client, settings, root = _fixture(tmp_path, fuse_compat=phase == "fuse_partial")
    author = root / "2511/251115/作者"
    author.mkdir(parents=True)
    (author / "cover.jpg").write_bytes(b"p")
    (author / "clip.mp4").write_bytes(b"v")
    quarantine = settings.data_mount / "quarantine-link"
    if phase == "fuse_partial":
        (author / "z.jpg").write_bytes(b"z")
        force_zos_no_directory_rename(monkeypatch)
    if phase == "protected_bucket":
        isolated = settings.data_mount / "isolated"
        isolated.mkdir()
        quarantine.symlink_to(isolated, target_is_directory=True)
        settings.quarantine_root = quarantine
    preview = _preview(client, settings, author)
    assert preview["summary"]["ready_count"] == 1
    batch_id = _batch(client, preview)
    publish = media_package_execution._publish_group
    link = os.link

    def stop_after_publication(manifest, group_index, *args, **kwargs):
        result = publish(manifest, group_index, *args, **kwargs)
        if group_index == (1 if phase == "all_buckets" else 0):
            raise SystemExit("Worker interrupted after a bucket was published")
        return result

    def stop_after_first_link(source, target, *args, **kwargs):
        link(source, target, *args, **kwargs)
        if source == "001.jpg" and kwargs.get("dst_dir_fd") is not None:
            raise SystemExit("Worker interrupted while publishing FUSE hardlinks")

    with monkeypatch.context() as patch:
        if phase == "fuse_partial":
            patch.setattr(os, "link", stop_after_first_link)
        else:
            patch.setattr(media_package_execution, "_publish_group", stop_after_publication)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    photo = author / ("P [2 2B]" if phase == "fuse_partial" else "P [1 1B]") / "001.jpg"
    video = author / "V [1 1B]" / "001.mp4"
    before = photo.stat().st_ino
    if phase == "foreign_directory":
        (author / "独立包").mkdir()
    elif phase == "foreign_bucket":
        video.parent.mkdir()
        video.write_bytes(b"x")
    elif phase == "protected_bucket":
        quarantine.unlink()
        quarantine.symlink_to(video.parent, target_is_directory=True)
    elif phase == "fuse_partial":
        assert not photo.with_name("002.jpg").exists()

    engine, sessions = create_engine_and_session(settings.database_path)
    try:
        assert recover_interrupted_jobs(
            engine, sessions, worker_id="organizer-test-worker",
        )["recovered_requeued"] == 1
    finally:
        engine.dispose()
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert photo.read_bytes() == b"p"
    assert photo.stat().st_ino == before
    if phase in {"foreign_directory", "foreign_bucket", "protected_bucket"}:
        assert report["summary"]["conflict_count"] == 1
        assert len(list(author.glob(".nfc-*/001.mp4"))) == 1
        if phase == "foreign_bucket":
            assert video.read_bytes() == b"x"
        elif phase == "foreign_directory":
            assert (author / "独立包").is_dir() and not video.exists()
        else:
            assert not video.parent.exists()
    else:
        assert report["summary"]["success_count"] == 1
        assert video.read_bytes() == b"v"
        assert not list(author.rglob(".nfc-*"))
        if phase == "fuse_partial":
            assert photo.with_name("002.jpg").read_bytes() == b"z"


@pytest.mark.parametrize("new", [False, True])
def test_selected_loose_files_generate_only_a_move_draft(tmp_path, new):
    client, settings, _, author, _, existing = _library(tmp_path)
    preview = _preview(client, settings, author)
    route = _loose_route(preview, author)
    package = author / "新建资源包" if new else existing
    source = author / "b.mp4"
    response = client.post(f"{route}/assignments", json={
        "sources": [str(source)], "package_name": package.name, "new_package": new,
    })
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert isinstance(receipt["plan_id"], str)
    assert receipt["status"] == "draft"
    detail = client.get(f"/api/plans/{receipt['plan_id']}").json()
    row, = detail["items"]
    assert row["operation"] == "move"
    assert row["source"] == str(source)
    assert row["target"] == str(package / "b.mp4")
    assert source.read_bytes() == b"video"
    assert (author / "a.jpg").read_bytes() == b"image"
    assert not (package / "b.mp4").exists()
    assert package.exists() is not new


@pytest.mark.parametrize("problem", ["inside_package", "other_author", "link_source", "parent_name",
                                     "new_exists", "link_target", "target_exists", "stale_source"])
def test_loose_file_draft_rejects_out_of_scope_stale_or_conflicting_requests(tmp_path, problem):
    client, settings, _, author, empty_author, package = _library(tmp_path)
    (author / "link.jpg").symlink_to(empty_author / "独立图片.jpg")
    preview = _preview(client, settings, author)
    route = _loose_route(preview, author)
    source = author / "a.jpg"
    request = {"sources": [str(source)], "package_name": package.name, "new_package": False}
    if problem == "inside_package":
        request["sources"] = [str(package / "old.jpg")]
    if problem == "other_author":
        request["sources"] = [str(empty_author / "独立图片.jpg")]
    if problem == "link_source":
        request["sources"] = [str(author / "link.jpg")]
    if problem == "parent_name":
        request.update(package_name=f"../{empty_author.name}", new_package=True)
    if problem == "new_exists":
        request["new_package"] = True
    if problem == "link_target":
        package.rename(author / "另一个包")
        package.symlink_to(empty_author, target_is_directory=True)
    if problem == "target_exists":
        (package / source.name).write_bytes(b"occupied")
    if problem == "stale_source":
        source.write_bytes(b"modified")
    response = client.post(f"{route}/assignments", json=request)
    assert response.status_code == 409, response.text
    assert source.is_file()
    assert client.get("/api/plans").json()["items"] == []


def test_luolcy_legacy_preview_rows_remain_readable(tmp_path):
    client, settings, _, _, _, package = _library(tmp_path)
    preview = _preview(client, settings, package)
    report = settings.reports_dir / "organizer-v1-previews" / preview["job_id"]
    path = report / "summary.json"
    summary = json.loads(path.read_text())
    summary.pop("needs_assignment_count")
    path.write_text(json.dumps(summary) + "\n")
    response = client.get(f"/api/media-organizer/previews/{preview['job_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["units"] == preview["units"]


def _queue_assignment(client, settings, author, package, *, new_package):
    route = _loose_route(_preview(client, settings, author), author)
    receipt = client.post(f"{route}/assignments", json={
        "sources": [str(author / "a.jpg"), str(author / "b.mp4")],
        "package_name": package.name, "new_package": new_package,
    })
    assert receipt.status_code == 200, receipt.text
    plan_route = f"/api/plans/{receipt.json()['plan_id']}"
    frozen = client.post(f"{plan_route}/freeze")
    assert frozen.status_code == 200, frozen.text
    validated = client.post(f"{plan_route}/validate")
    assert validated.status_code == 200, validated.text
    queued = client.post(f"{plan_route}/execute")
    assert queued.status_code == 200, queued.text
    return plan_route, str(queued.json()["work_job_id"])


@pytest.mark.parametrize("new_package", [False, True])
def test_frozen_loose_assignment_moves_only_selected_files_into_the_chosen_package(tmp_path, new_package):
    client, settings, _, author, _, existing = _library(tmp_path)
    package = author / "新资源包" if new_package else existing
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=new_package)
    assert package.exists() is not new_package
    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    assert detail["status"] == "completed", detail
    assert (package / "a.jpg").read_bytes() == b"image"
    assert (package / "b.mp4").read_bytes() == b"video"
    assert (author / "c.txt").read_bytes() == b"details"
    assert (existing / "old.jpg").read_bytes() == b"original"


@pytest.mark.parametrize("problem", ["replaced_package", "claimed_new_package", "occupied_leaf"])
def test_frozen_loose_assignment_does_not_enter_changed_target_or_overwrite(tmp_path, problem):
    client, settings, _, author, other_author, existing = _library(tmp_path)
    new_package = problem == "claimed_new_package"
    package = author / "新资源包" if new_package else existing
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=new_package)
    if problem == "replaced_package":
        package.rename(author / "旧包")
        package.symlink_to(other_author, target_is_directory=True)
    elif new_package:
        package.mkdir()
    else:
        (package / "a.jpg").write_bytes(b"occupied")

    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    assert detail["status"] == "partial", detail
    assert (author / "a.jpg").read_bytes() == b"image"
    if problem == "occupied_leaf":
        assert (package / "a.jpg").read_bytes() == b"occupied"
    else:
        assert (author / "b.mp4").read_bytes() == b"video"
        assert not (package / "a.jpg").exists()
        assert not (other_author / "a.jpg").exists()


def test_frozen_loose_assignment_can_resume_its_own_fuse_hardlink(tmp_path, monkeypatch):
    from app.execution import luolcy_assignment

    client, settings, _, author, _, _ = _library(tmp_path)
    package = author / "新资源包"
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=True)
    real_link = os.link

    def unsupported_rename(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "rename no-replace unsupported")

    def interrupt_after_publication(*args, **kwargs):
        real_link(*args, **kwargs)
        if kwargs.get("dst_dir_fd") is not None:
            raise SystemExit("Worker stopped before retiring the source hardlink")

    monkeypatch.setattr(luolcy_assignment, "rename_noreplace_at", unsupported_rename)
    with monkeypatch.context() as patch:
        patch.setattr(os, "link", interrupt_after_publication)
        with pytest.raises(SystemExit):
            _run_next(settings, job_id)
    assert (author / "a.jpg").samefile(package / "a.jpg")
    engine, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(engine, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        engine.dispose()

    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    assert detail["status"] == "completed", detail
    assert (package / "a.jpg").read_bytes() == b"image"
    assert (package / "b.mp4").read_bytes() == b"video"
    assert not (author / "a.jpg").exists()


@pytest.mark.parametrize("native_rename", [True, False])
def test_new_package_handles_unsupported_directory_fsync_without_losing_files(tmp_path, monkeypatch, native_rename):
    from app.execution import luolcy_assignment

    client, settings, _, author, _, _ = _library(tmp_path)
    package = author / "新资源包"
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=True)
    real_fsync = os.fsync

    def fsync_without_nas_directory_sync(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode) and (info.st_ino == author.stat().st_ino or (
                package.is_dir() and info.st_ino == package.stat().st_ino)):
            raise OSError(errno.EINVAL, "directory fsync unsupported")
        return real_fsync(fd)

    def unsupported_rename(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "rename no-replace unsupported")

    monkeypatch.setattr(os, "fsync", fsync_without_nas_directory_sync)
    if not native_rename:
        monkeypatch.setattr(luolcy_assignment, "rename_noreplace_at", unsupported_rename)
    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    if native_rename:
        assert detail["status"] == "completed", detail
        assert (package / "a.jpg").read_bytes() == b"image"
    else:
        assert detail["status"] == "partial", detail
        assert (author / "a.jpg").read_bytes() == b"image"
        assert (author / "b.mp4").read_bytes() == b"video"
        assert not list(package.iterdir())


def test_luolcy_assignment_requires_the_scope_checked_worker(tmp_path):
    client, settings, _, author, _, package = _library(tmp_path)
    plan_route, _ = _queue_assignment(client, settings, author, package, new_package=False)
    plan_id = client.get(plan_route).json()["id"]
    with pytest.raises(StateConflictError):
        client.app.state.service.execute_plan(plan_id)
    assert (author / "a.jpg").read_bytes() == b"image"
    assert not (package / "a.jpg").exists()
