"""Automatic in-place cleanup keeps independently named content separate."""

from pathlib import Path

import pytest

from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_organizer_split_work import put_files
from tests.test_media_package_execute_jobs import _fixture


@pytest.mark.parametrize(("scope", "sources", "targets"), [
    ("印象集锦", {
        "42/cover.jpg": b"photo",
        "42/video.mp4": b"clip",
        "57/视频.mp4": b"part",
        "命名作品/001.mp4": b"work",
    }, {
        "42/P [1 5B]/001.jpg": b"photo",
        "42/V [1 4B]/001.mp4": b"clip",
        "57/001.mp4": b"part",
        "命名作品/001.mp4": b"work",
    }),
    ("虞梅", {
        "024/001.jpg": b"photo",
        "024/Video/001.mp4": b"clip",
        "028 作品/001.mp4": b"work",
    }, {
        "024/P [1 5B]/001.jpg": b"photo",
        "024/V [1 4B]/001.mp4": b"clip",
        "028 作品/001.mp4": b"work",
    }),
    ("作者/大合集", {
        "5/preview.mp4": b"clip",
        "5/命名作品/001.mp4": b"work",
    }, {
        "5/001.mp4": b"clip",
        "5/命名作品/001.mp4": b"work",
    }),
    ("作者照片", {
        "cover.jpg": b"photo",
        "video.mp4": b"clip",
        "Telegram-001/001.mp4": b"work",
        "Telegram-002/001.mp4": b"other",
    }, {
        "P [1 5B]/001.jpg": b"photo",
        "V [1 4B]/001.mp4": b"clip",
        "Telegram-001/001.mp4": b"work",
        "Telegram-002/001.mp4": b"other",
    }),
    ("作者视频", {
        "video.mp4": b"clip",
        "未识别文件": b"unknown",
        "命名作品/001.mp4": b"work",
        "另一套/001.jpg": b"other",
    }, {
        "001.mp4": b"clip",
        "未识别文件": b"unknown",
        "命名作品/001.mp4": b"work",
        "另一套/001.jpg": b"other",
    }),
    ("来源目录", {
        "V/root.mp4": b"clip",
        "V/Video/a.mp4": b"alt ",
        "V/最新4v/001.mp4": b"work",
    }, {
        "V/001.mp4": b"clip",
        "V/Video/001.mp4": b"alt ",
        "V/最新4v/001.mp4": b"work",
    }),
    ("分类在同级", {
        "original.mp4": b"clip",
        "P/cover.jpg": b"photo",
        "42/001.mp4": b"work",
    }, {
        "001.mp4": b"clip",
        "P/001.jpg": b"photo",
        "42/001.mp4": b"work",
    }),
])
def test_local_media_fallback_covers_each_file_and_converges(tmp_path, scope, sources, targets):
    client, settings, _ = _fixture(tmp_path)
    root = settings.data_mount / "Else/2610/261015" / scope
    put_files(root, sources)
    selection = settings.data_mount / "Else/2610/261015"
    preview = _preview(client, settings, selection)
    assert preview["summary"]["blocked_count"] == 0, preview
    assert preview["summary"]["file_count"] == len(sources), preview
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["conflict_count"] == result["summary"]["failed_count"] == 0, result
    assert {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()} == targets
    again = _preview(client, settings, selection)
    assert again["summary"]["ready_count"] == again["summary"]["blocked_count"] == 0, again
    assert again["summary"]["file_count"] == len(targets), again


def test_local_numbered_scope_does_not_use_a_changed_video_wrapper(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2610/261015/作者"
    root = author / "024"
    sources = {"001.jpg": b"photo", "Video/001.mp4": b"clip"}
    put_files(root, sources)
    put_files(author, {"028 作品/001.mp4": b"work"})
    preview = _preview(client, settings, author)
    assert preview["summary"]["ready_count"] == 1, preview
    put_files(root, {"Video/独立作品/001.mp4": b"late"})
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["conflict_count"] == 1, result
    assert {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()} == sources | {"Video/独立作品/001.mp4": b"late"}
