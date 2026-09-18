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
    source_extension: str | None = None
    target_extension: str | None = None


@dataclass(frozen=True)
class RenameProposal:
    source: Path
    target: Path


def _normalize_extension(value: str | None) -> str | None:
    if value is None:
        return None
    extension = value.strip()
    if not extension:
        return None
    if "/" in extension or "\\" in extension:
        raise ValueError("Extension must not contain path separators")
    if not extension.startswith("."):
        extension = f".{extension}"
    if extension in {".", ".."}:
        raise ValueError("Extension must include at least one character")
    return extension


def _extension_pair(rule: RenameRule) -> tuple[str | None, str | None]:
    source_extension = _normalize_extension(rule.source_extension)
    target_extension = _normalize_extension(rule.target_extension)
    if (source_extension is None) != (target_extension is None):
        raise ValueError("source_extension and target_extension must be provided together")
    return source_extension, target_extension


def _matches_source_extension(source: Path, rule: RenameRule) -> bool:
    source_extension, _ = _extension_pair(rule)
    if source_extension is None:
        return True
    return source.suffix.casefold() == source_extension.casefold()


def _new_name(source: Path, rule: RenameRule, index: int) -> str:
    is_file = source.is_file()
    source_extension, target_extension = _extension_pair(rule)
    extension = source.suffix if is_file else ""
    if is_file and source_extension is not None:
        extension = target_extension or extension
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
    for source in sources:
        if source.is_symlink() or not source.exists():
            raise ValueError(f"Rename source must exist and not be a symlink: {source}")

    source_extension, _ = _extension_pair(rule)
    if source_extension is not None:
        sources = [
            source
            for source in sources
            if source.is_file() and source.suffix.casefold() == source_extension.casefold()
        ]

    sources.sort(key=str)
    source_set = set(sources)
    proposals: list[RenameProposal] = []
    targets: set[Path] = set()

    for index, source in enumerate(sources):
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
