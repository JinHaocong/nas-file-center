from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import os
from pathlib import Path
import re

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mts", ".m2ts", ".webm", ".ts"}

STAT_SUFFIX_RE = re.compile(
    r"\s+\[(?:(?:\d+P(?:\s+\d+V)?)|(?:\d+V))?\s*\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB|PB)\]$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TreeStats:
    images: int
    videos: int
    files: int
    folders: int
    total_bytes: int


def format_size(total_bytes: int | float | None) -> str:
    """
    Format byte count into human-readable size string matching frontend formatBytes().
    Examples:
        0 -> '0 B'
        128 -> '128 B'
        1023 -> '1023 B'
        1024 -> '1.00 KB'
        3072 -> '3.00 KB'
        4224 -> '4.13 KB'
        7296 -> '7.13 KB'
        1024**2 -> '1.00 MB'
        1024**3 -> '1.00 GB'
        1024**4 -> '1.00 TB'
    """
    if not total_bytes:
        return "0 B"
    size = int(total_bytes)
    if size == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    val = Decimal(size)
    for i, unit in enumerate(units):
        if abs(val) < 1024 or i == len(units) - 1:
            if unit == "B":
                return f"{val} B"
            formatted = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return f"{formatted} {unit}"
        val /= 1024
    return f"{size} B"


def strip_trailing_stat_suffixes(name: str) -> str:
    value = name.rstrip()
    while True:
        stripped = STAT_SUFFIX_RE.sub("", value).rstrip()
        if stripped == value:
            return value
        value = stripped


def collect_tree_stats(path: Path | str, excluded_roots: Iterable[Path | str] | None = None) -> TreeStats:
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    resolved_excluded = [Path(ex).resolve(strict=False) for ex in (excluded_roots or ())]

    def _is_excluded(p: Path) -> bool:
        resolved = p.resolve(strict=False)
        for ex in resolved_excluded:
            if resolved == ex or resolved.is_relative_to(ex):
                return True
        return False

    images = videos = files = folders = total_bytes = 0
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            p = current_path / dirname
            if p.is_symlink() or _is_excluded(p):
                continue
            folders += 1
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            p = current_path / filename
            if p.is_symlink() or _is_excluded(p):
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
