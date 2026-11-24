"""Read-only image delivery through the authenticated media API."""
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
from threading import BoundedSemaphore

from PIL import Image
import pytest

from tests.test_media_package_execute_jobs import _fixture


@pytest.fixture
def media(tmp_path):
    client, settings, _ = _fixture(tmp_path, mutation=False, deletion=False)
    return client, settings


def photo(path: Path, color: str, size=(960, 480), *, orientation=1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[274] = orientation
    exif[315] = "private camera owner"
    Image.new("RGB", size, color).save(path, format="JPEG", exif=exif)
    return path


def fetch(client, path, *, kind="file", headers=None):
    return client.get("/api/media/thumbnail", params={"path": str(path), "kind": kind}, headers=headers)


def test_thumbnail_requires_a_session(media):
    client, settings = media
    path = photo(settings.data_mount / "private.jpg", "blue")
    response = fetch(client, path)
    assert response.status_code == 200
    client.cookies.clear()
    assert fetch(client, path, headers={"If-None-Match": response.headers["etag"]}).status_code == 401


def test_thumbnail_is_resized_oriented_and_stripped_of_source_metadata(media):
    client, settings = media
    path = photo(settings.data_mount / "001.JFIF", "red", orientation=6)
    source_bytes = path.read_bytes()
    response = fetch(client, path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-cache"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["vary"] == "Cookie"
    with Image.open(BytesIO(response.content)) as thumbnail:
        assert thumbnail.format == "JPEG" and thumbnail.size == (240, 480)
        assert not thumbnail.getexif()
    assert path.read_bytes() == source_bytes


def test_thumbnail_revalidates_replacement_before_using_browser_cache(media):
    client, settings = media
    path = photo(settings.data_mount / "001.jpg", "red")
    before = fetch(client, path)
    assert before.status_code == 200
    headers = {"If-None-Match": before.headers["etag"]}
    cached = fetch(client, path, headers=headers)
    assert cached.status_code == 304 and not cached.content
    photo(path.with_name("replacement.jpg"), "blue").replace(path)
    changed = fetch(client, path, headers=headers)
    assert changed.status_code == 200
    assert changed.headers["etag"] != before.headers["etag"]
    assert changed.content != before.content


def test_directory_uses_direct_media_or_one_organizer_bucket(media):
    client, settings = media
    work = settings.data_mount / "作品"
    direct = photo(work / "cover.jpg", "red")
    bucket = photo(work / "P [1 4KiB]" / "001.jpg", "blue")
    photo(work / "另一套作品" / "001.jpg", "green")
    assert fetch(client, work, kind="directory").content == fetch(client, direct).content
    direct.unlink()
    cover = fetch(client, work, kind="directory")
    assert cover.status_code == 200 and cover.content == fetch(client, bucket).content
    bucket.unlink()
    assert fetch(client, work, kind="directory").status_code == 404


def test_directory_finds_a_bucket_photo_before_decoding_video(media, monkeypatch):
    from app.media import thumbnails

    client, settings = media
    directory = settings.data_mount / "work"
    still = photo(directory / "P [1 4KiB]" / "001.jpg", "green")
    (directory / "clip.mov").write_bytes(b"incomplete")

    def unexpected_video_decode(*_args):
        pytest.fail("A video was decoded before an available still")

    monkeypatch.setattr(thumbnails, "_video_jpeg", unexpected_video_decode)
    cover = fetch(client, directory, kind="directory")
    assert cover.status_code == 200
    assert cover.content == fetch(client, still).content


def test_thumbnail_excludes_symlinks_quarantine_and_reserved_workspace(media, tmp_path):
    client, settings = media
    root = settings.data_mount
    target = photo(tmp_path / "outside" / "hidden.jpg", "red")
    (root / "alias.jpg").symlink_to(target)
    (root / "alias-folder").symlink_to(target.parent, target_is_directory=True)
    (root / "internal-alias.jpg").symlink_to(photo(root / "subdir" / "visible.jpg", "blue"))
    for path in (target, root / "alias.jpg", root / "alias-folder" / "hidden.jpg", root / "internal-alias.jpg",
                 photo(settings.quarantine_root / "trash.jpg", "black"),
                 photo(root / ".nfc-media-stage" / "hidden.jpg", "green"),
                 root / ".." / "outside" / "hidden.jpg"):
        assert fetch(client, path).status_code == 403
    assert fetch(client, root / "alias-folder", kind="directory").status_code == 403
    assert fetch(client, root, kind="directory").status_code == 404


def test_missing_unreadable_or_unbounded_media_returns_icon_fallback(media, monkeypatch):
    from app.media import thumbnails

    client, settings = media
    root = settings.data_mount
    damaged = root / "damaged.jpg"
    damaged.write_bytes(b"incomplete")
    assert fetch(client, damaged).status_code == 404
    assert fetch(client, root / "missing.png").status_code == 404
    assert fetch(client, root / "unrelated.txt").status_code == 404
    image = photo(root / "large.jpg", "teal")
    monkeypatch.setattr(thumbnails, "MAX_IMAGE_PIXELS", 100)
    assert fetch(client, image).status_code == 404


def test_special_files_and_oversized_images_never_reach_a_decoder(media, monkeypatch):
    from app.media import thumbnails

    client, settings = media
    pipe = settings.data_mount / "pipe.jpg"
    os.mkfifo(pipe)
    oversized = settings.data_mount / "oversized.jpg"
    with oversized.open("wb") as file:
        file.truncate(thumbnails.MAX_IMAGE_BYTES + 1)

    def unexpected_decode(*_args):
        pytest.fail("Ineligible file reached the image decoder")

    monkeypatch.setattr(thumbnails, "_image_jpeg", unexpected_decode)
    assert fetch(client, pipe).status_code == 404
    assert fetch(client, oversized).status_code == 404


def test_replacement_during_decoding_discards_stale_preview(media, monkeypatch):
    from app.media import thumbnails

    client, settings = media
    path = photo(settings.data_mount / "selected.jpg", "red")
    replacement = photo(settings.data_mount / "replacement.jpg", "blue")
    render = thumbnails._render

    def change_selection(source, identity):
        jpeg = render(source, identity)
        replacement.replace(source)
        return jpeg

    monkeypatch.setattr(thumbnails, "_render", change_selection)
    assert fetch(client, path).status_code == 404


def test_thumbnail_budget_returns_a_retryable_busy_response(media, monkeypatch):
    from app.media import thumbnails

    client, settings = media
    path = photo(settings.data_mount / "busy.jpg", "red")
    gate = BoundedSemaphore(1)
    monkeypatch.setattr(thumbnails, "_DECODE_SLOTS", gate)
    with gate:
        busy = fetch(client, path)
    assert busy.status_code == 503 and busy.headers["retry-after"] == "1"
    assert fetch(client, path).status_code == 200


def test_video_poster_is_a_single_jpeg_when_the_first_frame_is_available(media):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is not installed")
    client, settings = media
    path = settings.data_mount / "sample.mp4"
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=red:s=160x96:r=1", "-frames:v", "1", "-c:v", "mpeg4", "-movflags", "+faststart", str(path),
    ], check=True, timeout=10)
    response = fetch(client, path)
    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as thumbnail:
        assert thumbnail.format == "JPEG"
        assert thumbnail.width <= 480 and thumbnail.height <= 480
