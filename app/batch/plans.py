from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OperationItem:
    sequence: int
    operation: str
    source: Path
    target: Path | None = None
    keep: Path | None = None
    expected_size: int = 0
    expected_hash: str | None = None
    state: str = "planned"
    protected_dir: Path | None = None
    expected_mtime_ns: int = 0
    expected_device: int = 0
    expected_inode: int = 0
