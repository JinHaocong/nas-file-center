"""Keep verified supplemental photos within their own titled work."""

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


@pytest.mark.parametrize("label", ["私訊", "私讯解锁", "私訊解鎖"])
def test_private_message_photos_follow_the_exact_declared_work_count(tmp_path, label):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2609/260917/作者/网盘"
    work = scope / "NO.015 海边 [3P 1.2GB]"
    put_files(work, {"001.jpg": b"base", f"{label}/001.jpg": b"extra", f"{label}/002.png": b"last"})
    sibling = scope / "NO.016 海边 2 [1P]"
    put_files(sibling, {"001.jpg": b"other work"})

    preview = _preview(client, settings, scope)
    row, = [item for item in preview["units"] if item["status"] == "ready"]
    assert row["unit"] == str(work) and row["groups"] == [], preview
    assert row["totals"] == {"P": 3, "V": 0, "Other": 0}
    assert _execute(client, settings, preview)["success_count"] == 1
    assert {p.name: p.read_bytes() for p in work.iterdir()} == {
        "001.jpg": b"base", "002.jpg": b"extra", "003.png": b"last",
    }
    assert (sibling / "001.jpg").read_bytes() == b"other work"
    assert _preview(client, settings, scope)["summary"]["ready_count"] == 0


def test_counted_cover_photos_join_existing_work_bucket_and_leave_video_mapping(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "Else/2609/260917/作者/NO.016 作品 [2P1V-1.1GB]"
    put_files(work, {"P [1 5B]/001.JPG": b"photo", "V [1 4B]/001.mp4": b"film", "封面圖/001.png": b"cover"})
    preview = _preview(client, settings, work)
    row, = [item for item in preview["units"] if item["status"] == "ready"]
    assert row["unit"] == str(work)
    assert [bucket["name"] for bucket in row["groups"]] == ["P [2 10B]", "V [1 4B]"]
    video, = [move for move in row["sample_moves"] if move["kind"] == "V"]
    assert video["source"] == video["target"] == str(work / "V [1 4B]/001.mp4")

    assert _execute(client, settings, preview)["success_count"] == 1
    assert (work / "P [2 10B]/001.JPG").read_bytes() == b"photo"
    assert (work / "P [2 10B]/002.png").read_bytes() == b"cover"
    assert (work / "V [1 4B]/001.mp4").read_bytes() == b"film"
    assert not (work / "封面圖").exists()
    assert _preview(client, settings, work)["summary"]["ready_count"] == 0


@pytest.mark.parametrize("label", ["私讯解锁", "私訊解鎖"])
def test_counted_unlock_lifts_photos_and_video_to_the_work_root(tmp_path, label):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2609/260917/作者/网盘"
    work = scope / "NO.122 同一作品 [2P1V 211MB]"
    put_files(work, {
        "001.jpg": b"base",
        f"{label}/P [1 5B]/001.png": b"extra",
        f"{label}/V [1 4B]/001.mp4": b"film",
    })

    preview = _preview(client, settings, scope)
    assert preview["summary"]["ready_count"] == 1 and preview["summary"]["blocked_count"] == 0, preview
    row, = [item for item in preview["units"] if item["status"] == "ready"]
    assert row["unit"] == str(work)
    assert [bucket["name"] for bucket in row["groups"]] == ["P [2 9B]", "V [1 4B]"]
    assert _execute(client, settings, preview)["success_count"] == 1
    assert {p.relative_to(work).as_posix(): p.read_bytes() for p in work.rglob("*") if p.is_file()} == {
        "P [2 9B]/001.jpg": b"base", "P [2 9B]/002.png": b"extra", "V [1 4B]/001.mp4": b"film",
    }
    assert not (work / label).exists()
    fresh = _preview(client, settings, scope)
    assert fresh["summary"]["ready_count"] == fresh["summary"]["blocked_count"] == 0


@pytest.mark.parametrize(("label", "total", "extra"), [
    ("私訊解鎖", "3P1V", {}),
    ("封面圖", "2P1V", {}),
    ("私訊解鎖", "3P1V", {"原圖無水印/001.jpg": b"variant"}),
])
def test_mixed_supplements_require_one_unlock_branch_and_matching_counts(tmp_path, label, total, extra):
    work = tmp_path / "2609/260917/作者/网盘" / f"NO.122 同一作品 [{total}]"
    put_files(work, {"001.jpg": b"base", f"{label}/001.png": b"extra", f"{label}/001.mp4": b"film", **extra})

    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True))
    assert not any(Path(row["unit"]) == work and row["status"] == "ready" for row in rows)


@pytest.mark.parametrize(("title", "extra"), [
    ("NO.016 作品", {}),
    ("NO.016 作品 [3P 1GB]", {}),
    ("NO.016 作品 [2P1V 1GB]", {}),
    ("NO.016 作品 [2P] [2P 1GB]", {}),
    ("NO.016 作品 [2P1V 1GB]", {"4K/001.mp4": b"version"}),
    ("NO.016 作品 [2P1V 1GB]", {"私訊/001.mp4": b"unsupported role"}),
])
def test_supplemental_photo_rule_preserves_ambiguous_or_mismatching_works(tmp_path, title, extra):
    work = tmp_path / "2609/260917/作者/网盘" / title
    put_files(work, {"001.jpg": b"base", "私訊/001.jpg": b"extra", **extra})
    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True))
    assert any(row["unit"] == str(work / "私訊") for row in rows)
    assert not any(row["status"] == "ready" and Path(row["unit"]) == work for row in rows)


def test_supplemental_count_is_rechecked_after_confirmation(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "Else/2609/260917/作者/NO.016 海边 [2P]"
    put_files(work, {"001.jpg": b"base", "私訊/001.jpg": b"extra"})
    preview = _preview(client, settings, work)
    assert preview["summary"]["ready_count"] == 1
    put_files(work, {"私訊/后来增加的照片.jpg": b"new"})

    assert _execute(client, settings, preview)["conflict_count"] == 1
    assert (work / "私訊/001.jpg").read_bytes() == b"extra"
    assert not (work / "002.jpg").exists()
