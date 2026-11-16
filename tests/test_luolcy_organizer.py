"""Luolcy-only fixed policy: read-only, bounded, safe package preview."""
from pathlib import Path

import pytest

from app.batch.luolcy_organizer import preview_luolcy_package


def make_package(tmp_path):
    root = tmp_path / "data" / "Else" / "Luolcy"
    package = root / "2611" / "261115" / "疑心病" / "New 1432.1MB"
    package.mkdir(parents=True)
    return root, package


def preview(root, package, **kwargs):
    return preview_luolcy_package(
        package, luolcy_root=root,
        allowed_roots=[root.parent.parent], **kwargs
    )


@pytest.mark.parametrize("extension", [".jpg", ".MP4"])
def test_pure_media_is_left_entirely_unchanged(tmp_path, extension):
    root, package = make_package(tmp_path)
    nested = package / "额外的目录"
    nested.mkdir()
    for i in range(205):
        (nested / f"{i:03d}{extension}").write_bytes(b"payload")
    result = preview(root, package)
    assert result["status"] == "skipped"
    assert result["reason"] == "pure_media"
    assert result["groups"] == []
    assert len(list(nested.iterdir())) == 205
    assert not any(child.name.startswith("P") for child in package.iterdir())
    assert not any(child.name.startswith("V") for child in package.iterdir())


def test_mixed_media_is_grouped_at_two_hundred_and_not_mutated(tmp_path):
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
        ("P", 200), ("P", 1), ("V", 200), ("V", 2), ("Other", 1)
    ]
    assert result["groups"][0]["name"] == "P [200 200B]"
    assert result["groups"][2]["name"] == "V [200 400B]"
    assert result["total_proposals"] == 404
    assert len(result["sample_moves"]) == 12
    assert result["truncated"] is True
    assert (images / "000.jpg").read_bytes() == b"x"
    assert (videos / "201.mp4").read_bytes() == b"xy"
    assert not any(child.name.startswith("P [") for child in package.iterdir())


def test_fixed_package_boundary_rejects_parent_and_other_tree(tmp_path):
    root, package = make_package(tmp_path)
    (package / "a.jpg").touch()
    with pytest.raises(ValueError, match="Expected"):
        preview(root, package.parent)
    with pytest.raises(ValueError, match="below the configured"):
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


def test_existing_final_folder_is_idempotent(tmp_path):
    root, package = make_package(tmp_path)
    p = package / "P [1 5B]"
    v = package / "V [1 7B]"
    p.mkdir()
    v.mkdir()
    (p / "one.jpg").write_bytes(b"image")
    (v / "one.mp4").write_bytes(b"example")
    result = preview(root, package)
    assert result["status"] == "already_organized"
    assert result["needed_moves"] == 0
    assert result["conflicts"] == []
    assert not (package / "P_1").exists()


def test_existing_unrelated_target_requires_manual_review(tmp_path):
    root, package = make_package(tmp_path)
    (package / "a.jpg").write_bytes(b"x")
    (package / "a.mp4").write_bytes(b"y")
    target = package / "P [1 1B]"
    target.mkdir()
    result = preview(root, package)
    assert result["status"] == "blocked"
    assert any(x["reason"] == "target_directory_exists" for x in result["conflicts"])


def test_existing_numbered_bucket_is_reported_for_manual_review(tmp_path):
    root, package = make_package(tmp_path)
    (package / "one.jpg").write_bytes(b"x")
    (package / "one.mp4").write_bytes(b"y")
    (package / "P").mkdir()
    result = preview(root, package)
    assert result["status"] == "blocked"
    assert any(x["reason"] == "existing_bucket_name_requires_review"
               for x in result["conflicts"])


def test_bad_directory_name_outside_fixed_layout_rejected(tmp_path):
    root, package = make_package(tmp_path)
    alternate = root / "misc" / "misc" / "person" / "package"
    alternate.mkdir(parents=True)
    with pytest.raises(ValueError, match="Expected"):
        preview(root, alternate)
