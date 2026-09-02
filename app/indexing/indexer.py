from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable, Iterator

from app.path_safety import require_allowed_path


@dataclass(frozen=True)
class IndexedEntry:
    root_key: str
    absolute_path: Path
    relative_path: str
    basename: str
    stem: str
    suffix: str
    size: int
    mtime_ns: int
    device: int
    inode: int
    is_dir: bool


def _entry(root: Path, path: Path, root_key: str, *, is_dir: bool) -> IndexedEntry:
    stat = path.stat(follow_symlinks=False)
    return IndexedEntry(
        root_key=root_key,
        absolute_path=path,
        relative_path=path.relative_to(root).as_posix(),
        basename=path.name,
        stem=path.stem,
        suffix=path.suffix,
        size=0 if is_dir else stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        device=stat.st_dev,
        inode=stat.st_ino,
        is_dir=is_dir,
    )


def iter_root(
    root: Path | str,
    allowed_roots: Iterable[Path | str],
    *,
    root_key: str | None = None,
) -> Iterator[IndexedEntry]:
    safe_root = require_allowed_path(root, allowed_roots)
    if not safe_root.is_dir():
        raise ValueError(f"Scan root is not a directory: {safe_root}")
    key = root_key or safe_root.name

    for current, dirnames, filenames in os.walk(safe_root, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            path = current_path / name
            if path.is_symlink():
                continue
            try:
                yield _entry(safe_root, path, key, is_dir=True)
            except OSError:
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in sorted(filenames):
            path = current_path / name
            if path.is_symlink():
                continue
            try:
                yield _entry(safe_root, path, key, is_dir=False)
            except OSError:
                continue


def scan_root(
    root: Path | str,
    allowed_roots: Iterable[Path | str],
    *,
    root_key: str | None = None,
) -> list[IndexedEntry]:
    entries = list(iter_root(root, allowed_roots, root_key=root_key))
    entries.sort(key=lambda item: item.relative_path)
    return entries
