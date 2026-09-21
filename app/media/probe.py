from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError


IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
})
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".mts",
    ".m2ts", ".wmv", ".flv", ".mpeg", ".mpg", ".3gp", ".ogv",
})

_MAX_PROBE_OUTPUT_BYTES = 256 * 1024
_HASH_CHUNK_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class MediaProbeResult:
    media_kind: str
    integrity_status: str
    integrity_reason_code: str | None = None
    integrity_detail: str | None = None
    width: int | None = None
    height: int | None = None
    format: str | None = None
    date_taken: str | None = None
    camera: str | None = None
    orientation: int | None = None
    duration_seconds: float | None = None
    codec: str | None = None
    bitrate: int | None = None
    fps: float | None = None
    audio_codec: str | None = None
    corrupt_sha256: str | None = None
    observed_device: int = 0
    observed_inode: int = 0
    observed_size: int = 0
    observed_mtime_ns: int = 0


def classify_media_kind(path: Path | str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def _mtime_ns(st: os.stat_result) -> int:
    return int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
        and int(left.st_dev) == int(right.st_dev)
        and int(left.st_ino) == int(right.st_ino)
        and int(left.st_size) == int(right.st_size)
        and _mtime_ns(left) == _mtime_ns(right)
    )


def _identity_result(result: MediaProbeResult, st: os.stat_result) -> MediaProbeResult:
    return replace(
        result,
        observed_device=int(st.st_dev),
        observed_inode=int(st.st_ino),
        observed_size=int(st.st_size),
        observed_mtime_ns=_mtime_ns(st),
    )


def _unknown(kind: str, code: str, detail: str | None = None) -> MediaProbeResult:
    return MediaProbeResult(
        media_kind=kind,
        integrity_status="unknown",
        integrity_reason_code=code,
        integrity_detail=detail,
    )


def _corrupt(kind: str, code: str, detail: str | None = None, **kwargs: Any) -> MediaProbeResult:
    return MediaProbeResult(
        media_kind=kind,
        integrity_status="corrupt",
        integrity_reason_code=code,
        integrity_detail=detail,
        **kwargs,
    )


def _healthy(kind: str, **kwargs: Any) -> MediaProbeResult:
    return MediaProbeResult(media_kind=kind, integrity_status="healthy", **kwargs)


def _normalize_exif_datetime(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def _camera_name(make: Any, model: Any) -> str | None:
    parts: list[str] = []
    for value in (make, model):
        if isinstance(value, str):
            cleaned = " ".join(value.strip().split())
            if cleaned and cleaned not in parts:
                parts.append(cleaned)
    return " ".join(parts) if parts else None


def probe_image(path: Path | str) -> MediaProbeResult:
    source = Path(path)
    try:
        with Image.open(source) as image:
            width, height = map(int, image.size)
            image_format = str(image.format) if image.format else None
            exif = image.getexif()
            date_taken = _normalize_exif_datetime(
                exif.get(36867) or exif.get(36868) or exif.get(306)
            )
            camera = _camera_name(exif.get(271), exif.get(272))
            raw_orientation = exif.get(274)
            orientation = (
                int(raw_orientation)
                if isinstance(raw_orientation, (int, float))
                and 1 <= int(raw_orientation) <= 8
                else None
            )
            image.verify()

        # verify() checks container structure without decoding all pixel data.
        # Reopen and load one decoded image/frame so truncated payloads fail.
        with Image.open(source) as decoded:
            decoded.load()

        if width <= 0 or height <= 0:
            return _corrupt(
                "image",
                "IMAGE_IMPOSSIBLE_METADATA",
                f"invalid dimensions {width}x{height}",
                width=width,
                height=height,
                format=image_format,
                date_taken=date_taken,
                camera=camera,
                orientation=orientation,
            )
        return _healthy(
            "image",
            width=width,
            height=height,
            format=image_format,
            date_taken=date_taken,
            camera=camera,
            orientation=orientation,
        )
    except (FileNotFoundError, PermissionError) as exc:
        return _unknown("image", "IMAGE_SOURCE_UNAVAILABLE", str(exc))
    except Image.DecompressionBombError as exc:
        return _unknown("image", "IMAGE_RESOURCE_LIMIT", str(exc))
    except UnidentifiedImageError as exc:
        return _corrupt("image", "IMAGE_DECODE_FAILED", str(exc))
    except OSError as exc:
        # Pillow also uses OSError for host/runtime failures (EIO, ESTALE,
        # descriptor exhaustion, etc.). Only message patterns that identify a
        # deterministic decoder/container failure are allowed to mint corrupt
        # deletion authority. System errno or ambiguous decoder failures stay
        # unknown and therefore cannot be permanently deleted via Gate6-D.
        lowered = str(exc).lower()
        deterministic_decode_markers = (
            "truncated",
            "broken data stream",
            "not enough image data",
            "decoder error",
            "cannot decode",
            "invalid image",
        )
        if exc.errno is None and any(marker in lowered for marker in deterministic_decode_markers):
            return _corrupt("image", "IMAGE_DECODE_FAILED", str(exc))
        return _unknown("image", "IMAGE_DECODE_AMBIGUOUS", str(exc))
    except (SyntaxError, ValueError) as exc:
        return _corrupt("image", "IMAGE_DECODE_FAILED", str(exc))


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_rate(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in {"N/A", "0/0"}:
        return None
    if "/" in raw:
        left, right = raw.split("/", 1)
        try:
            denominator = float(right)
            if denominator == 0:
                return None
            rate = float(left) / denominator
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    else:
        rate = _parse_float(raw)
        if rate is None:
            return None
    return rate if math.isfinite(rate) else None


def parse_ffprobe_payload(payload: dict[str, Any]) -> MediaProbeResult:
    streams = payload.get("streams")
    fmt = payload.get("format")
    if not isinstance(streams, list):
        return _unknown("video", "FFPROBE_OUTPUT_INVALID", "streams is not an array")
    if not isinstance(fmt, dict):
        fmt = {}

    video_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
        None,
    )

    if video_stream is None:
        return _unknown("video", "VIDEO_STREAM_NOT_FOUND", "ffprobe found no video stream")

    width = _parse_int(video_stream.get("width"))
    height = _parse_int(video_stream.get("height"))
    codec = video_stream.get("codec_name")
    codec = str(codec) if codec else None
    audio_codec = audio_stream.get("codec_name") if isinstance(audio_stream, dict) else None
    audio_codec = str(audio_codec) if audio_codec else None

    duration = _parse_float(video_stream.get("duration"))
    if duration is None:
        duration = _parse_float(fmt.get("duration"))

    bitrate = _parse_int(video_stream.get("bit_rate"))
    if bitrate is None:
        bitrate = _parse_int(fmt.get("bit_rate"))

    fps = _parse_rate(video_stream.get("avg_frame_rate"))
    if fps is None:
        fps = _parse_rate(video_stream.get("r_frame_rate"))

    format_name = fmt.get("format_name")
    format_name = str(format_name) if format_name else None

    impossible = (
        (width is not None and width <= 0)
        or (height is not None and height <= 0)
        or (duration is not None and duration < 0)
        or (bitrate is not None and bitrate < 0)
        or (fps is not None and fps < 0)
    )
    if impossible:
        return _corrupt(
            "video",
            "VIDEO_IMPOSSIBLE_METADATA",
            "ffprobe returned impossible video metadata",
            width=width,
            height=height,
            format=format_name,
            duration_seconds=duration,
            codec=codec,
            bitrate=bitrate,
            fps=fps,
            audio_codec=audio_codec,
        )

    return _healthy(
        "video",
        width=width,
        height=height,
        format=format_name,
        duration_seconds=duration,
        codec=codec,
        bitrate=bitrate,
        fps=fps,
        audio_codec=audio_codec,
    )


def run_ffprobe(
    path: Path | str,
    *,
    binary: str = "ffprobe",
    timeout_seconds: float = 30.0,
    checkpoint: Callable[[], None] | None = None,
) -> MediaProbeResult:
    command = [
        binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "format=duration,bit_rate,format_name:"
        "stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration,bit_rate",
        os.fspath(path),
    ]

    # ffprobe output is redirected into bounded temporary files instead of
    # subprocess.PIPE. communicate() can accumulate arbitrary output in RAM
    # before a post-hoc size check; this loop observes file sizes while the
    # child is running and terminates it as soon as either stream exceeds the
    # Gate6-D output budget.
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        try:
            proc = subprocess.Popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                text=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            return _unknown("video", "FFPROBE_UNAVAILABLE", str(exc))
        except OSError as exc:
            return _unknown("video", "FFPROBE_START_FAILED", str(exc))

        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        try:
            while proc.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    proc.kill()
                    proc.wait()
                    return _unknown("video", "FFPROBE_TIMEOUT", "ffprobe timed out")

                stdout_size = os.fstat(stdout_file.fileno()).st_size
                stderr_size = os.fstat(stderr_file.fileno()).st_size
                if (
                    stdout_size > _MAX_PROBE_OUTPUT_BYTES
                    or stderr_size > _MAX_PROBE_OUTPUT_BYTES
                ):
                    proc.kill()
                    proc.wait()
                    return _unknown(
                        "video",
                        "FFPROBE_OUTPUT_TOO_LARGE",
                        "ffprobe output exceeded limit",
                    )

                try:
                    proc.wait(timeout=min(0.25, remaining))
                except subprocess.TimeoutExpired:
                    if checkpoint is not None:
                        checkpoint()
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            raise

        stdout_size = os.fstat(stdout_file.fileno()).st_size
        stderr_size = os.fstat(stderr_file.fileno()).st_size
        if (
            stdout_size > _MAX_PROBE_OUTPUT_BYTES
            or stderr_size > _MAX_PROBE_OUTPUT_BYTES
        ):
            return _unknown(
                "video",
                "FFPROBE_OUTPUT_TOO_LARGE",
                "ffprobe output exceeded limit",
            )

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(_MAX_PROBE_OUTPUT_BYTES + 1).decode(
            "utf-8", errors="replace"
        )
        stderr = stderr_file.read(_MAX_PROBE_OUTPUT_BYTES + 1).decode(
            "utf-8", errors="replace"
        )

    if proc.returncode != 0:
        lowered = stderr.lower()
        unavailable_markers = (
            "permission denied",
            "operation not permitted",
            "no such file",
            "resource temporarily unavailable",
            "device or resource busy",
            "input/output error",
            "stale file handle",
            "too many open files",
            "cannot allocate memory",
            "interrupted system call",
            "timed out",
        )
        if any(marker in lowered for marker in unavailable_markers):
            return _unknown("video", "VIDEO_SOURCE_UNAVAILABLE", stderr.strip() or None)

        deterministic_invalid_data_markers = (
            "invalid data found when processing input",
            "moov atom not found",
            "invalid atom size",
            "error reading header",
        )
        if any(marker in lowered for marker in deterministic_invalid_data_markers):
            return _corrupt(
                "video",
                "FFPROBE_FAILED",
                stderr.strip() or f"ffprobe exit {proc.returncode}",
            )

        # A generic non-zero ffprobe exit is not enough evidence to grant
        # irreversible deletion authority. Unsupported runtime conditions,
        # transient decoder/library errors and other ambiguous failures remain
        # unknown unless they match a deterministic invalid-data signature.
        return _unknown(
            "video",
            "FFPROBE_FAILED_AMBIGUOUS",
            stderr.strip() or f"ffprobe exit {proc.returncode}",
        )

    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        return _unknown("video", "FFPROBE_OUTPUT_INVALID", str(exc))
    if not isinstance(payload, dict):
        return _unknown("video", "FFPROBE_OUTPUT_INVALID", "top-level ffprobe JSON is not an object")
    return parse_ffprobe_payload(payload)


def _sha256_bound_regular(path: Path, expected: os.stat_result) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    digest = hashlib.sha256()
    try:
        before = os.fstat(fd)
        if not _same_identity(expected, before):
            raise RuntimeError("source identity changed before hash")
        while True:
            chunk = os.read(fd, _HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        if not _same_identity(expected, after):
            raise RuntimeError("source identity changed during hash")
    finally:
        os.close(fd)
    return digest.hexdigest()


def probe_media_file(
    path: Path | str,
    *,
    kind: str | None = None,
    ffprobe_binary: str = "ffprobe",
    checkpoint: Callable[[], None] | None = None,
) -> MediaProbeResult:
    source = Path(path)
    media_kind = kind or classify_media_kind(source)
    if media_kind not in {"image", "video"}:
        return _unknown("unknown", "UNSUPPORTED_MEDIA_TYPE", source.suffix.lower())

    try:
        before = os.lstat(source)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return _unknown(media_kind, "MEDIA_SOURCE_UNAVAILABLE", str(exc))
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        return _unknown(media_kind, "MEDIA_SOURCE_NOT_REGULAR", "source is not a regular file")

    if media_kind == "image":
        result = probe_image(source)
    else:
        result = run_ffprobe(
            source,
            binary=ffprobe_binary,
            checkpoint=checkpoint,
        )

    try:
        after_probe = os.lstat(source)
    except OSError as exc:
        return _identity_result(
            _unknown(media_kind, "SOURCE_CHANGED_DURING_PROBE", str(exc)),
            before,
        )

    if not _same_identity(before, after_probe):
        return _identity_result(
            _unknown(media_kind, "SOURCE_CHANGED_DURING_PROBE", "source identity changed"),
            before,
        )

    result = _identity_result(result, before)

    if result.integrity_status != "corrupt":
        return result

    try:
        content_hash = _sha256_bound_regular(source, before)
        after_hash = os.lstat(source)
    except (OSError, RuntimeError) as exc:
        return _identity_result(
            _unknown(media_kind, "SOURCE_CHANGED_DURING_PROBE", str(exc)),
            before,
        )

    if not _same_identity(before, after_hash):
        return _identity_result(
            _unknown(media_kind, "SOURCE_CHANGED_DURING_PROBE", "source identity changed after hash"),
            before,
        )

    return replace(result, corrupt_sha256=content_hash)
