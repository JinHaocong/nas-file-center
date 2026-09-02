from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from app.batch.plans import OperationItem
from app.batch.rename import RenameCollisionError, RenameProposal
from app.batch.stats import TreeStats, collect_tree_stats, format_size, strip_trailing_stat_suffixes
from app.path_safety import require_allowed_path


def shaonv_stat_name(name: str, stats: TreeStats) -> str:
    base = strip_trailing_stat_suffixes(name)
    if stats.videos:
        return f"{base} [{stats.images}P {stats.videos}V {format_size(stats.total_bytes)}]"
    return f"{base} [{stats.images}P {format_size(stats.total_bytes)}]"


def build_stat_rename_proposals(
    root: Path | str,
    *,
    allowed_roots: Iterable[Path | str],
) -> list[RenameProposal]:
    safe_root = require_allowed_path(root, allowed_roots)
    if not safe_root.is_dir():
        raise ValueError(f"Not a directory: {safe_root}")
    proposals: list[RenameProposal] = []
    target_names: set[str] = set()
    source_names = {p.name for p in safe_root.iterdir() if p.is_dir() and not p.is_symlink()}

    for source in sorted((p for p in safe_root.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.name):
        stats = collect_tree_stats(source)
        target = source.with_name(shaonv_stat_name(source.name, stats))
        if target.name in target_names:
            raise RenameCollisionError(f"Duplicate target: {target}")
        if target.exists() and target.name not in source_names and target != source:
            raise RenameCollisionError(f"Target already exists: {target}")
        target_names.add(target.name)
        if target != source:
            proposals.append(RenameProposal(source=source, target=target))
    return proposals


def _root_touch_paths(root: Path) -> list[Path]:
    descendants: list[Path] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            p = current_path / dirname
            if p.is_symlink():
                continue
            kept_dirs.append(dirname)
            descendants.append(p)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            p = current_path / filename
            if not p.is_symlink():
                descendants.append(p)
    descendants.sort(key=lambda p: (-len(p.parts), str(p)))
    descendants.append(root)
    return descendants


def build_ordered_touch_plan(
    roots: Iterable[Path | str],
    *,
    allowed_roots: Iterable[Path | str],
) -> list[OperationItem]:
    items: list[OperationItem] = []
    sequence = 1
    for root in roots:
        safe_root = require_allowed_path(root, allowed_roots)
        if not safe_root.is_dir():
            raise ValueError(f"Not a directory: {safe_root}")
        for path in _root_touch_paths(safe_root):
            items.append(OperationItem(sequence=sequence, operation="touch", source=path))
            sequence += 1
    return items
