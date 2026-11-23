"""V1.6 media rules tested through the read-only preview boundary."""
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import iter_organizing_previews, preview_organizing_unit


def put(path: Path, content: bytes = b"data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@pytest.mark.parametrize(("root_name", "child", "paths"), [
    ("002.mp4", "#AKS 标题", ("001.mp4",)),
    ("001.mp4", "#AKS 标题", ("001.mp4", "002.mp4")),
    ("001.mp4", "#AKS 标题", ("001.jpg",)),
    ("001.mp4", "#AKS 标题", ("版本/001.mp4",)),
    ("001.mp4", "261119", ("001.mp4",)),
    ("001.mp4", "11.19", ("001.mp4",)),
    ("001.mp4", "11月19日", ("001.mp4",)),
    ("001.mp4", "11 月 19 日", ("001.mp4",)),
    ("001.mp4", "11月", ("001.mp4",)),
    ("001.mp4", "2026-1", ("001.mp4",)),
    ("001.mp4", "2026-1-2", ("001.mp4",)),
    ("001.mp4", "1119", ("001.mp4",)),
    ("001.mp4", "4K", ("001.mp4",)),
    ("001.mp4", "NO.017", ("001.mp4",)),
    ("001.mp4", "MOVIE", ("001.mp4",)),
    ("001.mp4", "Fantia", ("001.mp4",)),
])
def test_single_video_append_requires_a_numbered_root_and_an_eligible_one_video_leaf(
    tmp_path, root_name, child, paths,
):
    author = tmp_path / "2611/261123/AKS"
    put(author / root_name)
    for relative in paths:
        put(author / child / relative)

    rows = list(iter_organizing_previews(author.parent, allowed_roots=[tmp_path], include_mapping=True))

    assert all(row.get("operation") != "append_single_video" for row in rows)
    assert all(Path(move["source"]).is_relative_to(author / child)
               == Path(move["target"]).is_relative_to(author / child)
               for row in rows for move in row.get("_mapping_items", []))


@pytest.mark.parametrize("directory", ["Fantia", "11.19", "11月"])
def test_single_video_append_does_not_treat_collection_or_date_names_as_authors(tmp_path, directory):
    collection = tmp_path / "2611/261123" / directory
    put(collection / "001.mp4")
    put(collection / "标题帖子/001.mp4")

    rows = list(iter_organizing_previews(collection.parent, allowed_roots=[tmp_path]))

    assert {(row["unit"], row["status"]) for row in rows} == {
        (str(collection), "already_organized"),
        (str(collection / "标题帖子"), "already_organized"),
    }


@pytest.mark.parametrize(("folder", "extra"), [
    ("xkatz", "002.mp4"),
    ("xkatt", "cover.jpg"),
    ("xkatt", "2026-01-01/002.mp4"),
])
def test_multi_video_append_requires_matching_initials_and_a_pure_leaf(tmp_path, folder, extra):
    author = tmp_path / "2611/261120/小可爱甜甜"
    child = author / folder
    put(author / "001.mp4")
    put(child / "001.mp4")
    put(child / extra)

    rows = list(iter_organizing_previews(author, allowed_roots=[tmp_path], include_mapping=True))

    assert all(row.get("operation") != "append_author_videos" for row in rows)
    assert all(Path(move["source"]).is_relative_to(child) == Path(move["target"]).is_relative_to(child)
               for row in rows for move in row.get("_mapping_items", []))


@pytest.mark.parametrize("exception_path", ["1/作品/cover.jpg", "02/clip.mp4", "1/作品/notes.txt"])
def test_whole_author_rule_keeps_separate_units_when_its_narrow_shape_changes(tmp_path, exception_path):
    author = tmp_path / "2611/261123/作者A"
    put(author / "root.mp4")
    put(author / "1/clip.mp4")
    put(author / "1/作品/nested.mp4")
    put(author / exception_path)

    rows = {row["unit"]: row for row in iter_organizing_previews(author.parent, allowed_roots=[tmp_path])}

    assert rows[str(author)]["totals"] == {"P": 0, "V": 1, "Other": 0}
    assert rows[str(author / "1")]["status"] == "blocked"
    assert str(author / "1/作品") in rows


@pytest.mark.parametrize("symlinked", [False, True])
def test_whole_author_rule_never_absorbs_a_protected_branch(tmp_path, symlinked):
    author = tmp_path / "2611/261123/作者A"
    protected = author / "1/作品"
    put(author / "root.mp4")
    put(author / "1/clip.mp4")
    put(protected / "nested.mp4")
    quarantine_root = protected
    if symlinked:
        quarantine_root = tmp_path / "configured-quarantine"
        quarantine_root.symlink_to(protected, target_is_directory=True)

    rows = {row["unit"]: row for row in iter_organizing_previews(
        author.parent, allowed_roots=[tmp_path], quarantine_root=quarantine_root, include_mapping=True,
    )}

    assert rows[str(author)]["totals"] == {"P": 0, "V": 1, "Other": 0}
    assert rows[str(author / "1")]["status"] == "blocked"
    assert all(not Path(move["source"]).is_relative_to(protected)
               for row in rows.values() if row["status"] == "ready" for move in row["_mapping_items"])


def test_whole_author_rule_preserves_a_held_photo_wrapper_scope(tmp_path):
    photos = tmp_path / "2611/261123/作者A/archive/2611/261123/photos"
    put(photos / "root.jpg")
    put(photos / "1/cover.jpg")
    put(photos / "1/作品/nested.jpg")

    rows = list(iter_organizing_previews(tmp_path, allowed_roots=[tmp_path], include_mapping=True))

    ready_sources = [move["source"] for row in rows if row["status"] == "ready" for move in row["_mapping_items"]]
    assert sorted(ready_sources) == sorted([str(photos / "root.jpg"), str(photos / "1/作品/nested.jpg")])


@pytest.mark.parametrize("occupied", [False, True])
def test_large_whole_author_uses_existing_bucket_limits_and_checks_targets(tmp_path, occupied):
    author = tmp_path / "2611/261123/作者A"
    put(author / "root.mp4")
    put(author / "1/clip.mp4")
    for index in range(198):
        put(author / "1/作品" / f"{index:03d}.mp4")
    bucket = author / "V [200 800B]"
    put(bucket / "video.mp4")
    if occupied:
        (bucket / "empty-folder").mkdir()

    rows = list(iter_organizing_previews(author, allowed_roots=[tmp_path]))

    assert [row["unit"] for row in rows] == [str(author)]
    if occupied:
        assert rows[0]["status"] == "blocked"
        assert rows[0]["reason"] == "A target media bucket contains a non-input directory"
    else:
        assert rows[0]["status"] == "ready"
        assert [group["name"] for group in rows[0]["groups"]] == ["V [200 800B]", "V_1 [1 4B]"]


def test_leaf_photo_pack_joins_its_works_direct_videos(tmp_path):
    work = tmp_path / "圣诞雪饼带视频"
    put(work / "图包" / "cover.JPG")
    put(work / "clip.mp4")

    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True))

    assert [row["unit"] for row in rows] == [str(work)]
    assert [group["name"] for group in rows[0]["groups"]] == ["P [1 4B]", "V [1 4B]"]
    assert rows[0]["wrapper_cleanup"] == [str(work / "图包")]
    assert {item["target"] for item in rows[0]["_mapping_items"]} == {
        str(work / "P [1 4B]/001.JPG"), str(work / "V [1 4B]/001.mp4"),
    }


def test_photo_pack_only_is_flattened_but_nested_works_stay_separate(tmp_path):
    work = tmp_path / "作品A"
    mixed = tmp_path / "作品B" / "图包" / "NO.003"
    put(work / "图包" / "cover.jpg")
    put(mixed / "poster.webp")

    rows = {row["unit"]: row for row in iter_organizing_previews(tmp_path, allowed_roots=[tmp_path])}

    assert rows[str(work)]["sample_moves"][0]["target"] == str(work / "001.jpg")
    assert rows[str(mixed)]["sample_moves"][0]["target"] == str(mixed / "001.webp")


def test_photo_pack_at_author_level_stays_separate_when_named_works_are_present(tmp_path):
    author = tmp_path / "261103" / "作者A"
    pack = author / "图包"
    put(pack / "cover.jpg")
    put(author / "NO.001/cover.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(author, allowed_roots=[tmp_path])}

    assert str(author) not in rows
    assert rows[str(pack)]["sample_moves"][0]["target"] == str(pack / "001.jpg")


@pytest.mark.parametrize(("folder", "file"), [("MOVIE", "cover.jpg"), ("IMG", "clip.mp4"), ("gif", "cover.jpg")])
def test_alias_with_a_mismatched_file_type_keeps_its_own_unit(tmp_path, folder, file):
    work = tmp_path / "作者A/NO.185"
    leaf = work / folder
    put(work / "001.mp4")
    put(leaf / file)

    rows = {row["unit"]: row for row in iter_organizing_previews(work, allowed_roots=[tmp_path])}

    assert rows[str(work)]["status"] == "already_organized"
    assert rows[str(leaf)]["sample_moves"][0]["target"] == str(leaf / ("001" + Path(file).suffix))


def test_typed_media_label_at_author_level_remains_an_independent_unit(tmp_path):
    author = tmp_path / "2611/261104/作者A"
    put(author / "IMG/cover.jpg")
    put(author / "NO.022/photo.jpg")

    rows = list(iter_organizing_previews(author, allowed_roots=[tmp_path]))

    assert {row["unit"] for row in rows} == {str(author / "IMG"), str(author / "NO.022")}


def test_typed_media_label_is_still_discovered_inside_a_held_wrapper(tmp_path):
    mixed = tmp_path / "NO.123/photos"
    put(mixed / "root.jpg")
    put(mixed / "IMG/cover.jpg")
    put(mixed / "NO.124/photo.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        mixed.parent, allowed_roots=[tmp_path], include_mapping=True,
    )}

    assert rows[str(mixed)]["totals"] == {"P": 1, "V": 0, "Other": 0}
    assert rows[str(mixed / "IMG")]["sample_moves"][0]["target"] == str(mixed / "IMG/001.jpg")
    assert rows[str(mixed / "NO.124")]["sample_moves"][0]["target"] == str(mixed / "NO.124/001.jpg")


@pytest.mark.parametrize(("photo_post", "video_post"), [("P", "photos"), ("01", "261123")])
def test_fantia_posts_that_resemble_classification_labels_keep_their_boundaries(tmp_path, photo_post, video_post):
    collection = tmp_path / "Fantia 合集"
    photo = collection / photo_post / "$0_/cover.jpg"
    video = collection / video_post / "$1800_/clip.mp4"
    put(photo)
    put(video)

    rows = {row["unit"]: row for row in iter_organizing_previews(collection, allowed_roots=[tmp_path])}

    assert {path: row["sample_moves"][0]["target"] for path, row in rows.items()} == {
        str(collection / photo_post): str(collection / photo_post / "001.jpg"),
        str(collection / video_post): str(collection / video_post / "001.mp4"),
    }
    photo.rename(collection / photo_post / "001.jpg")
    video.rename(collection / video_post / "001.mp4")
    photo.parent.rmdir()
    video.parent.rmdir()
    again = list(iter_organizing_previews(collection, allowed_roots=[tmp_path]))
    assert {(row["unit"], row["status"]) for row in again} == {
        (str(collection / photo_post), "already_organized"),
        (str(collection / video_post), "already_organized"),
    }


@pytest.mark.parametrize(("collection", "extra"), [
    ("Fantia 合集", "$1800_/paid.jpg"),
    ("Fantia 合集", "root.jpg"),
    ("Fantia 合集", "$0_/mixed.mp4"),
    ("Fantia 合集", "$1800_🎬/clip.mp4"),
    ("Fantia 合集", "$0_🎬/cover.jpg"),
    ("百度网盘合集", None),
    ("NotFantiax 合集", None),
])
def test_tier_wrapper_keeps_its_unit_when_post_context_is_ambiguous(tmp_path, collection, extra):
    post = tmp_path / collection / "03_2026_帖子"
    tier = post / "$0_"
    put(tier / "cover.jpg")
    if extra is not None:
        put(post / extra)

    rows = {row["unit"]: row for row in iter_organizing_previews(post, allowed_roots=[tmp_path], include_mapping=True)}

    assert rows[str(tier)]["status"] == "ready"
    assert all(Path(move["target"]).is_relative_to(tier) for move in rows[str(tier)]["_mapping_items"])


@pytest.mark.parametrize("boundary", ["third-tier", "protected-video"])
def test_fantia_pair_keeps_independent_units_when_the_post_has_another_boundary(tmp_path, boundary):
    post = tmp_path / "Fantia 合集/帖子"
    put(post / "$1800_/cover.jpg")
    movie = post / "$1800_🎬"
    put(movie / "clip.mp4")
    quarantine_root = movie if boundary == "protected-video" else None
    if boundary == "third-tier":
        put(post / "$0_/free.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        post, allowed_roots=[tmp_path], quarantine_root=quarantine_root,
    )}

    assert str(post) not in rows
    assert rows[str(post / "$1800_")]["sample_moves"][0]["target"] == str(post / "$1800_/001.jpg")
    assert (str(movie) in rows) == (quarantine_root is None)


@pytest.mark.parametrize("boundary", ["missing-photo-bucket", "bad-photo-bucket", "mixed-selfies", "protected-bucket"])
def test_selfies_requires_an_available_photo_bucket_and_a_pure_photo_leaf(tmp_path, boundary):
    work = tmp_path / "作者A/NO.032"
    selfies = work / "Selfies"
    bucket = work / "P [1 4B]"
    put(selfies / "cover.jpg")
    put(work / "V [1 4B]/001.mp4")
    if boundary != "missing-photo-bucket":
        put(bucket / ("001.mp4" if boundary == "bad-photo-bucket" else "001.jpg"))
    if boundary == "mixed-selfies":
        put(selfies / "clip.mp4")
    quarantine_root = bucket if boundary == "protected-bucket" else None

    rows = {row["unit"]: row for row in iter_organizing_previews(
        work, allowed_roots=[tmp_path], quarantine_root=quarantine_root, include_mapping=True,
    )}

    assert str(selfies) in rows
    assert all(Path(move["target"]).is_relative_to(selfies)
               for move in rows[str(selfies)]["_mapping_items"])


def test_typed_leaf_does_not_absorb_a_symlinked_quarantine_root(tmp_path):
    work = tmp_path / "NO.017"
    protected = work / "MOVIE"
    put(work / "001.jpg")
    put(protected / "clip.mp4")
    quarantine_root = tmp_path / "configured-quarantine"
    quarantine_root.symlink_to(protected, target_is_directory=True)

    rows = list(iter_organizing_previews(
        work, allowed_roots=[tmp_path], quarantine_root=quarantine_root, include_mapping=True,
    ))

    assert [(row["unit"], row["status"], row["totals"]) for row in rows] == [
        (str(work), "already_organized", {"P": 1, "V": 0, "Other": 0}),
    ]


@pytest.mark.parametrize(("label", "child_name", "extra"), [
    ("作品 [2P1V]", "sp", None),
    ("作品 [1P1V] [2V]", "sp", None),
    ("作品 [1P1V] [3图]", "sp", None),
    ("作品 [1P1V] [3张]", "sp", None),
    ("作品 [3-1P1V]", "sp", None),
    ("作品 [3~1P1V]", "sp", None),
    ("作品 [1P1V]", "视频压缩版", None),
    ("作品 [1P1V]", "无修版", None),
    ("作品 [1P1V]", "导演剪辑版", None),
    ("作品 [1P1V]", "X-046-R16", None),
    ("作品 [1P1V]", "NO.002", None),
    ("作品 [1P1V]", "独立短片 1V", None),
    ("作品 [1P1V]", "短片Vol.02", None),
    ("作品 [1P1V]", "sp", "其他作品/cover.jpg"),
    ("作品 [1P1V]", "视图", "视图/4K/clip.mp4"),
])
def test_work_media_rules_preserve_unverified_counts_and_independent_boundaries(
    tmp_path, label, child_name, extra,
):
    work = tmp_path / label
    child = work / child_name
    put(work / "cover.jpg")
    put(child / "clip.mp4")
    if extra is not None:
        put(work / extra)

    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], include_mapping=True))

    assert all(Path(move["target"]).is_relative_to(child)
               for row in rows for move in row.get("_mapping_items", [])
               if Path(move["source"]).is_relative_to(child))
    assert {row["unit"] for row in rows} >= {str(work), str(child)}


def test_view_wrapper_does_not_adopt_a_mislabeled_bucket(tmp_path):
    work = tmp_path / "作品 [1P1V]"
    view = work / "视图"
    put(work / "cover.jpg")
    put(view / "V [99 假标签]/clip.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(work, allowed_roots=[tmp_path])}

    assert rows[str(work)]["totals"] == {"P": 1, "V": 0, "Other": 0}
    assert rows[str(view)]["totals"] == {"P": 0, "V": 1, "Other": 0}


def test_work_media_rule_preserves_the_date_and_recognizes_a_confirmed_work(tmp_path):
    date = tmp_path / "261123"
    work = date / "独立短片 [1P1V]"
    put(work / "cover.jpg")
    put(work / "sp/clip.mp4")

    rows = list(iter_organizing_previews(date, allowed_roots=[tmp_path]))

    assert [(row["unit"], row["totals"]) for row in rows] == [
        (str(work), {"P": 1, "V": 1, "Other": 0}),
    ]


def test_face_stays_separate_when_the_work_has_no_other_photos(tmp_path):
    work = tmp_path / "作品 [1P1V]"
    put(work / "clip.mp4")
    put(work / "face/cover.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(work, allowed_roots=[tmp_path])}

    assert rows[str(work)]["totals"] == {"P": 0, "V": 1, "Other": 0}
    assert rows[str(work / "face")]["sample_moves"][0]["target"] == str(work / "face/001.jpg")


def test_author_dated_batch_absorbs_categories_but_outer_calendar_keeps_author_names(tmp_path):
    day = tmp_path / "261103"
    batch = day / "作者A" / "261103"
    put(day / "图片" / "author-cover.jpg")
    put(batch / "图片" / "cover.jpg")
    put(batch / "视频" / "clip.mp4")
    put(batch.with_name("260321") / "sibling.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(day, allowed_roots=[tmp_path])}

    assert [group["name"] for group in rows[str(batch)]["groups"]] == ["P [1 4B]", "V [1 4B]"]
    assert rows[str(day / "图片")]["sample_moves"][0]["target"] == str(day / "图片/001.jpg")
    assert rows[str(batch.with_name("260321"))]["totals"] == {"P": 0, "V": 1, "Other": 0}


def test_same_name_work_promotes_typed_buckets_even_when_files_need_numbering(tmp_path):
    work = tmp_path / "作品A"
    inner = work / work.name
    put(inner / "P [1 4B]/001.jpg")
    put(inner / "V [1 4B]/001.MP4")
    unorganized = tmp_path / "作品B" / "作品B"
    put(unorganized / "P [1 4B]/cover.jpg")
    put(unorganized / "V [1 4B]/clip.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(tmp_path, allowed_roots=[tmp_path])}

    assert str(inner) not in rows
    assert rows[str(work)]["renamed_count"] == 0
    assert {move["target"] for move in rows[str(work)]["sample_moves"]} == {
        str(work / "P [1 4B]/001.jpg"), str(work / "V [1 4B]/001.MP4"),
    }
    assert str(unorganized) not in rows
    assert {move["target"] for move in rows[str(unorganized.parent)]["sample_moves"]} == {
        str(unorganized.parent / "P [1 4B]/001.jpg"),
        str(unorganized.parent / "V [1 4B]/001.mp4"),
    }


@pytest.mark.parametrize("boundary", ["261103", "11.06", "4K", "完整版"])
def test_same_name_work_does_not_collapse_calendar_or_version_layers(tmp_path, boundary):
    outer = tmp_path / "作品A" / boundary
    inner = outer / boundary
    put(inner / "P [1 4B]/001.jpg")
    put(inner / "V [1 4B]/001.MP4")

    rows = list(iter_organizing_previews(outer, allowed_roots=[tmp_path]))

    assert [(row["unit"], row["status"]) for row in rows] == [(str(inner), "already_organized")]


def test_recursive_preview_preserves_author_work_date_and_version_boundaries(tmp_path):
    collection = tmp_path / "library"
    expected = {
        "261001/AuthorA/NO.001": ("P1/a.JPG", "001.JPG"),
        "261001/AuthorB/NO.001": ("photos/a.jpg", "001.jpg"),
        "261015/AuthorA/NO.001/4K": ("Video/a.Mp4", "001.Mp4"),
        "261015/AuthorA/NO.001/PT": ("a.mp4", "001.mp4"),
    }
    for unit, (source, _) in expected.items():
        put(collection / unit / source)

    records = list(iter_organizing_previews(collection, allowed_roots=[tmp_path]))

    assert {Path(row["unit"]).relative_to(collection).as_posix() for row in records} == set(expected)
    for row in records:
        unit = Path(row["unit"])
        source, target = expected[unit.relative_to(collection).as_posix()]
        assert row["status"] == "ready"
        assert row["sample_moves"][0]["source"] == str(unit / source)
        assert row["sample_moves"][0]["target"] == str(unit / target)
        assert (unit / source).read_bytes() == b"data"


def test_author_loose_files_are_reported_separately_from_named_works(tmp_path):
    author = tmp_path / "2611" / "261122" / "作者A"
    photo_only_author = author.with_name("作者B")
    put(author / "随手拍.mp4")
    put(author / "散图.png")
    put(author / "NO.001" / "封面.jpg")
    put(photo_only_author / "P1" / "封面.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        author.parent, allowed_roots=[tmp_path],
    )}

    assert rows[str(author)]["status"] == "blocked"
    assert rows[str(author)]["reason"] == "作者层散文件待确认"
    assert rows[str(author)]["totals"] == {"P": 1, "V": 1, "Other": 0}
    assert rows[str(author / "NO.001")]["sample_moves"][0]["target"] == str(author / "NO.001/001.jpg")
    assert rows[str(photo_only_author)]["sample_moves"][0]["target"] == str(photo_only_author / "001.jpg")


def test_pure_author_layer_groups_only_its_direct_media(tmp_path):
    author = tmp_path / "2611" / "261122" / "作者A"
    for index in range(201):
        put(author / f"原视频-{index:03d}.mp4")
    put(author / "videos" / "旧素材.mp4")
    put(author / "NO.001" / "封面.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        author.parent, allowed_roots=[tmp_path], include_mapping=True,
    )}

    assert rows[str(author)]["status"] == "ready"
    assert [group["name"] for group in rows[str(author)]["groups"]] == ["V [200 800B]", "V_1 [1 4B]"]
    assert all(Path(move["source"]).parent == author for move in rows[str(author)]["_mapping_items"])
    assert rows[str(author / "NO.001")]["sample_moves"][0]["target"] == str(author / "NO.001/001.jpg")


def test_author_rescan_keeps_an_existing_canonical_photo_and_other_layout(tmp_path):
    author = tmp_path / "2611" / "261122" / "作者A"
    put(author / "P [1 4B]/001.jpg")
    put(author / "Other [1 4B]/notes.txt")
    put(author / "NO.001/001.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(author.parent, allowed_roots=[tmp_path])}

    assert rows[str(author)]["status"] == "already_organized"
    assert rows[str(author)]["totals"] == {"P": 1, "V": 0, "Other": 1}
    assert rows[str(author)]["actual_moves"] == 0


def test_grouped_author_rescan_keeps_other_and_excludes_unrelated_legacy_wrappers(tmp_path):
    author = tmp_path / "2611" / "261122" / "作者A"
    for index in range(1, 201):
        put(author / "V [200 800B]" / f"{index:03d}.mp4")
    put(author / "V_1 [1 4B]/001.mp4")
    put(author / "Other [1 4B]/notes.txt")
    put(author / "videos/旧素材.mp4")
    put(author / "NO.001/001.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(author.parent, allowed_roots=[tmp_path])}

    assert rows[str(author)]["status"] == "already_organized"
    assert rows[str(author)]["totals"] == {"P": 0, "V": 201, "Other": 1}
    assert rows[str(author)]["actual_moves"] == 0


def test_named_work_directly_under_a_date_can_organize_its_own_files(tmp_path):
    work = tmp_path / "2611" / "261122" / "NO.001"
    put(work / "clip.mp4")
    put(work / "4K" / "clip.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        work.parent, allowed_roots=[tmp_path],
    )}

    assert rows[str(work)]["status"] == "ready"
    assert rows[str(work)]["sample_moves"][0]["target"] == str(work / "001.mp4")
    assert rows[str(work / "4K")]["sample_moves"][0]["target"] == str(work / "4K/001.mp4")


def test_flattened_author_classification_is_already_organized_on_rescan(tmp_path):
    author = tmp_path / "2611" / "261122" / "作者A"
    source = author / "videos" / "clip.mp4"
    target = author / "001.mp4"
    put(source)
    put(author / "NO.001" / "001.jpg")

    before = {row["unit"]: row for row in iter_organizing_previews(
        author.parent, allowed_roots=[tmp_path],
    )}
    assert before[str(author)]["sample_moves"][0]["target"] == str(target)
    source.rename(target)
    source.parent.rmdir()

    after = {row["unit"]: row for row in iter_organizing_previews(
        author.parent, allowed_roots=[tmp_path],
    )}
    assert after[str(author)]["status"] == "already_organized"
    assert after[str(author)]["actual_moves"] == 0


def test_luolcy_scope_preserves_valid_package_after_alias_conflict(tmp_path):
    library = tmp_path / "library"
    package_root = library / "P"
    author = package_root / "2611" / "261115" / "Author"
    package = author / "Work"
    put(package / "Originals" / "a.JPG")
    alias = author / "Alias"
    alias.symlink_to(package, target_is_directory=True)
    put(library / "cover.png")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        library, allowed_roots=[tmp_path], media_package_root=package_root,
    )}

    assert rows[str(alias)]["status"] == "blocked"
    assert rows[str(package)]["status"] == rows[str(library)]["status"] == "ready"
    assert rows[str(package)]["sample_moves"][0]["target"] == str(package / "001.JPG")
    assert rows[str(library)]["sample_moves"][0]["target"] == str(library / "001.png")


@pytest.mark.parametrize(("count", "folders"), [
    (1, []), (200, []), (201, ["P [200 800B]", "P_1 [1 4B]"]),
    (401, ["P [200 800B]", "P_1 [200 800B]", "P_2 [1 4B]"]),
])
def test_semantic_count_threshold_and_complete_numbered_mapping(tmp_path, count, folders):
    unit = tmp_path / "Work"
    for ordinal in range(1, count + 1):
        put(unit / "P1" / f"source-{ordinal:03d}.JPG")

    result = preview_organizing_unit(
        unit, mode="semantic", allowed_roots=[tmp_path], max_rows=1, include_mapping=True,
    )

    assert result["status"] == "ready"
    assert result["actual_moves"] == count
    assert [group["name"] for group in result["groups"]] == folders
    assert len(result["sample_moves"]) == 1
    assert len(result["_mapping_items"]) == count
    assert Path(result["_mapping_items"][0]["target"]).name == "001.JPG"
    assert Path(result["_mapping_items"][-1]["target"]).name == (
        "001.JPG" if folders else f"{count:03d}.JPG"
    )


def test_semantic_mixed_wrappers_use_last_extension_and_keep_other(tmp_path):
    unit = tmp_path / "Work"
    inputs = {
        "P/video.mp4": "V [1 4B]/001.mp4",
        "V/photo.mp4.X.JPG": "P [2 8B]/002.JPG",
        "photos/photo.mp4.X.JPG": "P [2 8B]/001.JPG",
        "videos/video.srt": "Other [1 4B]/video.srt",
    }
    for source in inputs:
        put(unit / source)
    result = preview_organizing_unit(
        unit, mode="semantic", allowed_roots=[tmp_path], include_mapping=True,
    )
    assert result["status"] == "ready"
    assert {
        Path(row["source"]).relative_to(unit).as_posix():
        Path(row["target"]).relative_to(unit).as_posix()
        for row in result["_mapping_items"]
    } == inputs


def test_empty_non_input_target_prevents_flat_publication(tmp_path):
    unit = tmp_path / "Work"
    put(unit / "video.mp4")
    (unit / "001.mp4").mkdir()

    result = preview_organizing_unit(unit, mode="semantic", allowed_roots=[tmp_path])

    assert result["status"] == "blocked"
    assert (unit / "video.mp4").read_bytes() == b"data"
    assert (unit / "001.mp4").is_dir()


def test_canonical_luolcy_buckets_rescan_with_zero_changes(tmp_path):
    root = tmp_path / "Luolcy"
    unit = root / "2611" / "261115" / "Author" / "Work"
    for index in range(12):
        count = 1 if index == 11 else 200
        stem = f"P_{index}" if index else "P"
        for ordinal in range(1, count + 1):
            put(unit / f"{stem} [{count} {count}B]" / f"{ordinal:03d}.JPG", b"x")

    result = preview_organizing_unit(
        unit, mode="luolcy", allowed_roots=[tmp_path], media_package_root=root,
    )

    assert result["status"] == "already_organized"
    assert result["actual_moves"] == result["needed_moves"] == result["renamed_count"] == 0


def test_luolcy_cleanup_preview_keeps_originally_empty_branch(tmp_path):
    root = tmp_path / "Luolcy"
    unit = root / "2611" / "261115" / "Author" / "Work"
    put(unit / "Originals" / "Photos" / "photo.jpg")
    (unit / "Originals" / "Empty").mkdir()

    result = preview_organizing_unit(unit, mode="luolcy", allowed_roots=[tmp_path], media_package_root=root)

    assert result["wrapper_cleanup"] == [str(unit / "Originals" / "Photos")]


@pytest.mark.parametrize("mode", ["luolcy", "semantic"])
def test_existing_target_bucket_with_non_input_child_is_reported(tmp_path, mode):
    root = tmp_path / "Luolcy" if mode == "luolcy" else None
    unit = root / "2611" / "261115" / "Author" / "Work" if root else tmp_path / "Work"
    occupied = unit / "P [1 4B]"
    put(occupied / "001.JPG")
    (occupied / "photos").mkdir()
    put(unit / "video.mp4")

    result = preview_organizing_unit(
        unit, mode=mode, allowed_roots=[tmp_path], media_package_root=root,
    )

    assert result["status"] == "blocked"
    assert (occupied / "photos").is_dir()
    assert (occupied / "001.JPG").read_bytes() == b"data"


def test_blocked_wrappers_keep_nested_independent_works_and_versions(tmp_path):
    work = tmp_path / "Work"
    put(work / "P" / "P1" / "NO.001" / "cover.jpg")
    put(work / "P" / "4K" / "clip.mp4")
    put(work / "P" / "1" / "unknown.jpg")

    rows = {row["unit"]: row["status"] for row in iter_organizing_previews(
        work, allowed_roots=[tmp_path],
    )}

    assert rows == {
        str(work / "P" / "1"): "blocked",
        str(work / "P" / "4K"): "ready", str(work / "P" / "P1" / "NO.001"): "ready",
    }


def test_mixed_photo_wrapper_organizes_its_loose_files_and_allows_pure_sibling(tmp_path):
    work = tmp_path / "作品A"
    mixed = work / "P"
    child = mixed / "NO.002"
    put(mixed / "散图.jpg")
    put(child / "封面.webp")
    put(work / "videos" / "片段.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(work, allowed_roots=[tmp_path])}

    assert rows[str(work)]["status"] == "ready"
    assert [item["target"] for item in rows[str(work)]["sample_moves"]] == [str(work / "001.mp4")]
    assert rows[str(mixed)]["status"] == "ready"
    assert rows[str(mixed)]["totals"] == {"P": 1, "V": 0, "Other": 0}
    assert rows[str(mixed)]["sample_moves"][0]["target"] == str(mixed / "001.jpg")
    assert rows[str(child)]["sample_moves"][0]["target"] == str(child / "001.webp")


def test_mixed_video_wrapper_organizes_only_its_direct_videos(tmp_path):
    work = tmp_path / "作品A"
    wrapper = work / "V"
    child = wrapper / "NO.002"
    put(wrapper / "散视频.avi")
    put(child / "封面.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(work, allowed_roots=[tmp_path])}

    assert rows[str(wrapper)]["status"] == "ready"
    assert [move["target"] for move in rows[str(wrapper)]["sample_moves"]] == [str(wrapper / "001.avi")]
    assert rows[str(child)]["sample_moves"][0]["target"] == str(child / "001.jpg")


def test_photo_container_organizes_direct_images_and_preserves_its_named_child(tmp_path):
    work = tmp_path / "时间难考证"
    photos = work / "照片"
    child = photos / "今日份自拍"
    put(photos / "本层散图.jpg")
    put(child / "子组封面.webp")

    rows = {row["unit"]: row for row in iter_organizing_previews(work, allowed_roots=[tmp_path])}

    assert rows[str(photos)]["status"] == "ready"
    assert [move["target"] for move in rows[str(photos)]["sample_moves"]] == [str(photos / "001.jpg")]
    assert rows[str(child)]["sample_moves"][0]["target"] == str(child / "001.webp")


@pytest.mark.parametrize("date", ["261001", "2026-10-01", "2026年10月1日"])
def test_date_keeps_author_names_that_look_like_classification_wrappers(tmp_path, date):
    day = tmp_path / date
    put(day / "P" / "cover.jpg")
    put(day / "V" / "clip.mp4")
    put(day / "Author" / "photos" / "cover.png")

    rows = list(iter_organizing_previews(day, allowed_roots=[tmp_path]))

    assert {
        row["unit"]: row["sample_moves"][0]["target"]
        for row in rows if row["status"] == "ready"
    } == {
        str(day / "P"): str(day / "P" / "001.jpg"),
        str(day / "V"): str(day / "V" / "001.mp4"),
        str(day / "Author"): str(day / "Author" / "001.png"),
    }


def test_numbered_child_is_held_under_parent_but_direct_selection_stays_self_contained(tmp_path):
    unit = tmp_path / "Work" / "1"
    put(unit / "P1" / "cover.jpg")
    blocked = list(iter_organizing_previews(unit.parent, allowed_roots=[tmp_path]))
    selected = list(iter_organizing_previews(unit, allowed_roots=[tmp_path]))

    assert [(row["unit"], row["status"]) for row in blocked] == [(str(unit), "blocked")]
    assert [(row["unit"], row["status"]) for row in selected] == [(str(unit), "ready")]
    assert selected[0]["sample_moves"][0]["target"] == str(unit / "001.jpg")


def test_default_named_folder_keeps_its_unit_after_media_is_bucketed(tmp_path):
    parent = tmp_path / "作者A"
    folder = parent / "新建文件夹 (2)"
    for position in range(1, 201):
        put(folder / "P [200 800B]" / f"{position:03d}.jpg")
    put(folder / "P_1 [1 4B]/001.jpg")

    records = list(iter_organizing_previews(parent, allowed_roots=[tmp_path]))

    assert [(row["unit"], row["status"], row["actual_moves"]) for row in records] == [
        (str(folder), "already_organized", 0),
    ]


def test_default_named_container_preserves_unassigned_files_and_discovers_its_work(tmp_path):
    parent = tmp_path / "作者A"
    folder = parent / "新建文件夹"
    work = folder / "NO.001"
    put(folder / "散图.jpg")
    put(work / "封面.webp")

    rows = {row["unit"]: row for row in iter_organizing_previews(parent, allowed_roots=[tmp_path])}

    assert rows[str(folder)]["status"] == "blocked"
    assert rows[str(work)]["sample_moves"][0]["target"] == str(work / "001.webp")


def test_numbered_leaf_siblings_of_an_explicit_collection_are_independent(tmp_path):
    collection = tmp_path / "两卷合集"
    put(collection / "01" / "a-cover.jpg")
    put(collection / "01" / "b-page.png")
    put(collection / "02" / "cover.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        collection, allowed_roots=[tmp_path],
    )}

    assert set(rows) == {str(collection / "01"), str(collection / "02")}
    assert all(row["status"] == "ready" for row in rows.values())
    assert [Path(move["target"]).name for move in rows[str(collection / "01")]["sample_moves"]] == [
        "001.jpg", "002.png",
    ]
    assert rows[str(collection / "02")]["sample_moves"][0]["target"] == str(collection / "02/001.jpg")


def test_contiguous_numbered_media_leaves_are_independent_under_a_generic_parent(tmp_path):
    parent = tmp_path / "旧下载"
    put(parent / "parent.mp4")
    put(parent / "1/part.mp4")
    put(parent / "02/part.mp4")
    put(parent / "02/second.mp4")
    put(parent / "3/part.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(parent, allowed_roots=[tmp_path])}

    assert rows[str(parent)]["totals"] == {"P": 0, "V": 1, "Other": 0}
    assert {
        Path(row["unit"]).relative_to(parent).as_posix(): [Path(move["target"]).name for move in row["sample_moves"]]
        for row in rows.values() if row["status"] == "ready"
    } == {".": ["001.mp4"], "1": ["001.mp4"], "02": ["001.mp4", "002.mp4"], "3": ["001.mp4"]}


def test_numbered_packages_keep_their_role_after_parent_and_package_bucketing(tmp_path):
    parent = tmp_path / "旧下载"
    for unit in (parent, parent / "1"):
        for index in range(1, 201):
            put(unit / "V [200 800B]" / f"{index:03d}.mp4")
        put(unit / "V_1 [1 4B]" / "001.mp4")
    put(parent / "2/001.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(parent, allowed_roots=[tmp_path])}

    assert set(rows) == {str(parent), str(parent / "1"), str(parent / "2")}
    assert all(row["status"] == "already_organized" and row["actual_moves"] == 0 for row in rows.values())


@pytest.mark.parametrize("boundary", ["gap", "loose-file", "unmarked-work", "photo-wrapper", "protected-work"])
def test_numbered_volume_still_needs_an_unambiguous_directory_shape(tmp_path, boundary):
    series = tmp_path / "网盘"
    first = series / "1"
    second = series / ("3" if boundary == "gap" else "2")
    name = {"unmarked-work": "临时目录", "photo-wrapper": "图包"}.get(boundary, "作品 VOL.01")
    work = first / name
    put(work / "cover.jpg")
    put(second / "作品 VOL.02/cover.jpg")
    if boundary == "loose-file":
        put(first / "loose.mp4")
    quarantine_root = work if boundary == "protected-work" else None

    rows = {row["unit"]: row for row in iter_organizing_previews(
        series, allowed_roots=[tmp_path], quarantine_root=quarantine_root, include_mapping=True,
    )}

    assert rows[str(first)]["status"] == "blocked"
    assert rows[str(first)]["reason"] == "Ambiguous directory role"
    assert not rows[str(first)].get("_mapping_items")


@pytest.mark.parametrize("boundary", [
    "count-mismatch", "mixed-media", "extra-folder", "protected-group",
    "mixed-label", "duplicate-count", "another-video-label", "another-photo-label",
])
def test_promoting_photo_groups_requires_an_exact_isolated_photo_work(tmp_path, boundary):
    label = {
        "count-mismatch": "[3P 4B]",
        "mixed-label": "[2P 1视频]",
        "duplicate-count": "[2P 1P]",
        "another-video-label": "[2P 4B] [1V]",
        "another-photo-label": "[2P 4B] [3P]",
    }.get(boundary, "[2P 4B]")
    work = tmp_path / f"系列 {label}"
    first = work / "图片/3"
    put(first / "cover.jpg")
    put(work / ("图片/9/clip.mp4" if boundary == "mixed-media" else "图片/9/cover.jpg"))
    if boundary == "extra-folder":
        (work / "历史批次").mkdir()
    quarantine_root = first if boundary == "protected-group" else None

    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path], quarantine_root=quarantine_root))

    assert all(row.get("operation") != "promote_numbered_photo_groups" for row in rows)


def test_existing_numbered_photo_groups_do_not_trigger_a_lift_without_a_wrapper(tmp_path):
    work = tmp_path / "旧下载 [2P 8B]"
    put(work / "3/a.jpg")
    put(work / "9/b.jpg")

    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path]))

    assert all(row.get("operation") != "promote_numbered_photo_groups" for row in rows)


def test_numbered_container_with_named_work_preserves_ambiguous_direct_files(tmp_path):
    collection = tmp_path / "两卷合集"
    put(collection / "01" / "散图.jpg")
    put(collection / "01" / "NO.003" / "封面.jpg")
    put(collection / "02" / "cover.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        collection, allowed_roots=[tmp_path],
    )}

    assert rows[str(collection / "01")]["status"] == "blocked"
    assert rows[str(collection / "02")]["status"] == "ready"
    assert rows[str(collection / "02")]["sample_moves"][0]["target"] == str(collection / "02/001.jpg")
    assert rows[str(collection / "01/NO.003")]["sample_moves"][0]["target"] == str(collection / "01/NO.003/001.jpg")


def test_canonical_buckets_on_calendar_level_still_rescan_as_one_unit(tmp_path):
    day = tmp_path / "261001"
    put(day / "P [1 4B]" / "001.jpg")
    put(day / "V [1 4B]" / "001.mp4")
    put(day / "P" / "001.png")

    rows = list(iter_organizing_previews(day, allowed_roots=[tmp_path]))

    assert {row["unit"] for row in rows} == {str(day), str(day / "P")}
    assert all(row["status"] == "already_organized" and row["actual_moves"] == 0 for row in rows)


def test_calendar_author_with_numbered_alias_does_not_block_independent_media(tmp_path):
    day = tmp_path / "261001"
    put(day / "P_1" / "cover.jpg")
    put(day / "extra.gif")
    put(day / "clip.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(day, allowed_roots=[tmp_path])}

    assert rows[str(day)]["status"] == rows[str(day / "P_1")]["status"] == "ready"
    assert rows[str(day)]["totals"] == {"P": 1, "V": 1, "Other": 0}
    assert rows[str(day / "P_1")]["sample_moves"][0]["target"] == str(day / "P_1" / "001.jpg")


def test_direct_selection_never_organizes_retained_historical_staging(tmp_path):
    stage = tmp_path / "Work" / ".nfc-media-organizer-stage-35"
    put(stage / "cover.jpg")
    put(stage / "nested" / "clip.mp4")

    for path in (stage, stage / "nested"):
        with pytest.raises(ValueError, match="Reserved"):
            list(iter_organizing_previews(path, allowed_roots=[tmp_path]))
        with pytest.raises(ValueError, match="Reserved"):
            preview_organizing_unit(path, mode="semantic", allowed_roots=[tmp_path])
