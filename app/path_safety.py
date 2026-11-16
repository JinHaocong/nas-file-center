from __future__ import annotations

from pathlib import Path
from typing import Iterable


class UnsafePathError(ValueError):
    pass


def _resolved_roots(roots: Iterable[Path | str]) -> list[Path]:
    return [Path(root).expanduser().resolve(strict=False) for root in roots]


def is_path_allowed(path: Path | str, roots: Iterable[Path | str]) -> bool:
    resolved = Path(path).expanduser().resolve(strict=False)
    return any(resolved == root or resolved.is_relative_to(root) for root in _resolved_roots(roots))


def require_allowed_path(path: Path | str, roots: Iterable[Path | str]) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    allowed = _resolved_roots(roots)
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        raise UnsafePathError(f"Path is outside configured roots: {path}")
    return resolved


def is_reserved_quarantine_path(path: Path | str, quarantine_root: Path | str | None) -> bool:
    if not quarantine_root:
        return False
    resolved_path = Path(path).expanduser().resolve(strict=False)
    resolved_trash = Path(quarantine_root).expanduser().resolve(strict=False)
    return resolved_path == resolved_trash or resolved_path.is_relative_to(resolved_trash)


def require_unreserved_path(path: Path | str, quarantine_root: Path | str | None) -> Path:
    if is_reserved_quarantine_path(path, quarantine_root):
        raise UnsafePathError(f"Access to reserved quarantine storage is blocked: {path}")
    return Path(path).expanduser().resolve(strict=False)


def _preserves_existing_media_basename(
    source: Path | str | None,
    target: Path,
) -> bool:
    """Permit an unchanged, already-existing long basename only for local P/V moves.

    Some NAS/FUSE mounts report PC_NAME_MAX=255 for a missing P/V directory
    while actually storing a longer original name. We cannot infer support for
    arbitrary new names, but an unchanged name under a sibling P/V folder can
    be offered to the kernel's no-clobber move. The real syscall may still
    reject it safely with ENAMETOOLONG.
    """
    import os
    import re
    import stat

    if source is None:
        return False
    raw = Path(source).expanduser()
    if (not raw.is_absolute() or raw.name != target.name
            or not re.fullmatch(r"(?i:[PV](?:_[1-9][0-9]*)?)", target.parent.name)):
        return False
    try:
        if raw.is_symlink() or not raw.is_file():
            return False
        src_parent = raw.parent.resolve(strict=True)
        dest_grandparent = target.parent.parent.resolve(strict=True)
        if src_parent != dest_grandparent:
            return False
        source_stat = os.lstat(raw)
        parent_stat = os.stat(src_parent)
        if (not stat.S_ISREG(source_stat.st_mode)
                or source_stat.st_dev != parent_stat.st_dev):
            return False
        if target.parent.is_symlink():
            return False
        if target.parent.exists():
            target_parent_stat = os.lstat(target.parent)
            if (not stat.S_ISDIR(target_parent_stat.st_mode)
                    or target_parent_stat.st_dev != source_stat.st_dev):
                return False
        return True
    except (OSError, ValueError):
        return False


def _nearest_existing_path(directory: Path) -> Path:
    """Use an existing ancestor for PC_NAME_MAX; missing P/V is not a mount."""
    ancestor = directory
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    return ancestor


def validate_mutation_destination(
    path: Path | str,
    roots: Iterable[Path | str],
    quarantine_root: Path | str | None = None,
    *,
    existing_media_source: Path | str | None = None,
) -> Path:
    """
    Validate mutation destination (e.g. rename/move target).
    - Checks if the lexical path itself is already an existing symlink (rejects early).
    - Checks that parent directory resolves within ALLOWED_ROOTS.
    - Checks that filename is non-empty, contains no illegal characters, and does not exceed NAME_MAX.
    - Preserves lexical target under resolved parent without resolving to existing symlink targets.
    """
    import errno
    import os
    p = Path(path).expanduser()
    try:
        if p.is_symlink():
            raise ValueError(f"目标路径已存在同名符号链接 (symlink): {path}")
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ENAMETOOLONG or "too long" in str(exc).lower():
            raise ValueError(f"目标名称过长或无效: {exc}") from exc


    parent_resolved = require_allowed_path(p.parent, roots)
    if quarantine_root:
        require_unreserved_path(parent_resolved / p.name, quarantine_root)
    filename = p.name
    if not filename or any(c in filename for c in "/\0"):
        raise ValueError(f"非法目标文件名: {filename}")

    try:
        name_bytes = len(os.fsencode(filename))
        try:
            name_max = os.pathconf(_nearest_existing_path(parent_resolved), "PC_NAME_MAX")
        except (OSError, AttributeError, ValueError):
            name_max = 255
        if name_max <= 0:
            name_max = 255
        if (name_bytes > name_max
                and not _preserves_existing_media_basename(existing_media_source, p)):
            raise ValueError(
                f"目标文件名超过文件系统报告的限制 ({name_bytes} bytes > {name_max} bytes)"
            )
    except OSError as exc:
        raise ValueError(f"目标名称过长或无效: {exc}") from exc

    return parent_resolved / filename
