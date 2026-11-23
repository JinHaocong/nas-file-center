"""Scope-bound MOVE execution for an explicitly reviewed Luolcy assignment."""
from __future__ import annotations

import errno
import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_link_intent import LinkIntent
from app.batch.media_organizer_planner import is_reserved_workspace
from app.batch.media_package_execution import _retire_link
from app.batch.media_package_organizer import _validate_scope
from app.batch.plans import OperationItem
from app.config import Settings
from app.execution.executor import ItemResult
from app.fs_ops import rename_noreplace_at
from app.models import BatchPlanItem
from app.path_safety import is_reserved_quarantine_path

LUOLCY_ASSIGNMENT_KIND = "luolcy-author-assignment"


def _link_intent(settings: Settings, authority: dict) -> LinkIntent:
    assignment_id = authority["assignment_id"]
    if not re.fullmatch(r"[0-9a-f]{32}", assignment_id):
        raise ValueError("归属硬链接记录无效")
    return LinkIntent(settings.reports_dir / "luolcy-assignment-links" / f"{assignment_id}.json")


def _directory_identity(fd: int) -> list[int]:
    info = os.fstat(fd)
    return [info.st_dev, info.st_ino]


def _sync_new_package_parent(directory_fd: int) -> None:
    """Use directory sync when available before binding an exclusive new package."""
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP}:
            raise


def _verify_file(directory_fd: int, name: str, expected: list[int]) -> None:
    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns] != expected:
        raise ValueError(f"所选文件已经变化：{name}")


def _assignment_scope(item: OperationItem, authority: dict, settings: Settings) -> tuple[Path, Path, list[int]]:
    """Verify the frozen source row, exact same-name target and current Luolcy root."""
    if not isinstance(authority, dict) or settings.media_package_root is None:
        raise ValueError("缺少 Luolcy 散件归属记录")
    author, package = Path(authority["author"]), Path(authority["package"])
    _, depth = _validate_scope(author, media_package_root=settings.media_package_root,
                               allowed_roots=settings.allowed_roots, quarantine_root=settings.quarantine_root)
    sources = authority["sources"]
    if (depth != 3 or package.parent != author or package.name in {"", ".", ".."}
            or is_reserved_workspace(package) or is_reserved_quarantine_path(package, settings.quarantine_root)
            or item.operation != "move" or not 1 <= item.sequence <= len(sources)
            or item.source.parent != author or item.target != package / item.source.name):
        raise ValueError("散件归属路径超出已确认的作者或资源包范围")
    source, expected = sources[item.sequence - 1]
    if str(item.source) != source or expected != [item.expected_device, item.expected_inode,
                                                  item.expected_size, item.expected_mtime_ns]:
        raise ValueError("散件 MOVE 与已确认的源文件不一致")
    return author, package, expected


def has_replayable_luolcy_link(row: BatchPlanItem, authority: dict, settings: Settings) -> bool:
    """Identify a FUSE hardlink published by this exact interrupted MOVE intent."""
    try:
        intent = _link_intent(settings, authority)
        if not intent.path.exists():
            return False
        item = OperationItem(
            sequence=row.sequence, operation=row.operation, source=Path(row.source_path),
            target=Path(row.target_path) if row.target_path else None,
            expected_device=row.expected_device, expected_inode=row.expected_inode,
            expected_size=row.expected_size, expected_mtime_ns=row.expected_mtime_ns,
        )
        author, package, expected = _assignment_scope(item, authority, settings)
        name = item.source.name
        with ExitStack() as stack:
            author_fd = _open_directory_nofollow(author)
            stack.callback(os.close, author_fd)
            package_fd = os.open(package.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=author_fd)
            stack.callback(os.close, package_fd)
            if (_directory_identity(author_fd) != authority["author_identity"] or
                    _directory_identity(package_fd) != (authority["package_identity"] or
                                                        authority.get("created_package_identity"))):
                return False
            _verify_file(author_fd, name, expected)
            _verify_file(package_fd, name, expected)
            return intent.matches(intent.binding(author_fd, name, package_fd, name, expected))
    except (KeyError, OSError, TypeError, ValueError):
        return False


def execute_luolcy_assignment(item: OperationItem, authority: dict, settings: Settings, *,
                              lease_fence: Callable[[], None],
                              remember_package: Callable[[list[int]], None],
                              replay_link: bool = False) -> ItemResult:
    """Apply one frozen row using only same-author, no-follow directory descriptors."""
    if not settings.allow_mutation:
        return ItemResult("skipped", "当前环境未开启整理权限")
    author, package, expected = _assignment_scope(item, authority, settings)
    name = item.source.name
    with ExitStack() as stack:
        author_fd = _open_directory_nofollow(author)
        stack.callback(os.close, author_fd)
        author_identity = _directory_identity(author_fd)
        if author_identity != authority["author_identity"]:
            raise ValueError("作者目录已经变化")
        _verify_file(author_fd, name, expected)
        package_identity = authority["package_identity"] or authority.get("created_package_identity")
        if package_identity is None:
            # Exclusive creation claims only a new package which still has no on-disk binding.
            lease_fence()
            os.mkdir(package.name, mode=0o755, dir_fd=author_fd)
        package_fd = os.open(package.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=author_fd)
        stack.callback(os.close, package_fd)
        actual = _directory_identity(package_fd)
        if actual[0] != author_identity[0] or (package_identity is not None and actual != package_identity):
            raise ValueError("目标资源包已经变化")
        if package_identity is None:
            _sync_new_package_parent(author_fd)
            remember_package(actual)

        lease_fence()
        _verify_file(author_fd, name, expected)
        intent = _link_intent(settings, authority)
        binding = intent.binding(author_fd, name, package_fd, name, expected)
        if replay_link:
            if not intent.matches(binding):
                raise ValueError("中断的散件 MOVE 记录已经变化")
            _retire_link(item.source, package / name, author_fd, package_fd, expected, lease_fence, durable=True)
            return ItemResult("completed", "moved", package / name)
        try:
            rename_noreplace_at(author_fd, name, package_fd, name)
        except FileExistsError:
            return ItemResult("skipped", "目标已存在同名文件")
        except OSError as exc:
            if exc.errno != errno.EOPNOTSUPP:
                raise
            # Write the same durable link intent used by the organizer before
            # a no-replace FUSE hardlink can leave both pathname bindings live.
            try:
                os.stat(name, dir_fd=package_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                return ItemResult("skipped", "目标已存在同名文件")
            # Check metadata durability before publishing a hardlink. The
            # source may be retired only after a successful target sync.
            os.fsync(package_fd)
            intent.path.parent.mkdir(mode=0o750, exist_ok=True)
            intent.save(binding)
            lease_fence()
            _verify_file(author_fd, name, expected)
            try:
                os.link(name, name, src_dir_fd=author_fd, dst_dir_fd=package_fd, follow_symlinks=False)
            except FileExistsError:
                return ItemResult("skipped", "目标已存在同名文件")
            _retire_link(item.source, package / name, author_fd, package_fd, expected, lease_fence, durable=True)
        _verify_file(package_fd, name, expected)
        return ItemResult("completed", "moved", package / name)
