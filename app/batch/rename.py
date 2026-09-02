from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from app.path_safety import require_allowed_path


class RenameCollisionError(ValueError):
    pass


@dataclass(frozen=True)
class RenameRule:
    regex_pattern: str | None = None
    regex_replacement: str = ""
    prefix: str = ""
    suffix: str = ""
    number_start: int | None = None
    number_width: int = 3
    include_parent: bool = False


@dataclass(frozen=True)
class RenameProposal:
    source: Path
    target: Path


def _new_name(source: Path, rule: RenameRule, index: int) -> str:
    is_file = source.is_file()
    extension = source.suffix if is_file else ""
    base = source.stem if is_file else source.name
    if rule.regex_pattern:
        base = re.sub(rule.regex_pattern, rule.regex_replacement, base)
    base = f"{rule.prefix}{base}{rule.suffix}"
    if rule.include_parent:
        base = f"{source.parent.name}-{base}"
    if rule.number_start is not None:
        number = rule.number_start + index
        base = f"{number:0{rule.number_width}d}-{base}"
    return f"{base}{extension}"


def build_rename_plan(
    paths: Iterable[Path | str],
    *,
    rule: RenameRule,
    allowed_roots: Iterable[Path | str],
) -> list[RenameProposal]:
    sources = [require_allowed_path(path, allowed_roots) for path in paths]
    sources.sort(key=str)
    source_set = set(sources)
    proposals: list[RenameProposal] = []
    targets: set[Path] = set()

    for index, source in enumerate(sources):
        if source.is_symlink() or not source.exists():
            raise ValueError(f"Rename source must exist and not be a symlink: {source}")
        target = source.with_name(_new_name(source, rule, index))
        require_allowed_path(target, allowed_roots)
        if target in targets:
            raise RenameCollisionError(f"Multiple sources map to the same target: {target}")
        if target.exists() and target not in source_set and target != source:
            raise RenameCollisionError(f"Target already exists: {target}")
        targets.add(target)
        if source != target:
            proposals.append(RenameProposal(source=source, target=target))
    return proposals
