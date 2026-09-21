import json
import os
from pathlib import Path

import pytest
from PIL import Image

from app.media.probe import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    classify_media_kind,
    parse_ffprobe_payload,
    probe_image,
    probe_media_file,
    run_ffprobe,
)


def test_media_candidate_classification_is_explicit():
    assert classify_media_kind(Path("/data/a.JPG")) == "image"
    assert classify_media_kind(Path("/data/a.mkv")) == "video"
    assert classify_media_kind(Path("/data/a.txt")) is None
    assert ".jpg" in IMAGE_EXTENSIONS
    assert ".mp4" in VIDEO_EXTENSIONS


def test_image_probe_extracts_metadata_and_is_healthy(tmp_path: Path):
    path = tmp_path / "photo.jpg"
    image = Image.new("RGB", (32, 24), (12, 34, 56))
    exif = Image.Exif()
    exif[271] = "OpenAI Camera Co"
    exif[272] = "Model X"
    exif[274] = 6
    exif[36867] = "2026:09:21 12:34:56"
    image.save(path, format="JPEG", exif=exif)

    result = probe_media_file(path, kind="image", ffprobe_binary="ffprobe")

    assert result.integrity_status == "healthy"
    assert result.width == 32
    assert result.height == 24
    assert result.format == "JPEG"
    assert result.camera == "OpenAI Camera Co Model X"
    assert result.orientation == 6
    assert result.date_taken == "2026-09-21T12:34:56"
    assert result.corrupt_sha256 is None


def test_truncated_supported_image_is_corrupt_and_gets_delete_authority_hash(tmp_path: Path):
    path = tmp_path / "broken.jpg"
    image = Image.new("RGB", (64, 64), (200, 100, 20))
    image.save(path, format="JPEG")
    raw = path.read_bytes()
    path.write_bytes(raw[: max(32, len(raw) // 3)])

    result = probe_media_file(path, kind="image", ffprobe_binary="ffprobe")

    assert result.integrity_status == "corrupt"
    assert result.integrity_reason_code == "IMAGE_DECODE_FAILED"
    assert result.corrupt_sha256 is not None
    assert len(result.corrupt_sha256) == 64


def test_parse_ffprobe_payload_extracts_video_metadata():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "duration": "12.5",
                "bit_rate": "8000000",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "12.5", "bit_rate": "8500000", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
    }

    result = parse_ffprobe_payload(payload)

    assert result.integrity_status == "healthy"
    assert result.width == 1920
    assert result.height == 1080
    assert result.codec == "h264"
    assert result.audio_codec == "aac"
    assert result.duration_seconds == pytest.approx(12.5)
    assert result.fps == pytest.approx(30000 / 1001)
    assert result.bitrate == 8000000


def test_parse_ffprobe_payload_rejects_impossible_video_dimensions():
    result = parse_ffprobe_payload(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 0,
                    "height": 1080,
                    "avg_frame_rate": "25/1",
                }
            ],
            "format": {},
        }
    )
    assert result.integrity_status == "corrupt"
    assert result.integrity_reason_code == "VIDEO_IMPOSSIBLE_METADATA"


def test_ffprobe_no_video_stream_is_unknown_not_corrupt():
    result = parse_ffprobe_payload(
        {
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "4.0"},
        }
    )
    assert result.integrity_status == "unknown"
    assert result.integrity_reason_code == "VIDEO_STREAM_NOT_FOUND"



def test_image_runtime_oserror_stays_unknown(monkeypatch, tmp_path: Path):
    path = tmp_path / "io.jpg"
    path.write_bytes(b"placeholder")

    def fail_open(*_args, **_kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("app.media.probe.Image.open", fail_open)
    result = probe_image(path)

    assert result.integrity_status == "unknown"
    assert result.integrity_reason_code == "IMAGE_DECODE_AMBIGUOUS"
    assert result.corrupt_sha256 is None


class _FakeFfprobeProcess:
    def __init__(self, stderr: str):
        self.returncode = 1
        self._stderr = stderr

    def communicate(self, timeout=None):
        return "", self._stderr

    def kill(self):
        return None

    def poll(self):
        return self.returncode


def test_ffprobe_ambiguous_nonzero_exit_stays_unknown(monkeypatch, tmp_path: Path):
    path = tmp_path / "ambiguous.mp4"
    path.write_bytes(b"x")

    monkeypatch.setattr(
        "app.media.probe.subprocess.Popen",
        lambda *_args, **_kwargs: _FakeFfprobeProcess("Unknown decoder library failure"),
    )
    result = run_ffprobe(path)

    assert result.integrity_status == "unknown"
    assert result.integrity_reason_code == "FFPROBE_FAILED_AMBIGUOUS"


def test_ffprobe_explicit_invalid_data_is_corrupt(monkeypatch, tmp_path: Path):
    path = tmp_path / "invalid.mp4"
    path.write_bytes(b"x")

    monkeypatch.setattr(
        "app.media.probe.subprocess.Popen",
        lambda *_args, **_kwargs: _FakeFfprobeProcess(
            "Invalid data found when processing input"
        ),
    )
    result = run_ffprobe(path)

    assert result.integrity_status == "corrupt"
    assert result.integrity_reason_code == "FFPROBE_FAILED"
