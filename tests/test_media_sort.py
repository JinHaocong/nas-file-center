"""P/V media sorting stays a read-only one-level preview until a Move Plan executes."""
from pathlib import Path

import pytest

from app.batch import media_sort
from app.batch.media_sort import preview_media_sort


def preview(parent: Path, *, roots=None, trash=None):
    return preview_media_sort(
        parent,
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


def test_existing_pv_dirs_and_casefold_conflicts(tmp_path):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "Photo.JPG").write_bytes(b"source")
    (parent / "movie.mp4").write_bytes(b"video")
    (parent / "P").mkdir()
    (parent / "V").mkdir()
    (parent / "P" / "photo.jpg").write_bytes(b"existing")
    (parent / "V" / "other.mp4").write_bytes(b"other")

    result = preview(parent)
    assert result["conflict_count"] == 1
    assert result["ready_count"] == 1
    photo = next(row for row in result["items"] if row["media_kind"] == "image")
    movie = next(row for row in result["items"] if row["media_kind"] == "video")
    assert photo["conflict"] is True
    assert "collides" in photo["conflict_reason"]
    assert movie["conflict"] is False
    assert (parent / "P" / "photo.jpg").read_bytes() == b"existing"


@pytest.mark.parametrize("occupant", ["file", "symlink"])
def test_rejects_unsafe_target_parent(tmp_path, occupant):
    parent = tmp_path / "mixed"
    parent.mkdir()
    (parent / "image.png").write_bytes(b"image")
    (parent / "video.mp4").write_bytes(b"video")
    target = parent / "P"
    if occupant == "file":
        target.write_bytes(b"not a directory")
    else:
        target.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ValueError, match="real directory"):
        preview(parent)
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
