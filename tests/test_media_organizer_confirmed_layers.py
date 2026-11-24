"""Verified layers simplify at their work root through the real organizer batch."""

from pathlib import Path

import pytest

from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_organizer_split_work import put_files
from tests.test_media_package_execute_jobs import _fixture


@pytest.mark.parametrize(("work_name", "sources", "destinations"), [
    ("【主题45】", {
        "主题45正片.mp4": b"root",
        "45/主题45-1.mp4": b"one1",
        "45/主题45-2.mp4": b"two2",
    }, {"001.mp4": b"one1", "002.mp4": b"two2", "003.mp4": b"root"}),
    ("A4913-02", {
        "图2/原图.jpg": b"pic1",
        "图2/附件.jpeg": b"pic2",
    }, {"001.jpg": b"pic1", "002.jpeg": b"pic2"}),
    ("9.24号【3V 1p 12M】", {
        "P/Export (1).jpg": b"pic1",
        "1/Export.mp4": b"one1",
        "2/Export.mp4": b"two1",
        "2/Export (1).mp4": b"two2",
    }, {
        "P [1 4B]/001.jpg": b"pic1",
        "V [3 12B]/001.mp4": b"one1",
        "V [3 12B]/002.mp4": b"two2",
        "V [3 12B]/003.mp4": b"two1",
    }),
    ("18.12.19会员福利(2P+1V)★", {
        "样例18.12.19/图包/001.jpg": b"pic1",
        "样例18.12.19/图包/002.jpg": b"pic2",
        "样例18.12.19/视频/001.mp4": b"clip",
    }, {
        "P [2 8B]/001.jpg": b"pic1",
        "P [2 8B]/002.jpg": b"pic2",
        "V [1 4B]/001.mp4": b"clip",
    }),
    ("18.09.11滨海写真(2P+1V)★", {
        "[样例]滨海写真/001.jpg": b"pic1",
        "[样例]滨海写真/002.jpg": b"pic2",
        "[样例]滨海写真/视频/001.mp4": b"clip",
    }, {
        "P [2 8B]/001.jpg": b"pic1",
        "P [2 8B]/002.jpg": b"pic2",
        "V [1 4B]/001.mp4": b"clip",
    }),
])
def test_confirmed_layers_merge_at_the_work_root(tmp_path, work_name, sources, destinations):
    client, settings, _ = _fixture(tmp_path)
    source = settings.data_mount / "Else/2610/261001/作者/260707"
    work = source / work_name
    put_files(work, sources)
    peer = source / "独立作品"
    put_files(peer, {"001.jpg": b"peer"})

    preview = _preview(client, settings, source)
    assert {(row["unit"], row["status"]) for row in preview["units"]} == {
        (str(work), "ready"), (str(peer), "already_organized"),
    }
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["success_count"] == 1, result
    assert {path.relative_to(work).as_posix(): path.read_bytes()
            for path in work.rglob("*") if path.is_file()} == destinations
    assert {name.relative_to(work).as_posix() for name in work.rglob("*") if name.is_dir()} == {
        str(parent) for name in destinations if (parent := Path(name).parent) != Path(".")
    }
    assert (peer / "001.jpg").read_bytes() == b"peer"
    again = _preview(client, settings, source)
    assert again["summary"]["blocked_count"] == again["summary"]["ready_count"] == 0, again


@pytest.mark.parametrize(("work_name", "files"), [
    ("【主题45】", {"主题45超清原版.mp4": b"root", "45/主题45-1.mp4": b"clip"}),
    ("【主题45】", {"主题45.mp4": b"root", "45/主题145-1.mp4": b"clip"}),
    ("A4913-02", {"图2/照片.jpg": b"pic1", "图2/预览.mp4": b"clip"}),
    ("9.24号【2V 1p 12M】", {"P/Export.jpg": b"pic1", "1/甲.mp4": b"one1", "2/乙.mp4": b"two1"}),
    ("9.24号【3V 1p 12M】", {"P/Export.jpg": b"pic1", "1/Export.mp4": b"one1", "2/Export.mp4": b"two1"}),
    ("18.12.19会员福利(1P+1V)★", {"样例18.12.19/001.jpg": b"pic1", "样例18.12.19/001.mp4": b"clip"}),
    ("18.12.19会员福利(1P+1V)★", {"样例18.12.29/001.jpg": b"pic1", "样例18.12.29/视频/001.mp4": b"clip"}),
])
def test_weak_or_ambiguous_wrappers_stay_independent(tmp_path, work_name, files):
    from app.batch.media_organizer_planner import iter_organizing_previews

    work = tmp_path / work_name
    put_files(work, files)
    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True))
    root_rows = [row for row in rows if row["unit"] == str(work)]
    assert not any(row["total_files"] == len(files) for row in root_rows)
