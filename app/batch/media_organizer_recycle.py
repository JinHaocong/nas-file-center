"""Bind the organizer's read-only projection to explicitly reviewed recycle files."""
from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_recycle_rules import check
from app.batch.zspace_recycle import ZSpaceRecycleClient

if TYPE_CHECKING:
    from app.config import Settings

RECYCLE_DOWNLOAD_EXTRAS = "recycle_download_extras"
LEGACY_RECYCLE_PROBE_NAME = ".nfc-zspace-recycle-probe"
_RECYCLE_DIRS = frozenset({".recycle", "#recycle", "@recycle", "@eadir", "@recently-snapshot"})
_omitted: ContextVar[frozenset[Path]] = ContextVar("organizer_omitted_recycle_paths", default=frozenset())


@contextmanager
def omit_recycle_files(paths: frozenset[Path]) -> Iterator[None]:
    """Plan against the inventory that will exist after the reviewed recycle stage."""
    token = _omitted.set(paths)
    try:
        yield
    finally:
        _omitted.reset(token)


def omitted_from_organizer(path: Path) -> bool:
    return path in _omitted.get()


def organizer_omissions() -> frozenset[Path]:
    return _omitted.get()


def zspace_client(settings: Settings) -> ZSpaceRecycleClient | None:
    """An unconfigured deployment continues to use the existing organizer flow."""
    executable = settings.media_organizer_zspace_cli
    remote = settings.media_organizer_zspace_remote_root
    if executable is None and remote is None:
        return None
    if executable is None or not remote:
        raise ValueError("极空间回收需要完整的 CLI 和 NAS 个人空间映射配置")
    return ZSpaceRecycleClient(
        executable=executable, profile=settings.media_organizer_zspace_profile,
        local_root=settings.data_mount, remote_root=remote, cli_home=settings.media_organizer_zspace_cli_home,
    )


def _ignored(path: Path, quarantine: Path) -> bool:
    return path.is_relative_to(quarantine) or any(
        part.casefold().startswith(".nfc-") or part.casefold() in _RECYCLE_DIRS
        for part in path.parts
    )


def identity(info: os.stat_result) -> list[int]:
    """Bind a recycle receipt to exact source size, inode and metadata revisions."""
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def iter_recycle_candidates(selection: Path, settings: Settings, checkpoint: Callable[[], None]) -> Iterator[dict]:
    """Visit literal ordinary files on this mount, skipping recycle and system trees."""
    from app.batch.media_package_organizer import MAX_DEPTH, MAX_PACKAGE_FILES, MAX_SCOPE_ENTRIES_PER_DIRECTORY

    if not selection.is_relative_to(settings.data_mount) or _ignored(selection, settings.quarantine_root):
        return
    base_fd = _open_directory_nofollow(selection)
    try:
        device = os.fstat(base_fd).st_dev
    finally:
        os.close(base_fd)
    pending = [(selection, 0)]
    candidates = 0
    while pending:
        folder, depth = pending.pop()
        checkpoint()
        if depth > MAX_DEPTH:
            raise ValueError("附带文件回收扫描超过目录深度限制")
        fd = _open_directory_nofollow(folder)
        children = []
        try:
            if os.fstat(fd).st_dev != device:
                continue
            with os.scandir(fd) as entries:
                for count, entry in enumerate(entries, 1):
                    if count > MAX_SCOPE_ENTRIES_PER_DIRECTORY:
                        raise ValueError("附带文件回收扫描超过单目录条目限制")
                    if count % 256 == 0:
                        checkpoint()
                    path = folder / entry.name
                    if _ignored(path, settings.quarantine_root):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        children.append(path)
                        continue
                    if path.suffix.casefold() not in {".url", ".txt"}:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if info.st_dev != device or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        continue
                    reason = check(path, info)
                    if reason:
                        candidates += 1
                        if candidates > MAX_PACKAGE_FILES:
                            raise ValueError("待回收附带文件超过单次整理限制")
                        yield {
                            "unit": str(path), "status": "ready", "operation": RECYCLE_DOWNLOAD_EXTRAS,
                            "recycle_reason": reason, "recycle_identity": identity(info),
                            "total_bytes": info.st_size, "totals": {"P": 0, "V": 0, "Other": 0},
                        }
        finally:
            os.close(fd)
        pending.extend((child, depth + 1) for child in reversed(sorted(children)))
