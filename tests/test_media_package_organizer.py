"""MediaPackage-only fixed policy: read-only, bounded, safe package preview."""
from pathlib import Path

import pytest

from app.batch.media_package_organizer import (
    preview_media_package_package, iter_media_package_packages, iter_media_package_previews,
)


def make_package(tmp_path):
    root = tmp_path / "data" / "Else" / "Collection"
    package = root / "2611" / "261115" / "SampleAuthor" / "SampleBundle"
    package.mkdir(parents=True)
    return root, package


def preview(root, package, **kwargs):
    return preview_media_package_package(
        package, media_package_root=root,
        allowed_roots=[root.parent.parent], **kwargs
    )


@pytest.mark.parametrize(("extension", "count"), [(".jpg", 200), (".MP4", 50)])
def test_pure_media_at_its_capacity_flattens_only_to_package_root(tmp_path, extension, count):
    root, package = make_package(tmp_path)
    nested = package / "额外的目录"
    nested.mkdir()
    for i in range(count):
        (nested / f"{i:03d}{extension}").write_bytes(b"payload")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["operation"] == "flatten_pure_media"
    assert result["needed_moves"] == count
    assert result["groups"] == []
    assert len(list(nested.iterdir())) == count
    assert result["sample_moves"][0]["target"].startswith(str(package) + "/")
    assert not any(child.name.startswith("P") for child in package.iterdir())
    assert not any(child.name.startswith("V") for child in package.iterdir())


def test_mixed_media_uses_separate_bucket_capacities_and_is_not_mutated(tmp_path):
    root, package = make_package(tmp_path)
    images = package / "图包" / "第一次"
    videos = package / "视频"
    images.mkdir(parents=True)
    videos.mkdir()
    for i in range(201):
        (images / f"{i:03d}.jpg").write_bytes(b"x")
    for i in range(202):
        (videos / f"{i:03d}.mp4").write_bytes(b"xy")
    (package / "notes.nfo").write_text("hello", encoding="utf-8")
    result = preview(root, package, max_rows=12)
    assert result["status"] == "ready", result
    assert result["totals"] == {"P": 201, "V": 202, "Other": 1}
    assert [(x["kind"], x["count"]) for x in result["groups"]] == [
        ("P", 200), ("P", 1), ("V", 50), ("V", 50), ("V", 50), ("V", 50), ("V", 2), ("Other", 1)
    ]
    assert result["groups"][0]["name"] == "P [200 200B]"
    assert result["groups"][2]["name"] == "V [50 100B]"
    assert result["total_proposals"] == 404
    assert len(result["sample_moves"]) == 12
    assert result["truncated"] is True
    assert (images / "000.jpg").read_bytes() == b"x"
    assert (videos / "201.mp4").read_bytes() == b"xy"
    assert not any(child.name.startswith("P [") for child in package.iterdir())


def test_two_digit_video_bucket_ordinals_are_stable_on_rescan(tmp_path):
    root, package = make_package(tmp_path)
    for serial in range(11):
        stem = f"V_{serial}" if serial else "V"
        bucket = package / f"{stem} [50 50B]"
        bucket.mkdir()
        for number in range(1, 51):
            (bucket / f"{number:03d}.mp4").write_bytes(b"x")

    assert preview(root, package)["status"] == "already_organized"


def test_fixed_package_boundary_rejects_parent_and_other_tree(tmp_path):
    root, package = make_package(tmp_path)
    (package / "a.jpg").touch()
    with pytest.raises(ValueError, match="Expected"):
        preview(root, package.parent)
    with pytest.raises(ValueError, match="outside configured roots"):
        preview(root, tmp_path / "outside")


def test_symlinks_are_never_traversed(tmp_path):
    root, package = make_package(tmp_path)
    target = tmp_path / "other"
    target.mkdir()
    (target / "secret.mp4").write_bytes(b"do-not-read")
    (package / "alias").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink requires manual review"):
        preview(root, package)
    assert (target / "secret.mp4").read_bytes() == b"do-not-read"


def test_legacy_labelled_targets_with_original_files_are_replanned(tmp_path):
    root, package = make_package(tmp_path)
    p = package / "P [1 5B]"
    v = package / "V [1 7B]"
    p.mkdir()
    v.mkdir()
    (p / "one.jpg").write_bytes(b"image")
    (v / "one.mp4").write_bytes(b"example")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["conflicts"] == []
    assert [g["name"] for g in result["groups"]] == ["P [1 5B]", "V [1 7B]"]
    assert (p / "one.jpg").read_bytes() == b"image"
    assert (v / "one.mp4").read_bytes() == b"example"


def test_existing_unrelated_target_requires_manual_review(tmp_path):
    root, package = make_package(tmp_path)
    (package / "a.jpg").write_bytes(b"x")
    (package / "a.mp4").write_bytes(b"y")
    target = package / "P [1 1B]"
    target.mkdir()
    result = preview(root, package)
    assert result["status"] == "blocked"
    assert any(x["reason"] == "target_directory_exists" for x in result["conflicts"])


def test_plain_legacy_pv_folders_are_inputs_not_automatic_conflicts(tmp_path):
    root, package = make_package(tmp_path)
    (package / "P").mkdir()
    (package / "V").mkdir()
    (package / "P" / "one.jpg").write_bytes(b"x")
    (package / "V" / "one.mp4").write_bytes(b"y")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["conflicts"] == []
    assert [g["name"] for g in result["groups"]] == [
        "P [1 1B]", "V [1 1B]",
    ]


def test_existing_numbered_legacy_bucket_is_reported_for_manual_review(tmp_path):
    root, package = make_package(tmp_path)
    (package / "one.jpg").write_bytes(b"x")
    (package / "one.mp4").write_bytes(b"y")
    (package / "P_1").mkdir()
    result = preview(root, package)
    assert result["status"] == "blocked"
    assert any(x["reason"] == "legacy_numbered_bucket_requires_review"
               for x in result["conflicts"])



def test_existing_labelled_buckets_and_legacy_numbered_inputs_do_not_block(tmp_path):
    root, package = make_package(tmp_path)
    legacy = package / "P_1"
    old_label = package / "V [1 1B]"
    legacy.mkdir()
    old_label.mkdir()
    (legacy / "001.jpg").write_bytes(b"a")
    (old_label / "old.mp4").write_bytes(b"b")
    (package / "new.mp4").write_bytes(b"c")
    result = preview(root, package)
    assert result["status"] == "ready", result["conflicts"]
    assert result["conflicts"] == []
    assert result["totals"] == {"P": 1, "V": 2, "Other": 0}
    assert sorted(group["name"] for group in result["groups"]) == [
        "P [1 1B]", "V [2 2B]",
    ]


def test_renamed_existing_bucket_is_an_input_not_a_foreign_competing_target(tmp_path):
    root, package = make_package(tmp_path)
    bucket = package / "P [1 1B]"
    bucket.mkdir()
    (bucket / "old.jpg").write_bytes(b"a")
    (package / "new.jpg").write_bytes(b"b")
    (package / "movie.mp4").write_bytes(b"c")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["conflicts"] == []
    assert [group["name"] for group in result["groups"]] == [
        "P [2 2B]", "V [1 1B]",
    ]
    assert (bucket / "old.jpg").exists()


def test_empty_legacy_numbered_folder_is_not_adopted_as_an_input(tmp_path):
    root, package = make_package(tmp_path)
    (package / "P_1").mkdir()
    (package / "one.jpg").write_bytes(b"a")
    (package / "one.mp4").write_bytes(b"b")
    result = preview(root, package)
    assert result["status"] == "blocked"
    assert any(
        conflict["reason"] == "legacy_numbered_bucket_requires_review"
        for conflict in result["conflicts"]
    )


def test_bad_directory_name_outside_fixed_layout_rejected(tmp_path):
    root, package = make_package(tmp_path)
    alternate = root / "misc" / "misc" / "person" / "package"
    alternate.mkdir(parents=True)
    with pytest.raises(ValueError, match="Expected"):
        preview(root, alternate)


def test_pure_video_flatten_collision_is_auto_numbered(tmp_path):
    root, package = make_package(tmp_path)
    a = package / "clips-a"
    b = package / "clips-b"
    a.mkdir()
    b.mkdir()
    (a / "001.mp4").write_bytes(b"one")
    (b / "001.mp4").write_bytes(b"two")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["operation"] == "flatten_pure_media"
    assert result["conflicts"] == []
    assert result["resolved_collision_count"] == 1
    assert [Path(row["target"]).name for row in result["sample_moves"]] == [
        "001.mp4", "002.mp4",
    ]


def test_flat_pure_media_is_idempotently_skipped(tmp_path):
    root, package = make_package(tmp_path)
    (package / "001.mp4").write_bytes(b"video")
    result = preview(root, package)
    assert result["status"] == "skipped"
    assert result["reason"] == "already_flat_numbered"
    assert result["needed_moves"] == 0


def test_root_and_nested_homonyms_can_be_staged(tmp_path):
    root, package = make_package(tmp_path)
    (package / "001.jpg").write_bytes(b"original")
    (package / "images").mkdir()
    (package / "images" / "001.JPG").write_bytes(b"nested")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["conflicts"] == []
    assert result["resolved_collision_count"] == 1
    assert [Path(row["target"]).name for row in result["sample_moves"]] == [
        "001.jpg", "002.JPG",
    ]


@pytest.mark.parametrize("extension,kind,capacity", [(".jpg", "P", 200), (".mp4", "V", 50)])
@pytest.mark.parametrize("complete,remainder", [(1, 1), (2, 0), (2, 1)])
def test_pure_media_over_capacity_uses_numbered_count_size_buckets(
    tmp_path, extension, kind, capacity, complete, remainder,
):
    root, package = make_package(tmp_path)
    folder = package / "nested"
    folder.mkdir()
    count = complete * capacity + remainder
    for i in range(count):
        (folder / f"{i:04d}{extension}").write_bytes(b"123")
    result = preview(root, package)
    assert result["status"] == "ready", result
    assert result["operation"] == "bucket_pure_media"
    assert result["total_files"] == count
    expected_counts = [capacity] * complete
    if remainder:
        expected_counts.append(remainder)
    assert [group["count"] for group in result["groups"]] == expected_counts
    assert [group["name"] for group in result["groups"]] == [
        f"{kind if i == 0 else kind + '_' + str(i)} [{size} {size*3}B]"
        for i, size in enumerate(expected_counts)
    ]
    assert result["needed_moves"] == count
    assert not any(entry.is_dir() and entry.name.startswith(kind + " [")
                   for entry in package.iterdir())
    assert len(list(folder.iterdir())) == count


@pytest.mark.parametrize("extension,kind,capacity", [(".jpg", "P", 200), (".mp4", "V", 50)])
def test_flat_pure_media_over_capacity_is_still_bucketed(tmp_path, extension, kind, capacity):
    root, package = make_package(tmp_path)
    for i in range(capacity + 1):
        (package / f"{i:03d}{extension}").write_bytes(b"x")
    result = preview(root, package)
    assert result["operation"] == "bucket_pure_media"
    assert [(x["kind"], x["count"]) for x in result["groups"]] == [
        (kind, capacity), (kind, 1)
    ]
    assert result["needed_moves"] == capacity + 1


@pytest.mark.parametrize("extension,capacity", [(".jpg", 200), (".mp4", 50)])
def test_flat_pure_media_at_capacity_is_renumbered(tmp_path, extension, capacity):
    root, package = make_package(tmp_path)
    for i in range(capacity):
        (package / f"{i:03d}{extension}").write_bytes(b"x")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["groups"] == []
    assert result["needed_moves"] == capacity
    assert result["sample_moves"][0]["target"].endswith("001" + extension)


def test_pure_media_201_filename_collision_is_auto_numbered(tmp_path):
    root, package = make_package(tmp_path)
    first = package / "A"
    second = package / "B"
    first.mkdir()
    second.mkdir()
    for i in range(1, 200):
        (first / f"{i:03d}.jpg").write_bytes(b"photo")
    (second / "001.jpg").write_bytes(b"different")
    (second / "extra.jpg").write_bytes(b"last")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["operation"] == "bucket_pure_media"
    assert result["conflicts"] == []
    assert result["resolved_collision_count"] == 1
    assert len({row["target"] for row in result["sample_moves"]}) == len(result["sample_moves"])


def test_media_package_root_month_day_scope_discovers_only_resource_packages(tmp_path):
    root, first = make_package(tmp_path)
    same_day = root / "2611" / "261115" / "第二作者" / "Package2"
    same_day.mkdir(parents=True)
    other_day = root / "2611" / "261116" / "第三作者" / "Package3"
    other_day.mkdir(parents=True)
    other_month = root / "2610" / "261015" / "第四作者" / "Package4"
    other_month.mkdir(parents=True)
    nonconforming = root / "misc" / "261115" / "作者" / "ShouldNeverBePackage"
    nonconforming.mkdir(parents=True)
    wrong_month_day = root / "2611" / "261015" / "作者" / "WrongDate"
    wrong_month_day.mkdir(parents=True)
    kwargs = {"media_package_root": root, "allowed_roots": [root.parent.parent]}
    assert list(iter_media_package_packages(root, **kwargs)) == [
        other_month, first, same_day, other_day,
    ]
    assert list(iter_media_package_packages(root / "2611", **kwargs)) == [
        first, same_day, other_day,
    ]
    assert list(iter_media_package_packages(root / "2611" / "261115", **kwargs)) == [
        first, same_day,
    ]
    assert list(iter_media_package_packages(first, **kwargs)) == [first]
    assert list(iter_media_package_packages(first.parent, **kwargs)) == [first]


def test_day_scope_generates_independent_read_only_package_previews(tmp_path):
    root, first = make_package(tmp_path)
    another = root / "2611" / "261115" / "另一个作者" / "New 2GB"
    another.mkdir(parents=True)
    (first / "001.jpg").write_bytes(b"photo")
    (another / "001.mp4").write_bytes(b"movie")
    kwargs = {"media_package_root": root, "allowed_roots": [root.parent.parent]}
    previews = list(iter_media_package_previews(root / "2611" / "261115", **kwargs))
    assert {result["package"] for result in previews} == {str(first), str(another)}
    assert all(result["status"] == "skipped" for result in previews)
    assert (first / "001.jpg").read_bytes() == b"photo"
    assert (another / "001.mp4").read_bytes() == b"movie"


def test_media_package_scope_rejects_outside_tree_and_invalid_day(tmp_path):
    root, first = make_package(tmp_path)
    kwargs = {"media_package_root": root, "allowed_roots": [root.parent.parent]}
    with pytest.raises(ValueError, match="configured MediaPackage root"):
        list(iter_media_package_packages(root.parent, **kwargs))
    with pytest.raises(ValueError, match="Select MediaPackage"):
        list(iter_media_package_packages(root / "2611" / "261016", **kwargs))
    with pytest.raises(ValueError, match="Select MediaPackage"):
        list(iter_media_package_packages(first / "P", **kwargs))


def test_media_package_scope_does_not_follow_symlinked_author(tmp_path):
    root, first = make_package(tmp_path)
    sibling = root / "2611" / "261115" / "alias"
    sibling.symlink_to(first.parent, target_is_directory=True)
    kwargs = {"media_package_root": root, "allowed_roots": [root.parent.parent]}
    with pytest.raises(ValueError, match="contains a symlink"):
        list(iter_media_package_packages(root / "2611" / "261115", **kwargs))


def test_already_numbered_grouped_media_is_idempotent(tmp_path):
    root, package = make_package(tmp_path)
    p = package / "P [1 5B]"
    v = package / "V [1 7B]"
    p.mkdir()
    v.mkdir()
    (p / "001.jpg").write_bytes(b"image")
    (v / "001.mp4").write_bytes(b"example")
    result = preview(root, package)
    assert result["status"] == "already_organized"
    assert result["needed_moves"] == 0
    assert result["conflicts"] == []


def test_flat_root_numbering_keeps_original_path_mapping(tmp_path):
    root, package = make_package(tmp_path)
    (package / "001.mp4").write_bytes(b"first")
    (package / "clips").mkdir()
    (package / "clips" / "001.mp4").write_bytes(b"second")
    result = preview(root, package)
    assert result["status"] == "ready"
    assert result["needed_moves"] == 2
    assert result["resolved_collision_count"] == 1
    assert [row["target_name"] for row in result["sample_moves"]] == ["001.mp4", "002.mp4"]
    assert all("original_relative_path" in row for row in result["sample_moves"])
