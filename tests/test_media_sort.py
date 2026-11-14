"""P/V media sorting stays a read-only one-level preview until a Move Plan executes."""
from pathlib import Path

import pytest

from app.batch import media_sort
from app.batch.media_sort import preview_media_sort


def preview(parent: Path, *, roots=None, trash=None, recursive=False):
    return preview_media_sort(
        parent,
        recursive=recursive,
        allowed_roots=roots if roots is not None else [parent.parent],
        quarantine_root=trash,
    )


def test_preview_sorts_images_and_videos_without_mutating(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    original = {
        "风景.JPG": b"image",
        "portrait.HEIC": b"heic",
        "holiday.mp4": b"video",
        "clip.MKV": b"mkv",
        "notes.txt": b"text",
        "track.mp3": b"audio",
    }
    for name, data in original.items():
        (parent / name).write_bytes(data)
    nested = parent / "nested"
    nested.mkdir()
    (nested / "hidden.jpg").write_bytes(b"nested")
    (parent / "link.jpg").symlink_to(parent / "风景.JPG")

    result = preview(parent)
    assert result["parent"] == str(parent)
    assert result["count"] == 4
    assert result["image_count"] == 2
    assert result["video_count"] == 2
    assert result["ready_count"] == 4
    assert result["conflict_count"] == 0
    assert all(row["conflict"] is False for row in result["items"])
    assert {
        (Path(row["source"]).name, Path(row["target"]).relative_to(parent).as_posix())
        for row in result["items"]
    } == {
        ("风景.JPG", "P/风景.JPG"),
        ("portrait.HEIC", "P/portrait.HEIC"),
        ("holiday.mp4", "V/holiday.mp4"),
        ("clip.MKV", "V/clip.MKV"),
    }
    assert not (parent / "P").exists()
    assert not (parent / "V").exists()
    for name, data in original.items():
        assert (parent / name).read_bytes() == data
    assert (nested / "hidden.jpg").read_bytes() == b"nested"
    assert (parent / "link.jpg").is_symlink()


def test_existing_pv_dirs_choose_numbered_folder_instead_of_reusing(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "Photo.JPG").write_bytes(b"source")
    (parent / "movie.mp4").write_bytes(b"video")
    (parent / "P").mkdir()
    (parent / "V").mkdir()
    (parent / "P" / "photo.jpg").write_bytes(b"existing")
    (parent / "V" / "other.mp4").write_bytes(b"other")

    result = preview(parent)
    assert result["conflict_count"] == 0
    assert result["ready_count"] == 2
    photo = next(row for row in result["items"] if row["media_kind"] == "image")
    movie = next(row for row in result["items"] if row["media_kind"] == "video")
    assert photo["target"] == str(parent / "P_1" / "Photo.JPG")
    assert movie["target"] == str(parent / "V_1" / "movie.mp4")
    assert (parent / "P" / "photo.jpg").read_bytes() == b"existing"
    assert not (parent / "P_1").exists()
    assert not (parent / "V_1").exists()


@pytest.mark.parametrize("occupant", ["file", "symlink"])
def test_suffixes_occupied_target_parent_without_traversing(tmp_path, occupant):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "image.png").write_bytes(b"image")
    (parent / "video.mp4").write_bytes(b"video")
    target = parent / "P"
    if occupant == "file":
        target.write_bytes(b"not a directory")
    else:
        target.symlink_to(tmp_path, target_is_directory=True)

    result = preview(parent)
    assert result["conflict_count"] == 0
    photo = next(row for row in result["items"] if row["media_kind"] == "image")
    assert photo["target"] == str(parent / "P_1" / "image.png")
    assert not (parent / "P_1").exists()
    assert (parent / "image.png").exists()
    assert (parent / "video.mp4").exists()


def test_rejects_selected_symlink_and_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = root / "alias"
    alias.symlink_to(inside, target_is_directory=True)

    with pytest.raises(ValueError, match="non-symlink"):
        preview(alias, roots=[root])
    with pytest.raises(ValueError, match="outside configured roots"):
        preview(outside, roots=[root])


def test_quarantine_path_is_not_selectable(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    trash = root / ".trash"
    trash.mkdir()
    (trash / "private.jpg").write_bytes(b"protected")
    with pytest.raises(ValueError, match="reserved"):
        preview(trash, roots=[root], trash=trash)


def test_directory_size_is_bounded_before_any_change(tmp_path, monkeypatch):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "a.jpg").write_bytes(b"a")
    (parent / "b.mp4").write_bytes(b"b")
    monkeypatch.setattr(media_sort, "MAX_IMMEDIATE_ENTRIES", 1)
    with pytest.raises(ValueError, match="Too many immediate entries"):
        preview(parent)
    assert not (parent / "P").exists()
    assert not (parent / "V").exists()


def test_api_preview_creates_only_normal_move_plan_draft(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    (data / "photo.JPG").write_bytes(b"photo")
    (data / "clip.MP4").write_bytes(b"clip")
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/media-sort/preview", json={"parent": str(data)}).status_code == 401
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        response = client.post("/api/media-sort/preview", json={"parent": str(data)})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == 2
        assert body["conflict_count"] == 0
        assert not (data / "P").exists()
        assert not (data / "V").exists()
        plan = client.post("/api/plans", json={
            "name": "P/V 分类",
            "kind": "media-sort",
            "items": [
                {"operation": "move", "source": row["source"],
                 "target": row["target"], "expected_size": row["expected_size"]}
                for row in body["items"]
            ],
        })
        assert plan.status_code == 200, plan.text
        assert plan.json()["expected_changes"] == 2
        assert not (data / "P").exists()
        assert not (data / "V").exists()
        assert (data / "photo.JPG").exists() and (data / "clip.MP4").exists()


def test_recursive_places_pv_inside_each_source_directory(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    nested = parent / "Travel"
    deep = nested / "Day1"
    deep.mkdir(parents=True)
    (parent / "cover.JPG").write_bytes(b"root")
    (nested / "photo.png").write_bytes(b"one")
    (nested / "movie.MOV").write_bytes(b"two")
    (deep / "clip.mp4").write_bytes(b"three")
    (deep / "memo.txt").write_bytes(b"leave alone")

    result = preview(parent, recursive=True)
    assert result["recursive"] is True
    assert result["scanned_directories"] == 3
    assert result["count"] == 4
    assert result["conflict_count"] == 0
    assert {
        (Path(row["source"]).relative_to(parent).as_posix(),
         Path(row["target"]).relative_to(parent).as_posix())
        for row in result["items"]
    } == {
        ("cover.JPG", "P/cover.JPG"),
        ("Travel/photo.png", "Travel/P/photo.png"),
        ("Travel/movie.MOV", "Travel/V/movie.MOV"),
        ("Travel/Day1/clip.mp4", "Travel/Day1/V/clip.mp4"),
    }
    assert not (nested / "P").exists()
    assert (deep / "clip.mp4").read_bytes() == b"three"


def test_disabled_recursion_does_not_include_nested_files(tmp_path):
    parent = tmp_path / "mixed"
    deep = parent / "a" / "b"
    deep.mkdir(parents=True)
    (parent / "cover.jpg").write_bytes(b"root")
    (deep / "nested.mp4").write_bytes(b"nested")

    result = preview(parent)
    assert result["recursive"] is False
    assert result["scanned_directories"] == 1
    assert result["count"] == 1
    assert result["items"][0]["target"] == str(parent / "P" / "cover.jpg")


def test_recursive_skips_classification_directories_symlinks_and_quarantine(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "root.jpg").write_bytes(b"root")
    nested = parent / "child"
    nested.mkdir()
    (nested / "video.mp4").write_bytes(b"video")
    for folder in ("P", "V", "P_1", "V_99"):
        (nested / folder).mkdir()
        (nested / folder / "already.jpg").write_bytes(b"previous")
    (parent / "P").mkdir()
    (parent / "P" / "previous.jpg").write_bytes(b"previous")
    trash = parent / ".trash"
    trash.mkdir()
    (trash / "private.mp4").write_bytes(b"private")
    (parent / "child-link").symlink_to(nested, target_is_directory=True)

    result = preview(parent, recursive=True, trash=trash)
    assert result["count"] == 2
    assert result["scanned_directories"] == 2
    assert result["conflict_count"] == 0
    assert {
        Path(row["target"]).relative_to(parent).as_posix()
        for row in result["items"]
    } == {"P_1/root.jpg", "child/V_1/video.mp4"}
    assert (trash / "private.mp4").exists()
    assert not (nested / "V_1").exists()
    assert (nested / "P" / "already.jpg").exists()


def test_folder_suffix_skips_numbered_and_casefold_existing_names(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    for name in ("p", "P_1", "p_2", "v", "V_1"):
        (parent / name).mkdir()
    (parent / "A.jpg").write_bytes(b"image")
    (parent / "B.mp4").write_bytes(b"video")

    rows = preview(parent)["items"]
    assert {
        Path(row["target"]).relative_to(parent).as_posix()
        for row in rows
    } == {"P_3/A.jpg", "V_2/B.mp4"}


def test_duplicate_casefold_filenames_get_unique_suffixes(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "Photo.JPG").write_bytes(b"upper")
    (parent / "photo.jpg").write_bytes(b"lower")
    (parent / "a.MP4").write_bytes(b"video")
    (parent / "A.mp4").write_bytes(b"video2")
    result = preview(parent)
    assert result["count"] == 4
    assert result["conflict_count"] == 0
    targets = [Path(item["target"]).name for item in result["items"]]
    assert len({name.casefold() for name in targets}) == 4
    assert any(name.casefold().endswith("_1.jpg") for name in targets)
    assert any(name.casefold().endswith("_1.mp4") for name in targets)
    assert not (parent / "P").exists()


def test_file_suffix_keeps_filesystem_component_length_bounded(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / ("a" * 250 + ".jpg")).write_bytes(b"a")
    (parent / ("A" * 250 + ".JPG")).write_bytes(b"b")
    result = preview(parent)
    assert result["conflict_count"] == 0
    for item in result["items"]:
        assert len(Path(item["target"]).name.encode()) <= 255


def test_recursive_scan_entry_and_directory_limits_are_safe(tmp_path, monkeypatch):
    parent = tmp_path / "mixed"
    leaf = parent / "child"
    leaf.mkdir(parents=True)
    (parent / "one.jpg").write_bytes(b"one")
    (leaf / "two.mp4").write_bytes(b"two")
    monkeypatch.setattr(media_sort, "MAX_RECURSIVE_ENTRIES", 2)
    with pytest.raises(ValueError, match="Too many recursive entries"):
        preview(parent, recursive=True)
    monkeypatch.setattr(media_sort, "MAX_RECURSIVE_ENTRIES", 50_000)
    monkeypatch.setattr(media_sort, "MAX_RECURSIVE_DIRECTORIES", 1)
    with pytest.raises(ValueError, match="Too many directories"):
        preview(parent, recursive=True)
    assert not (parent / "P").exists()
    assert not (leaf / "V").exists()


def test_api_recursive_option_and_suffixed_paths(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    config = tmp_path / "config"
    nested = data / "a" / "b"
    nested.mkdir(parents=True)
    config.mkdir()
    (data / "photo.jpg").write_bytes(b"photo")
    (nested / "video.mp4").write_bytes(b"video")
    (nested / "V").mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        default = client.post("/api/media-sort/preview", json={"parent": str(data)})
        assert default.status_code == 200, default.text
        assert default.json()["recursive"] is False
        assert default.json()["count"] == 1
        response = client.post("/api/media-sort/preview", json={
            "parent": str(data), "recursive": True,
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recursive"] is True
        assert body["count"] == 2
        assert body["scanned_directories"] == 3
        assert str(nested / "V_1" / "video.mp4") in [row["target"] for row in body["items"]]
        assert client.post("/api/media-sort/preview", json={
            "parent": str(data), "recursive": "yes",
        }).status_code == 422
        assert (nested / "video.mp4").read_bytes() == b"video"
        assert not (nested / "V_1").exists()
        plan = client.post("/api/plans", json={
            "name": "递归 P/V",
            "kind": "media-sort",
            "items": [
                {"operation": "move", "source": row["source"],
                 "target": row["target"], "expected_size": row["expected_size"]}
                for row in body["items"]
            ],
        })
        assert plan.status_code == 200, plan.text
        assert not (nested / "V_1").exists()
