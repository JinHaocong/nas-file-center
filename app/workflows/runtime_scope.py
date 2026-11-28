from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.batch.file_rename import _open_directory_nofollow
from app.models import IndexRoot, IndexedPath
from app.path_safety import require_allowed_path
from app.workflows.errors import WorkflowValidationError


@dataclass(frozen=True)
class FileRunScope:
    directory: Path
    index_root: IndexRoot
    relative_path: str
    device: int
    inode: int


def descendants(column: InstrumentedAttribute[str], path: str) -> ColumnElement[bool]:
    """Bound a literal directory component using SQLite's case-sensitive binary order."""
    prefix = path.rstrip("/")
    return (column >= prefix + "/") & (column < prefix + "0")


def require_current_source_parents(paths: Iterable[str], scope: FileRunScope) -> None:
    """A previously indexed subdirectory may now be a symlink or have disappeared."""
    for parent in sorted({Path(path).parent for path in paths} - {scope.directory}):
        try:
            if not parent.is_relative_to(scope.directory) or parent.resolve(strict=True) != parent or not parent.is_dir():
                raise ValueError("Source parent changed")
        except (OSError, ValueError, RuntimeError) as exc:
            raise WorkflowValidationError(
                "索引中的源目录已变化，请刷新索引后重新预览",
                code="WORKFLOW_DIRECTORY_STALE",
                details={"directory": str(parent)},
                status_code=409,
            ) from exc


def resolve_file_run_scope(
    session: Session,
    requested: str,
    *,
    roots: list[IndexRoot],
    allowed_roots: Iterable[str],
    protected_roots: Iterable[str],
    excluded_names: Iterable[str],
    pinned_root_ids: list[int] | None,
) -> FileRunScope:
    """Resolve a directory in the most specific index without modifying the saved scan step."""
    directory = Path(requested)
    if (not directory.is_absolute() or requested.startswith("//") or "\0" in requested
            or os.path.normpath(requested) != requested):
        raise WorkflowValidationError("请选择完整的执行目录", code="WORKFLOW_DIRECTORY_UNAVAILABLE")
    try:
        resolved = require_allowed_path(directory, allowed_roots)
        if resolved != directory:
            raise ValueError("Directory alias")
        fd = _open_directory_nofollow(directory)
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
    except (OSError, ValueError, RuntimeError) as exc:
        raise WorkflowValidationError(
            "执行目录不可读取或不在允许范围内", code="WORKFLOW_DIRECTORY_UNAVAILABLE",
        ) from exc

    excluded = {name.casefold() for name in excluded_names}
    if (any(directory.is_relative_to(Path(path).resolve()) for path in protected_roots)
            or any(part.casefold() in excluded or part.casefold().startswith(".nfc-") for part in directory.parts)):
        raise WorkflowValidationError("不能对受保护目录运行工作流", code="WORKFLOW_DIRECTORY_FORBIDDEN")

    candidates = [root for root in roots if directory.is_relative_to(Path(root.root))
                  and (pinned_root_ids is None or root.id in pinned_root_ids)]
    candidates.sort(key=lambda root: len(Path(root.root).parts), reverse=True)
    for root in candidates:
        if root.last_indexed_at is None:
            continue
        relative = directory.relative_to(root.root).as_posix()
        if relative == ".":
            return FileRunScope(directory, root, "", info.st_dev, info.st_ino)
        indexed = session.scalar(select(IndexedPath.id).where(
            IndexedPath.root_key == root.root,
            or_(
                (IndexedPath.relative_path == relative) & IndexedPath.is_dir.is_(True),
                descendants(IndexedPath.relative_path, relative),
            ),
        ).limit(1))
        if indexed is not None:
            return FileRunScope(directory, root, relative, info.st_dev, info.st_ino)

    raise WorkflowValidationError(
        "本次执行目录尚未被索引，请先在文件索引中完成索引或刷新", code="WORKFLOW_DIRECTORY_NOT_INDEXED",
        details={"directory": requested},
    )
