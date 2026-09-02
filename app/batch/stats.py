from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mts", ".m2ts", ".webm", ".ts"}

STAT_SUFFIX_RE = re.compile(
    r"\s+\[(?:(?:\d+P(?:\s+\d+V)?)|(?:\d+V))?\s*\d+(?:\.\d+)?(?:KB|MB|GB|TB)\]$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TreeStats:
    images: int
    videos: int
    files: int
    folders: int
    total_bytes: int


def format_size(total_bytes: int) -> str:
    if total_bytes >= 1024**4:
        return f"{total_bytes / 1024**4:.2f}TB"
    if total_bytes >= 1024**3:
        return f"{total_bytes / 1024**3:.2f}GB"
    return f"{total_bytes / 1024**2:.1f}MB"


def strip_trailing_stat_suffixes(name: str) -> str:
    value = name.rstrip()
    while True:
        stripped = STAT_SUFFIX_RE.sub("", value).rstrip()
        if stripped == value:
            return value
        value = stripped


def collect_tree_stats(path: Path | str) -> TreeStats:
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    images = videos = files = folders = total_bytes = 0
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            p = current_path / dirname
            if p.is_symlink():
                continue
            folders += 1
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            p = current_path / filename
            if p.is_symlink():
                continue
            try:
                stat = p.stat(follow_symlinks=False)
            except OSError:
                continue
            files += 1
            total_bytes += stat.st_size
            suffix = p.suffix.lower()
            if suffix in IMAGE_EXTENSIONS:
                images += 1
            if suffix in VIDEO_EXTENSIONS:
                videos += 1
    return TreeStats(images=images, videos=videos, files=files, folders=folders, total_bytes=total_bytes)


def render_stat_name(name: str, stats: TreeStats, *, template: str) -> str:
    base_name = strip_trailing_stat_suffixes(name)
    values = {
        "name": base_name,
        "images": stats.images,
        "videos": stats.videos,
        "files": stats.files,
        "folders": stats.folders,
        "size": format_size(stats.total_bytes),
    }
    return template.format_map(values)
