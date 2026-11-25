"""Verify numbered media packages and volumes containing named packs."""

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


def test_numbered_package_accepts_a_verified_legacy_p_and_v_pair(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "Else/2609/260904/作者/归档"
    package = archive / "1"
    put_files(package, {"P/image.jpg": b"photo", "V/clip.mp4": b"film"})
    put_files(archive / "2", {"001.mp4": b"separate", "命名作品/001.mp4": b"other"})

    preview = _preview(client, settings, archive)
    assert preview["summary"]["ready_count"] == 1 and preview["summary"]["blocked_count"] == 0, preview
    row, = [item for item in preview["units"] if item["status"] == "ready"]
    assert row["unit"] == str(package)
    assert [bucket["name"] for bucket in row["groups"]] == ["P [1 5B]", "V [1 4B]"]

    assert _execute(client, settings, preview)["success_count"] == 1
    assert (package / "P [1 5B]/001.jpg").read_bytes() == b"photo"
    assert (package / "V [1 4B]/001.mp4").read_bytes() == b"film"
    assert set(path.name for path in package.iterdir()) == {"P [1 5B]", "V [1 4B]"}
    assert (archive / "2/命名作品/001.mp4").read_bytes() == b"other"
    fresh = _preview(client, settings, archive)
    assert fresh["summary"]["ready_count"] == fresh["summary"]["blocked_count"] == 0, fresh


@pytest.mark.parametrize("boundary", ["wrong kind", "another work", "no ordinal peer"])
def test_legacy_p_and_v_pair_needs_a_complete_numbered_package_shape(tmp_path, boundary):
    archive = tmp_path / "Else/2609/260904/作者/归档"
    package = archive / "1"
    photo = "P/cover.mp4" if boundary == "wrong kind" else "P/cover.jpg"
    put_files(package, {photo: b"photo", "V/clip.mp4": b"video"})
    if boundary != "no ordinal peer":
        put_files(archive / "2", {"001.mp4": b"peer"})
    if boundary == "another work":
        put_files(package, {"独立作品/001.mp4": b"other"})

    rows = list(iter_organizing_previews(archive, allowed_roots=[tmp_path], include_mapping=True))
    assert any(row["unit"] == str(package) and row["status"] == "blocked" for row in rows)


def test_named_packs_can_stay_independent_inside_a_numbered_volume_with_named_peers(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "Else/2609/260930/作者/网盘"
    volume = archive / "01"
    packs = {"Series - Pack（1）": {"cover.jpg": b"photo", "clip.mp4": b"film"},
             "Series - Pack (3)": {"clip.mov": b"other"}}
    for title, files in packs.items():
        put_files(volume / title, files)
    for name in ("02", "2025", "4K", "命名档"):
        put_files(archive / name, {"001.mp4": b"untouched"})

    preview = _preview(client, settings, archive)
    assert preview["summary"]["ready_count"] == 2 and preview["summary"]["blocked_count"] == 0, preview
    assert {row["unit"] for row in preview["units"] if row["status"] == "ready"} == {
        str(volume / pack) for pack in packs
    }
    assert all(row["unit"] != str(volume) for row in preview["units"])

    assert _execute(client, settings, preview)["success_count"] == 2
    assert set(path.name for path in volume.iterdir()) == packs.keys()
    assert (volume / "Series - Pack（1）/P [1 5B]/001.jpg").read_bytes() == b"photo"
    assert (volume / "Series - Pack（1）/V [1 4B]/001.mp4").read_bytes() == b"film"
    assert (volume / "Series - Pack (3)/001.mov").read_bytes() == b"other"
    assert (archive / "4K/001.mp4").read_bytes() == b"untouched"
    fresh = _preview(client, settings, archive)
    assert fresh["summary"]["ready_count"] == fresh["summary"]["blocked_count"] == 0, fresh


@pytest.mark.parametrize("boundary", ["no ordinal peer", "duplicate ordinal", "different series", "non-media leaf"])
def test_named_pack_volume_does_not_claim_ambiguous_numbered_folders(tmp_path, boundary):
    archive = tmp_path / "Else/2609/260930/作者/网盘"
    volume = archive / "01"
    second = {"duplicate ordinal": "Series - Pack (01)", "different series": "Another - Pack (3)"}.get(
        boundary, "Series - Pack (3)")
    put_files(volume / "Series - Pack（1）", {"001.mp4": b"first"})
    put_files(volume / second, {"notes.txt" if boundary == "non-media leaf" else "001.mov": b"second"})
    put_files(archive / "2025", {"001.mp4": b"independent"})
    if boundary != "no ordinal peer":
        put_files(archive / "02", {"001.mp4": b"peer"})

    rows = list(iter_organizing_previews(archive, allowed_roots=[tmp_path], include_mapping=True))
    assert any(row["unit"] == str(volume) and row["status"] == "blocked" for row in rows)
