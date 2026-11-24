"""Fantia wrapper ownership through the recursive preview and execution entry points."""
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import iter_organizing_previews
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_organizer_planner import put
from tests.test_media_package_execute_jobs import _fixture


@pytest.mark.parametrize("collection_name", [
    "相册 Fantia06月订阅", "Fantia7月 会员合集", "相册 Fantia1800日圓訂閱",
    "Fantia350日圆 会员", "Fantia500日元 会员",
])
def test_adjacent_fantia_month_or_yen_still_groups_dated_posts(tmp_path, collection_name):
    collection = tmp_path / collection_name
    post = collection / "10_2225_夏日"
    put(post / "$0_/001.jpg", b"free")
    put(post / "$1800_/001.jpg", b"paid")
    put(collection / "P/001.jpg", b"independent")
    put(collection / "其他作品/$0_/001.jpg", b"independent-tier")

    rows = {row["unit"]: row for row in iter_organizing_previews(collection, allowed_roots=[tmp_path])}
    assert set(rows) == {str(post), str(collection), str(collection / "其他作品/$0_")}
    assert rows[str(post)]["status"] == "ready"
    assert {Path(move["target"]) for move in rows[str(post)]["sample_moves"]} == {
        post / "001.jpg", post / "002.jpg",
    }


@pytest.mark.parametrize("collection_name", [
    "FakeFantia06月", "Fantia13月", "Fantia00月", "Fantia2024", "Fantia9000GB",
    "Fantia100000日元", "Fantia1800日元12", "Fantia07月20日", "Fantia04月x",
])
def test_unrelated_adjacent_fantia_tokens_keep_tiers_separate(tmp_path, collection_name):
    post = tmp_path / collection_name / "10_2225_夏日"
    put(post / "$0_/001.jpg")
    put(post / "$1800_/001.jpg")

    rows = list(iter_organizing_previews(post.parent, allowed_roots=[tmp_path]))
    assert {row["unit"] for row in rows} == {str(post / "$0_"), str(post / "$1800_")}


@pytest.mark.parametrize(("relative", "sources", "expected"), [
    ("合集 Fantia06月订阅/10_2225_夏日", {
        "$0_/001.jpg": b"free", "$1800_/001.jpg": b"paid",
    }, {"001.jpg": b"free", "002.jpg": b"paid"}),
    ("Fantia 合集/1130 夏の花", {
        "P [1 4B]/001.jpg": b"main", "V [1 4B]/001.mp4": b"clip", "夏の花_/001.jpg": b"more",
    }, {"P [2 8B]/001.jpg": b"main", "P [2 8B]/002.jpg": b"more", "V [1 4B]/001.mp4": b"clip"}),
    ("Fantia 合集/7654321", {
        "作品/001.jpg": b"main", "作品_2/001.jpg": b"more",
    }, {"001.jpg": b"main", "002.jpg": b"more"}),
    ("Fantia 合集/7654321", {
        "作品/001.jpg": b"main", "作品_2/001.jpg": b"more", "001.mp4": b"clip",
    }, {"P [2 8B]/001.jpg": b"main", "P [2 8B]/002.jpg": b"more", "V [1 4B]/001.mp4": b"clip"}),
])
def test_fantia_wrappers_execute_once_with_independent_sibling(tmp_path, relative, sources, expected):
    client, settings, _ = _fixture(tmp_path)
    post = settings.data_mount / relative
    for path, content in sources.items():
        put(post / path, content)
    put(post.parent / "7654322/另一帖子/001.jpg", b"other")

    preview = _preview(client, settings, post.parent)
    assert [(row["unit"], row["status"]) for row in preview["units"] if row["status"] != "already_organized"] == [
        (str(post), "ready"),
    ]
    job = _batch(client, preview)
    assert _run_next(settings, job)
    result = client.get(f"/api/media-organizer/batches/{job}").json()
    assert result["summary"] == {"success_count": 1, "skipped_count": 1, "conflict_count": 0, "failed_count": 0}
    assert {p.relative_to(post).as_posix(): p.read_bytes() for p in post.rglob("*") if p.is_file()} == expected
    assert (post.parent / "7654322/另一帖子/001.jpg").read_bytes() == b"other"
    assert all(not (post / Path(source).parent).exists() for source in sources
               if Path(source).parent not in {Path(path).parent for path in expected} | {Path(".")})
    again = _preview(client, settings, post.parent)
    assert {(row["unit"], row["status"]) for row in again["units"]} == {
        (str(post), "already_organized"), (str(post.parent / "7654322/另一帖子"), "already_organized"),
    }


@pytest.mark.parametrize(("relative", "sources"), [
    ("作品合集/7654321", ["作品/001.jpg", "作品_2/001.jpg"]),
    ("Fantia 合集/654321", ["作品/001.jpg", "作品_2/001.jpg"]),
    ("Fantia 合集/7654321/7654322", ["作品/001.jpg", "作品_2/001.jpg"]),
    ("Fantia 合集/7654321", ["作品/001.jpg", "另一作品_2/001.jpg"]),
    ("Fantia 合集/7654321", ["作品/001.jpg", "作品_2/001.jpg", "作品_3/001.jpg"]),
    ("Fantia 合集/7654321", ["作品/001.jpg", "作品_2/001.jpg", "001.jpg"]),
    ("Fantia 合集/7654321", ["作品/001.jpg", "作品_2/001.mp4"]),
    ("Fantia 合集/7654321", ["作品/001.jpg", "作品_2/P [1 4B]/001.jpg"]),
    ("Fantia 合集/7654321", ["原图无水印/001.jpg", "原图无水印_2/001.jpg"]),
    ("Fantia 合集/20221130 夏の花", ["夏の花_/001.jpg", "001.mp4"]),
    ("Fantia 合集/20221130 夏の花", ["夏の花/001.jpg", "P [1 4B]/001.jpg"]),
    ("Fantia 合集/20221130 夏の花", ["夏の花_/001.jpg", "P [1 9B]/001.jpg"]),
    ("Fantia 合集/20221130 夏の花", ["夏の花_/001.jpg", "夏の花__/001.jpg", "P [1 4B]/001.jpg"]),
    ("Fantia 合集/20221130 夏の花", ["夏の花_/P [1 4B]/001.jpg", "P [1 4B]/001.jpg"]),
    ("Fantia 合集/20221130 夏の花", ["夏の花_/001.mp4", "P [1 4B]/001.jpg"]),
    ("Fantia 合集/20221130 原图无水印", ["原图无水印_/001.jpg", "P [1 4B]/001.jpg"]),
])
def test_uncertain_fantia_title_or_id_structure_does_not_claim_its_children(tmp_path, relative, sources):
    post = tmp_path / relative
    for source in sources:
        put(post / source)
    for row in iter_organizing_previews(post, allowed_roots=[tmp_path], include_mapping=True):
        for move in row.get("_mapping_items", []):
            source = Path(move["source"])
            target = Path(move["target"])
            source_layer = source.relative_to(post).parts[0]
            if source.parent != post and not source_layer.startswith("P ["):
                assert target.is_relative_to(post / source_layer)


@pytest.mark.parametrize(("relative", "sources", "late_file"), [
    ("Fantia 合集/7654321", ("作品/001.jpg", "作品_2/001.jpg"), "另一作品/001.jpg"),
    ("Fantia 合集/1130 夏の花", ("P [1 4B]/001.jpg", "夏の花_/001.jpg"), "夏の花_/001.mp4"),
    ("相册 Fantia06月订阅/1130 夏の花", ("$0_/001.jpg", "$1800_/001.jpg"), "另一帖子/001.jpg"),
])
def test_fantia_ownership_change_rejects_an_existing_preview(tmp_path, relative, sources, late_file):
    client, settings, _ = _fixture(tmp_path)
    post = settings.data_mount / relative
    for source in sources:
        put(post / source)
    preview = _preview(client, settings, post)
    assert preview["summary"]["ready_count"] == 1
    put(post / late_file, b"late")

    job = _batch(client, preview)
    assert _run_next(settings, job)
    result = client.get(f"/api/media-organizer/batches/{job}").json()
    assert result["summary"]["conflict_count"] == 1
    assert {p.relative_to(post).as_posix(): p.read_bytes() for p in post.rglob("*") if p.is_file()} == {
        **dict.fromkeys(sources, b"data"), late_file: b"late",
    }
