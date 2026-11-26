"""End-to-end checks for real MP4 video files downloaded without a suffix."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture


def _make_mp4(path: Path, *, source: str, codec: str, stream: str) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("This test requires ffmpeg and ffprobe")
    subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", source, "-t", "0.2", f"-c:{stream}", codec, "-f", "mp4", str(path)],
        check=True,
        capture_output=True,
        timeout=10,
    )
    return path.read_bytes()


@pytest.mark.parametrize("mixed_media", [False, True])
def test_extensionless_mp4_is_organized_with_the_authors_numbered_videos(tmp_path, mixed_media):
    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2610/261019/示例作者"
    for work in ("场景甲", "场景乙"):
        folder = author / work
        folder.mkdir(parents=True)
        (folder / "001.jpg").write_bytes(b"kept")
    (author / "001.mp4").write_bytes(b"numbered")
    video = _make_mp4(author / "原片", source="color=s=16x16:r=10", codec="mpeg4", stream="v")
    audio = _make_mp4(author / "录音", source="anullsrc=r=44100", codec="aac", stream="a")
    (author / "说明").write_text("Leave this file in place", encoding="utf-8")
    if mixed_media:
        (author / "封面.jpg").write_bytes(b"photo")

    preview = _preview(client, settings, author)
    row, = (row for row in preview["units"] if row["unit"] == str(author))
    assert row["status"] == "ready"
    assert any(Path(move["target"]).name == "002.mp4" for move in row["sample_moves"])
    assert row["totals"] == {"P": int(mixed_media), "V": 2, "Other": 2}
    video_dir = author
    if mixed_media:
        group, = (group for group in row["groups"] if group["kind"] == "V")
        assert group["count"] == 2
        video_dir /= group["name"]

    job = _batch(client, preview)
    assert _run_next(settings, job)
    batch = client.get(f"/api/media-organizer/batches/{job}").json()
    assert batch["summary"]["success_count"] == 1
    assert not (author / "原片").exists()
    assert (video_dir / "001.mp4").read_bytes() == b"numbered"
    assert (video_dir / "002.mp4").read_bytes() == video
    assert (author / "录音").read_bytes() == audio
    assert (author / "说明").read_text(encoding="utf-8") == "Leave this file in place"

    fresh = _preview(client, settings, author)
    assert fresh["summary"]["already_organized_count"] == 3
    assert fresh["summary"]["ready_count"] == fresh["summary"]["blocked_count"] == 0


def test_changed_extensionless_video_conflicts_before_publishing(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    work.mkdir()
    source = work / "原片"
    original = _make_mp4(source, source="color=s=16x16:r=10", codec="mpeg4", stream="v")

    preview = _preview(client, settings, work)
    row, = preview["units"]
    assert row["totals"]["V"] == 1

    info = source.stat()
    replacement = b"x" * len(original)
    source.write_bytes(replacement)
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))

    job = _batch(client, preview)
    assert _run_next(settings, job)
    result = client.get(f"/api/media-organizer/batches/{job}").json()
    assert result["summary"]["conflict_count"] == 1
    assert source.read_bytes() == replacement
    assert list(work.iterdir()) == [source]
