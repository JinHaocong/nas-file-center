"""V1.6 media rules tested through the read-only preview boundary."""
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import iter_organizing_previews, preview_organizing_unit


def put(path: Path, content: bytes = b"data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


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
    put(author / "NO.001" / "封面.jpg")
    put(photo_only_author / "P1" / "封面.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        author.parent, allowed_roots=[tmp_path],
    )}

    assert rows[str(author)]["status"] == "blocked"
    assert rows[str(author)]["reason"] == "作者层散文件待确认"
    assert rows[str(author)]["totals"] == {"P": 0, "V": 1, "Other": 0}
    assert rows[str(author / "NO.001")]["sample_moves"][0]["target"] == str(author / "NO.001/001.jpg")
    assert rows[str(photo_only_author)]["sample_moves"][0]["target"] == str(photo_only_author / "001.jpg")


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


def test_mixed_wrapper_preserves_its_loose_files_and_allows_pure_sibling(tmp_path):
    work = tmp_path / "作品A"
    mixed = work / "P"
    child = mixed / "NO.002"
    put(mixed / "散图.jpg")
    put(child / "封面.webp")
    put(work / "videos" / "片段.mp4")

    rows = {row["unit"]: row for row in iter_organizing_previews(work, allowed_roots=[tmp_path])}

    assert rows[str(work)]["status"] == "ready"
    assert [item["target"] for item in rows[str(work)]["sample_moves"]] == [str(work / "001.mp4")]
    assert rows[str(mixed)]["status"] == "blocked"
    assert rows[str(mixed)]["totals"] == {"P": 1, "V": 0, "Other": 0}
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


def test_numbered_container_with_named_work_preserves_ambiguous_direct_files(tmp_path):
    collection = tmp_path / "两卷合集"
    put(collection / "01" / "散图.jpg")
    put(collection / "01" / "NO.003" / "封面.jpg")
    put(collection / "02" / "cover.jpg")

    rows = {row["unit"]: row for row in iter_organizing_previews(
        collection, allowed_roots=[tmp_path],
    )}

    assert rows[str(collection / "01")]["status"] == rows[str(collection / "02")]["status"] == "blocked"
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
