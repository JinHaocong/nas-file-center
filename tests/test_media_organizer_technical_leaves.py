"""Regression coverage for validated media leaves."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.batch.media_organizer_planner import iter_organizing_previews
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture


def put(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")


def previews(scope: Path, root: Path, **options) -> dict[Path, dict]:
    return {
        Path(row["unit"]): row
        for row in iter_organizing_previews(scope, allowed_roots=[root], include_mapping=True, **options)
    }


@pytest.mark.parametrize("mode", ["semantic", "luolcy"])
def test_jfif_in_an_old_other_bucket_returns_to_its_own_work(tmp_path, mode):
    client, settings, root = _fixture(tmp_path)
    if mode == "luolcy":
        scope = root / "2611/261115/作者"
        work = scope / "6.7G"
        sibling = scope / "另一资源包/001.mp4"
    else:
        scope = settings.data_mount / "Else/作品"
        work = scope / "原图无水印"
        sibling = scope / "001.mp4"

    # JPEG payloads with different colors make it possible to verify file ownership after execution.
    payloads = []
    for color in ("red", "navy"):
        with BytesIO() as output:
            Image.new("RGB", (2, 2), color).save(output, format="JPEG")
            payloads.append(output.getvalue())
    original_jpeg, misclassified_jfif = payloads
    bucket = work / f"Other [1 {len(misclassified_jfif)}B]"
    source = bucket / "original.JfIf"
    photo = work / f"P [1 {len(original_jpeg)}B]/001.jpg"
    for path, payload in ((source, misclassified_jfif), (photo, original_jpeg), (sibling, b"video")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    preview = _preview(client, settings, scope)
    row, = (unit for unit in preview["units"] if unit["unit"] == str(work))
    assert row["status"] == "ready"
    assert row["totals"] == {"P": 2, "V": 0, "Other": 0}
    move, = (move for move in row["sample_moves"] if move["source"] == str(source))
    assert (move["kind"], move["target"]) == ("P", str(work / "001.JfIf"))
    assert source.read_bytes() == misclassified_jfif

    assert _run_next(settings, _batch(client, preview))
    assert {path.name: path.read_bytes() for path in work.iterdir()} == {
        "001.JfIf": misclassified_jfif, "002.jpg": original_jpeg,
    }
    assert sibling.read_bytes() == b"video"
    assert _preview(client, settings, scope)["summary"]["ready_count"] == 0


@pytest.mark.parametrize(("folder", "photos", "videos", "group_counts"), [
    ("JpG", 456, 0, [200, 200, 56]),
    ("jPeG", 1202, 2, [200, 200, 200, 200, 200, 200, 2, 2]),
])
def test_jpeg_wrapper_is_bucketed_at_its_work_with_original_extensions(tmp_path, folder, photos, videos, group_counts):
    media_label = f"{photos}P {videos}V" if videos else f"{photos}P"
    work = tmp_path / f"下载标题 [{media_label}]"
    wrapper = work / folder
    for index in range(photos):
        extension = ".JPG" if index % 2 else ".JpEg"
        put(wrapper / f"photo-{index:04d}{extension}")
    for index in range(videos):
        put(work / f"clip-{index}.MP4")

    rows = previews(work, tmp_path)

    assert set(rows) == {work}
    row = rows[work]
    assert row["status"] == "ready"
    assert row["totals"] == {"P": photos, "V": videos, "Other": 0}
    assert [group["count"] for group in row["groups"]] == group_counts
    assert row["wrapper_cleanup"] == [str(wrapper)]
    assert len(row["_mapping_items"]) == photos + videos
    assert all(Path(move["target"]).suffix == Path(move["source"]).suffix for move in row["_mapping_items"])


def test_jpeg_wrapper_accepts_verified_photo_buckets(tmp_path):
    work = tmp_path / "作品"
    wrapper = work / "JPEG"
    photo = wrapper / "P [1 4B]/001.JPEG"
    put(photo)
    put(work / "clip.mp4")

    rows = previews(work, tmp_path)

    assert set(rows) == {work}
    assert rows[work]["wrapper_cleanup"] == [str(photo.parent), str(wrapper)]
    assert {move["source"]: move["target"] for move in rows[work]["_mapping_items"]} == {
        str(photo): str(work / "P [1 4B]/001.JPEG"),
        str(work / "clip.mp4"): str(work / "V [1 4B]/001.mp4"),
    }


@pytest.mark.parametrize("boundary", [
    "PNG", "video", "edition", "unverified-bucket", "protected-bucket",
    "author", "date", "short-date", "version",
])
def test_jpeg_label_keeps_unverified_or_separate_contents_within_their_own_boundary(tmp_path, boundary):
    work = tmp_path / {
        "author": "261123/作者A",
        "date": "261123",
        "short-date": "11月19日",
        "version": "作品/修复版",
    }.get(boundary, "作品 [2P 1V]")
    wrapper = work / "JPEG"
    put(work / "clip.mp4")
    put(wrapper / "cover.JPG")
    extra = {
        "PNG": "second.png",
        "video": "second.mp4",
        "edition": "修复版/second.jpg",
        "unverified-bucket": "P [2 4B]/001.jpg",
        "protected-bucket": "P [1 4B]/001.jpg",
    }.get(boundary)
    if extra:
        put(wrapper / extra)
    quarantine = wrapper / "P [1 4B]" if boundary == "protected-bucket" else None

    rows = previews(work, tmp_path, quarantine_root=quarantine)

    assert work in rows and wrapper in rows
    assert rows[work]["totals"] == {"P": 0, "V": 1, "Other": 0}
    assert all(
        Path(move["source"]).is_relative_to(wrapper) == Path(move["target"]).is_relative_to(wrapper)
        for row in rows.values() for move in row.get("_mapping_items", ())
    )


@pytest.mark.parametrize("name", ["新建文件夹", "新建文件夹 (2)"])
def test_default_named_mixed_leaf_is_independent_and_its_buckets_rescan(tmp_path, name):
    parent = tmp_path / "作者A"
    folder = parent / name
    put(folder / "cover.JPG")
    put(folder / "clip.mp4")
    put(parent / "作品A/poster.png")

    rows = previews(parent, tmp_path)

    assert set(rows) == {folder, parent / "作品A"}
    assert rows[folder]["status"] == "ready"
    assert {Path(move["target"]).relative_to(folder).as_posix() for move in rows[folder]["_mapping_items"]} == {
        "P [1 4B]/001.JPG", "V [1 4B]/001.mp4",
    }
    for move in rows[folder]["_mapping_items"]:
        target = Path(move["target"])
        target.parent.mkdir()
        Path(move["source"]).rename(target)

    row = previews(parent, tmp_path)[folder]
    assert (row["status"], row["actual_moves"]) == ("already_organized", 0)


@pytest.mark.parametrize("extra", ["作品/cover.png", "readme.txt", "P [1 4B]/001.png"])
def test_default_named_mixed_leaf_keeps_ambiguous_contents_held(tmp_path, extra):
    folder = tmp_path / "新建文件夹"
    put(folder / "clip.mp4")
    put(folder / "cover.jpg")
    put(folder / extra)

    assert previews(tmp_path, tmp_path)[folder]["status"] == "blocked"


def test_default_named_mixed_buckets_cannot_use_a_protected_bucket_as_evidence(tmp_path):
    folder = tmp_path / "新建文件夹"
    protected = folder / "P [1 4B]"
    put(protected / "001.jpg")
    put(folder / "V [1 4B]/001.mp4")

    rows = previews(tmp_path, tmp_path, quarantine_root=protected)

    assert rows[folder]["status"] == "blocked"
    assert protected not in rows


def test_continuous_numbered_leaf_is_independently_verified_among_uncertain_volumes(tmp_path):
    series = tmp_path / "旧下载"
    put(series / "1/cover.jpg")
    put(series / "02/修复版/clip.mp4")
    put(series / "02/loose.mp4")
    put(series / "3/still.webp")
    put(series / "3/clip.mp4")
    put(series / "4/cover.jpg")
    put(series / "4/readme.txt")
    put(series / "5/作品 VOL.05/poster.jpg")

    rows = previews(series, tmp_path)

    assert rows[series / "1"]["status"] == rows[series / "3"]["status"] == "ready"
    assert rows[series / "02"]["status"] == rows[series / "4"]["status"] == "blocked"
    assert rows[series / "02/修复版"]["status"] == rows[series / "5/作品 VOL.05"]["status"] == "ready"
    assert series / "5" not in rows
    for leaf in (series / "1", series / "3"):
        assert all(Path(move["target"]).is_relative_to(leaf) for move in rows[leaf]["_mapping_items"])


@pytest.mark.parametrize("name", ["旧下载", "两卷合集"])
def test_gapped_series_with_an_uncertain_volume_leaves_both_volumes_held(tmp_path, name):
    series = tmp_path / name
    put(series / "01/cover.jpg")
    put(series / "03/修复版/clip.mp4")

    rows = previews(series, tmp_path)

    assert rows[series / "01"]["status"] == rows[series / "03"]["status"] == "blocked"


def test_explicit_collection_with_verified_gapped_leaves_remains_supported(tmp_path):
    series = tmp_path / "两卷合集"
    put(series / "01/cover.jpg")
    put(series / "03/clip.mp4")

    rows = previews(series, tmp_path)

    assert set(rows) == {series / "01", series / "03"}
    assert all(row["status"] == "ready" for row in rows.values())
