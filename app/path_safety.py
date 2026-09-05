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


def validate_mutation_destination(
    path: Path | str,
    roots: Iterable[Path | str],
    quarantine_root: Path | str | None = None,
) -> Path:
    """
    Validate mutation destination (e.g. rename/move target).
    - Checks if the lexical path itself is already an existing symlink (rejects early).
    - Checks that parent directory resolves within ALLOWED_ROOTS.
    - Checks that filename is non-empty, contains no illegal characters, and does not exceed NAME_MAX.
    - Preserves lexical target under resolved parent without resolving to existing symlink targets.
    """
    import os
    p = Path(path).expanduser()
    if p.is_symlink():
        raise ValueError(f"目标路径已存在同名符号链接 (symlink): {path}")

    parent_resolved = require_allowed_path(p.parent, roots)
    if quarantine_root:
        require_unreserved_path(parent_resolved / p.name, quarantine_root)
    filename = p.name
    if not filename or any(c in filename for c in "/\0"):
        raise ValueError(f"非法目标文件名: {filename}")

    try:
        name_bytes = len(os.fsencode(filename))
        try:
            name_max = os.pathconf(parent_resolved, "PC_NAME_MAX")
        except (OSError, AttributeError, ValueError):
            name_max = 255
        if name_bytes > name_max:
            raise ValueError(f"目标目录名称超过文件系统限制 ({name_bytes} bytes > {name_max} bytes)")
    except OSError as exc:
        raise ValueError(f"目标名称过长或无效: {exc}") from exc

    return parent_resolved / filename
