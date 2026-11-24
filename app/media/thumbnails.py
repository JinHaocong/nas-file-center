"""Authenticated media previews. All file reads are bounded and descriptor-bound."""
from __future__ import annotations

from functools import lru_cache
from hashlib import blake2s
from io import BytesIO
from itertools import islice
import os
from pathlib import Path
import stat
import subprocess
from threading import BoundedSemaphore
from typing import Iterator

from PIL import Image, ImageOps

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_naming import MEDIA_BUCKET_PATTERN
from app.config import Settings
from app.filters.excludes import DEFAULT_EXCLUDE_DIR_NAMES
from app.path_safety import UnsafePathError, require_allowed_path, require_unreserved_path


MAX_EDGE = 480
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 32_000_000
MAX_VIDEO_PREFIX = 8 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 512
MAX_CANDIDATES = 4
MAX_BUCKETS = 2
_DECODE_SLOTS = BoundedSemaphore(3)
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_VIDEO_DEMUXERS = {
    ".mp4": "mov", ".mov": "mov", ".m4v": "mov", ".3gp": "mov",
    ".mkv": "matroska", ".webm": "matroska", ".avi": "avi",
    ".ts": "mpegts", ".mts": "mpegts", ".m2ts": "mpegts",
}
_RESERVED = frozenset(name.casefold() for name in DEFAULT_EXCLUDE_DIR_NAMES)
_Identity = tuple[int, int, int, int, int]


class ThumbnailBusy(Exception):
    """The process is already servicing its preview budget."""


class ThumbnailUnavailable(Exception):
    """The source cannot produce a bounded, readable thumbnail."""


def _guard(path: Path, settings: Settings) -> None:
    """Require a literal allowed path and keep application workspaces private."""
    if not path.is_absolute() or ".." in path.parts or any(
        part.casefold().startswith(".nfc-") or part.casefold() in _RESERVED for part in path.parts
    ):
        raise UnsafePathError("Invalid thumbnail location")
    canonical = require_unreserved_path(require_allowed_path(path, settings.allowed_roots), settings.quarantine_root)
    if path != canonical or path.is_relative_to(settings.config_dir.resolve()):
        raise UnsafePathError("Invalid thumbnail location")


def _suffix(path: Path) -> str:
    # Some NAS exports use the extension itself as the entire video basename.
    return (path.suffix or path.name).casefold()


def _identity(info: os.stat_result) -> _Identity:
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise ThumbnailUnavailable
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _source_identity(path: Path) -> _Identity:
    parent = _open_directory_nofollow(path.parent)
    try:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if info.st_dev != os.fstat(parent).st_dev:
            raise ThumbnailUnavailable
        return _identity(info)
    finally:
        os.close(parent)


def _list_candidates(folder: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Inspect a bounded directory slice without following entry symlinks."""
    photos: list[Path] = []
    videos: list[Path] = []
    buckets: list[Path] = []
    fd = _open_directory_nofollow(folder)
    try:
        device = os.fstat(fd).st_dev
        with os.scandir(fd) as entries:
            for entry in islice(entries, MAX_DIRECTORY_ENTRIES):
                path = folder / entry.name
                suffix = _suffix(path)
                if suffix in _IMAGE_SUFFIXES or suffix in _VIDEO_DEMUXERS:
                    if entry.is_file(follow_symlinks=False):
                        sources = photos if suffix in _IMAGE_SUFFIXES else videos
                        sources.append(path)
                elif (entry.name.casefold() in {"p", "v"} or MEDIA_BUCKET_PATTERN.fullmatch(entry.name)):
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode) and info.st_dev == device:
                        buckets.append(path)
    finally:
        os.close(fd)
    for candidates in (photos, videos, buckets):
        candidates.sort(key=lambda path: (path.name.casefold(), path.name))
    return photos, videos, buckets


def _cover_candidates(folder: Path, settings: Settings) -> Iterator[Path]:
    photos, videos, buckets = _list_candidates(folder)
    yield from photos
    for bucket in buckets[:MAX_BUCKETS]:
        try:
            _guard(bucket, settings)
            photos, bucket_videos, _ = _list_candidates(bucket)
        except (OSError, UnsafePathError):
            continue
        yield from photos
        videos.extend(bucket_videos)
    # Limit video decoding to one attempt after inexpensive stills, including
    # photos inside the organizer's standard P buckets.
    yield from videos[:1]


def _image_jpeg(raw: bytes) -> bytes:
    # Restrict Pillow to self-contained raster decoders. Never hand it a file
    # name or copy source profiles, EXIF, comments or other source metadata.
    with Image.open(BytesIO(raw), formats=("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF")) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ThumbnailUnavailable
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        with ImageOps.exif_transpose(image) as oriented, oriented.convert("RGBA") as rgba:
            with Image.new("RGB", rgba.size, "white") as thumb, BytesIO() as output:
                thumb.paste(rgba, mask=rgba.getchannel("A"))
                thumb.save(output, format="JPEG", quality=80)
                return output.getvalue()


def _video_jpeg(raw: bytes, demuxer: str) -> bytes:
    # Only the already-bound source prefix reaches the decoder. No file or
    # network protocol is available to a container that references other data.
    result = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-max_alloc", "67108864",
        "-threads", "1", "-max_pixels", str(MAX_IMAGE_PIXELS), "-probesize", "1048576",
        "-analyzeduration", "1000000", "-protocol_whitelist", "pipe", "-f", demuxer, "-i", "pipe:0",
        "-map", "0:v:0", "-an", "-sn", "-dn", "-frames:v", "1", "-filter_threads", "1",
        "-vf", f"scale='min(iw,{MAX_EDGE})':'min(ih,{MAX_EDGE})':force_original_aspect_ratio=decrease",
        "-threads", "1", "-c:v", "mjpeg", "-q:v", "4", "-f", "image2pipe", "pipe:1",
    ], input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=4, check=False)
    if result.returncode or not result.stdout:
        raise ThumbnailUnavailable
    return result.stdout


@lru_cache(maxsize=96)
def _render(path: Path, identity: _Identity) -> bytes:
    """Keep only small encoded results, keyed by the live source identity."""
    suffix = _suffix(path)
    is_photo = suffix in _IMAGE_SUFFIXES
    if (not is_photo and suffix not in _VIDEO_DEMUXERS) or (is_photo and identity[2] > MAX_IMAGE_BYTES):
        raise ThumbnailUnavailable

    parent = _open_directory_nofollow(path.parent)
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path.name, flags, dir_fd=parent)
        try:
            if _identity(os.fstat(fd)) != identity:
                raise ThumbnailUnavailable
            size = identity[2] if is_photo else min(identity[2], MAX_VIDEO_PREFIX)
            with os.fdopen(fd, "rb", closefd=False) as source:
                raw = source.read(size)
            if len(raw) != size or _identity(os.fstat(fd)) != identity:
                raise ThumbnailUnavailable
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    return _image_jpeg(raw) if is_photo else _video_jpeg(raw, _VIDEO_DEMUXERS[suffix])


def load_thumbnail(requested: str, directory: bool, settings: Settings) -> tuple[bytes, str]:
    """Read a preview of one file or one representative media file in a directory."""
    path = Path(requested)
    _guard(path, settings)
    if not _DECODE_SLOTS.acquire(timeout=1.0):
        raise ThumbnailBusy
    try:
        candidates = _cover_candidates(path, settings) if directory else iter((path,))
        for source in islice(candidates, MAX_CANDIDATES):
            try:
                _guard(source, settings)
                identity = _source_identity(source)
                jpeg = _render(source, identity)
                # Reopen the literal path before handing even cached bytes to the caller.
                _guard(source, settings)
                if _source_identity(source) != identity:
                    continue
                token = blake2s(jpeg, digest_size=16).hexdigest()
                return jpeg, f'"{token}"'
            except (OSError, ValueError, RuntimeError, SyntaxError, Image.DecompressionBombError,
                    subprocess.TimeoutExpired, ThumbnailUnavailable):
                continue
    finally:
        _DECODE_SLOTS.release()
    raise ThumbnailUnavailable
