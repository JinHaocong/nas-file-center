"""Check episode ownership through preview, frozen execution and re-scan."""

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


def test_downloaded_episode_uses_its_root_and_keeps_repeated_ordinals_separate(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    series = settings.data_mount / "Else/2609/260918/作者/存档/合集"
    put_files(series / "00弹-海边", {"@eaDir/旧照片1.jpg/尺寸.jpg": b"p1"})
    put_files(series / "00弹-城市", {"附图/@eaDir/旧照片2.png/尺寸.png": b"p2"})
    put_files(series / "01弹-湖边", {
        "@eaDir/旧视频.mp4/截图.jpg": b"p3", "@eaDir/旧视频.mp4@SynoEAStream": b"meta",
    })
    put_files(series / "？弹-花絮", {"@eaDir/旧照片3.jpg/尺寸.jpg": b"p4"})

    preview = _preview(client, settings, series)
    assert preview["summary"]["ready_count"] == 4 and preview["summary"]["file_count"] == 5, preview
    assert {Path(row["unit"]).name for row in preview["units"]} == {folder.name for folder in series.iterdir()}
    assert _execute(client, settings, preview)["success_count"] == 4
    assert {entry.relative_to(series).as_posix(): entry.read_bytes()
            for entry in series.rglob("*") if entry.is_file()} == {
        "00弹-海边/001.jpg": b"p1", "00弹-城市/001.png": b"p2", "？弹-花絮/001.jpg": b"p4",
        "01弹-湖边/P [1 2B]/001.jpg": b"p3", "01弹-湖边/Other [1 4B]/旧视频.mp4@SynoEAStream": b"meta",
    }
    assert not list(series.rglob("@eaDir"))
    again = _preview(client, settings, series)
    assert again["summary"]["ready_count"] == again["summary"]["blocked_count"] == 0, again


def test_named_episode_buckets_its_supplements_and_keeps_nested_episodes(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    series = settings.data_mount / "Else/2609/260918/作者/老合集"
    work = series / "作者原创第10弹：海边"
    put_files(work, {"film.mp4": b"film", "解说/image.png": b"pic", "4.22-4.24聊天记录/card.jpg": b"chat"})
    put_files(series / "作者原创第11弹：城市", {"001.mp4": b"peer"})
    nested = series / "作者原创第20弹：冬日" / "作者原创第21弹：山景"
    put_files(nested, {"001.mp4": b"different episode"})

    preview = _preview(client, settings, series)
    ready, = [row for row in preview["units"] if row["status"] == "ready"]
    assert ready["unit"] == str(work)
    assert [group["name"] for group in ready["groups"]] == ["P [2 7B]", "V [1 4B]"]
    assert _execute(client, settings, preview)["success_count"] == 1
    assert (nested / "001.mp4").read_bytes() == b"different episode"
    assert (work / "P [2 7B]/001.jpg").read_bytes() == b"chat"
    assert (work / "P [2 7B]/002.png").read_bytes() == b"pic"
    assert (work / "V [1 4B]/001.mp4").read_bytes() == b"film"
    assert not (work / "解说").exists()
    assert _preview(client, settings, series)["summary"]["ready_count"] == 0


@pytest.mark.parametrize("boundary", ["standalone name", "version", "different episode", "dated archive"])
def test_episode_root_rule_preserves_independent_boundaries(tmp_path, boundary):
    series = tmp_path / "Else/2609/作者/合集"
    work = series / "14弹-海边"
    put_files(work, {"@eaDir/旧照片.jpg/预览.jpg": b"pic"})
    if boundary != "standalone name":
        put_files(series / "15弹-城市", {"001.mp4": b"peer"})
        folder = {"version": "4K", "different episode": "16弹-山景", "dated archive": "2025.03"}[boundary]
        put_files(work / folder, {"001.mp4": b"separate"})
    rows = list(iter_organizing_previews(series, allowed_roots=[tmp_path], include_mapping=True))
    assert all(Path(row["unit"]) != work for row in rows)


def test_episode_preview_is_revalidated_when_an_independent_episode_appears(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    series = settings.data_mount / "Else/2609/260918/作者/合集"
    work = series / "14弹-海边"
    put_files(work, {"@eaDir/旧照片.jpg/预览.jpg": b"pic"})
    put_files(series / "15弹-城市", {"001.mp4": b"peer"})
    preview = _preview(client, settings, work)
    assert preview["summary"]["ready_count"] == 1
    put_files(work / "16弹-山景", {"001.mp4": b"separate"})

    assert _execute(client, settings, preview)["conflict_count"] == 1
    assert (work / "@eaDir/旧照片.jpg/预览.jpg").read_bytes() == b"pic"
    assert (work / "16弹-山景/001.mp4").read_bytes() == b"separate"
