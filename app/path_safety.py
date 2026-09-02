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
