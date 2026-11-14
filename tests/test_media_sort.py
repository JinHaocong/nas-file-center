"""P/V media sorting stays a read-only one-level preview until a Move Plan executes."""
from pathlib import Path

import pytest

from app.batch import media_sort
from app.batch.media_sort import preview_media_sort


def preview(parent: Path, *, roots=None, trash=None, recursive=False, smart_skip=True):
    return preview_media_sort(
        parent,
        recursive=recursive,
        smart_skip=smart_skip,
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

    result = preview(parent, recursive=True, smart_skip=False)
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

    result = preview(parent, smart_skip=False)
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

    result = preview(parent, recursive=True, trash=trash, smart_skip=False)
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
    result = preview(parent, smart_skip=False)
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
        default = client.post("/api/media-sort/preview", json={"parent": str(data), "smart_skip": False})
        assert default.status_code == 200, default.text
        assert default.json()["recursive"] is False
        assert default.json()["count"] == 1
        response = client.post("/api/media-sort/preview", json={
            "parent": str(data), "recursive": True, "smart_skip": False,
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


def test_recursive_move_plan_executes_with_per_directory_suffixes(tmp_path):
    """The ordinary Move Plan must actually create each local target, not flatten."""
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from app.worker import process_work_job

    data = tmp_path / "data"
    config = tmp_path / "config"
    album = data / "Album"
    album.mkdir(parents=True)
    config.mkdir()
    (data / "cover.jpg").write_bytes(b"cover")
    (album / "Photo.jpg").write_bytes(b"photo-upper")
    (album / "photo.JPG").write_bytes(b"photo-lower")
    (album / "clip.MP4").write_bytes(b"clip")
    (album / "P").mkdir()
    (album / "P" / "old.jpg").write_bytes(b"old")
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=True, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        preview_resp = client.post("/api/media-sort/preview", json={
            "parent": str(data), "recursive": True, "smart_skip": False,
        })
        assert preview_resp.status_code == 200, preview_resp.text
        preview_rows = preview_resp.json()["items"]
        assert len(preview_rows) == 4
        assert not any(row["conflict"] for row in preview_rows)
        created = client.post("/api/plans", json={
            "name": "Recursive P/V execution",
            "kind": "media-sort",
            "items": [
                {"operation": "move", "source": row["source"],
                 "target": row["target"], "expected_size": row["expected_size"]}
                for row in preview_rows
            ],
        })
        assert created.status_code == 200, created.text
        plan_id = created.json()["id"]
        assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
        validated = client.post(f"/api/plans/{plan_id}/validate")
        assert validated.status_code == 200, validated.text
        job = client.post(f"/api/plans/{plan_id}/execute")
        assert job.status_code == 200, job.text
        process_work_job(settings, job.json()["work_job_id"])
        assert client.get(f"/api/plans/{plan_id}").json()["status"] == "completed"
        assert (data / "P" / "cover.jpg").read_bytes() == b"cover"
        assert (album / "P" / "old.jpg").read_bytes() == b"old"
        assert (album / "V" / "clip.MP4").read_bytes() == b"clip"
        pictures = sorted((album / "P_1").iterdir())
        assert len(pictures) == 2
        assert {item.read_bytes() for item in pictures} == {b"photo-upper", b"photo-lower"}
        assert len({item.name.casefold() for item in pictures}) == 2
        assert not (album / "Photo.jpg").exists()
        assert not (album / "photo.JPG").exists()


def test_screenshot_scenario_keeps_chinese_video_and_lowercase_p_unchanged(tmp_path):
    """An already-sorted nonstandard folder must not get a nested V/V or P/P."""
    root = tmp_path / "1.13G"
    videos = root / "视频"
    pictures = root / "p"
    videos.mkdir(parents=True)
    pictures.mkdir()
    (videos / "001.mp4").write_bytes(b"video")
    (videos / "002.MKV").write_bytes(b"movie")
    (pictures / "001.jpg").write_bytes(b"photo")
    (pictures / "002.png").write_bytes(b"pic")
    (root / ".DS_Store").write_bytes(b"metadata")

    result = preview(root, recursive=True)
    assert result["smart_skip"] is True
    assert result["scanned_directories"] == 2  # p is a known classification folder
    assert result["count"] == 0
    assert result["skipped_directory_count"] == 3
    reasons = {row["path"]: row["reason"] for row in result["skipped_directories"]}
    assert reasons == {
        str(root): "no_media",
        str(pictures): "preclassified",
        str(videos): "pure_videos",
    }
    assert (videos / "001.mp4").read_bytes() == b"video"
    assert (pictures / "001.jpg").read_bytes() == b"photo"
    assert not (videos / "V").exists()


def test_pure_media_with_system_sidecars_is_skipped_and_recurses_children(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    pure_image = root / "旅行照片"
    pure_image.mkdir()
    (pure_image / "01.jpg").write_bytes(b"image")
    (pure_image / ".DS_Store").write_bytes(b"meta")
    (pure_image / "Thumbs.DB").write_bytes(b"meta")
    child = pure_image / "mixed"
    child.mkdir()
    (child / "a.jpg").write_bytes(b"photo")
    (child / "a.mp4").write_bytes(b"video")
    pure_video = root / "电影"
    pure_video.mkdir()
    (pure_video / "01.mkv").write_bytes(b"movie")
    # A media-looking symlink cannot turn this into a mixed directory.
    (pure_video / "link.jpg").symlink_to(pure_image / "01.jpg")

    result = preview(root, recursive=True)
    assert result["count"] == 2
    assert {
        (Path(row["source"]).relative_to(root).as_posix(),
         Path(row["target"]).relative_to(root).as_posix())
        for row in result["items"]
    } == {
        ("旅行照片/mixed/a.jpg", "旅行照片/mixed/P/a.jpg"),
        ("旅行照片/mixed/a.mp4", "旅行照片/mixed/V/a.mp4"),
    }
    skipped = {row["path"]: row["reason"] for row in result["skipped_directories"]}
    assert skipped[str(pure_image)] == "pure_images"
    assert skipped[str(pure_video)] == "pure_videos"
    assert (pure_image / "01.jpg").read_bytes() == b"image"
    assert (pure_video / "01.mkv").read_bytes() == b"movie"


@pytest.mark.parametrize("other", ["subtitle.srt", "details.nfo", "notes.txt", "music.mp3"])
def test_non_system_files_prevent_false_pure_media_skip(tmp_path, other):
    root = tmp_path / "library"
    root.mkdir()
    (root / "movie.MP4").write_bytes(b"video")
    (root / other).write_bytes(b"sidecar")

    result = preview(root)
    assert result["count"] == 1
    assert result["video_count"] == 1
    assert result["skipped_directory_count"] == 0
    assert result["items"][0]["target"] == str(root / "V" / "movie.MP4")
    assert (root / other).read_bytes() == b"sidecar"


def test_smart_skip_can_be_disabled_to_preserve_original_classification(tmp_path):
    parent = tmp_path / "media"
    parent.mkdir()
    (parent / "01.JPG").write_bytes(b"image")
    (parent / "Thumbs.db").write_bytes(b"metadata")
    smart = preview(parent)
    assert smart["count"] == 0
    assert smart["skipped_directories"] == [{
        "path": str(parent), "reason": "pure_images",
        "image_count": 1, "video_count": 0,
    }]
    classic = preview(parent, smart_skip=False)
    assert classic["smart_skip"] is False
    assert classic["count"] == 1
    assert classic["items"][0]["target"] == str(parent / "P" / "01.JPG")
    assert classic["skipped_directory_count"] == 0
    assert not (parent / "P").exists()


def test_mixed_media_still_sorted_with_existing_pv_suffixes(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "old.jpg").write_bytes(b"picture")
    (parent / "old.mp4").write_bytes(b"movie")
    (parent / "P").mkdir()
    (parent / "V").mkdir()
    result = preview(parent, smart_skip=True)
    assert result["count"] == 2
    assert result["skipped_directory_count"] == 0
    assert {Path(row["target"]).relative_to(parent).as_posix()
            for row in result["items"]} == {"P_1/old.jpg", "V_1/old.mp4"}


def test_no_media_directory_still_recurses_into_mixed_grandchild(tmp_path):
    root = tmp_path / "root"
    grandchild = root / "empty-level" / "mixed"
    grandchild.mkdir(parents=True)
    (grandchild / "one.jpg").write_bytes(b"a")
    (grandchild / "one.mp4").write_bytes(b"b")
    result = preview(root, recursive=True)
    assert result["count"] == 2
    assert result["scanned_directories"] == 3
    reasons = {row["path"]: row["reason"] for row in result["skipped_directories"]}
    assert reasons[str(root)] == "no_media"
    assert reasons[str(grandchild.parent)] == "no_media"
    assert str(grandchild) not in reasons


def test_smart_skip_api_defaults_to_true_and_rejects_nonboolean(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    (data / "photo.jpg").write_bytes(b"pic")
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        smart = client.post("/api/media-sort/preview", json={"parent": str(data)})
        assert smart.status_code == 200, smart.text
        assert smart.json()["smart_skip"] is True
        assert smart.json()["count"] == 0
        assert smart.json()["skipped_directory_count"] == 1
        classic = client.post("/api/media-sort/preview", json={
            "parent": str(data), "smart_skip": False,
        })
        assert classic.status_code == 200
        assert classic.json()["count"] == 1
        assert client.post("/api/media-sort/preview", json={
            "parent": str(data), "smart_skip": "yes",
        }).status_code == 422
        assert client.post("/api/media-sort/preview", json={
            "parent": str(data), "smart_skip": 1,
        }).status_code == 422
        assert (data / "photo.jpg").read_bytes() == b"pic"
        assert not (data / "P").exists()
