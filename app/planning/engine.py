from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.planning.policies import balanced_score, preference_key


@dataclass(frozen=True)
class CandidateFile:
    path: Path
    root_id: int
    top_level_dir: str
    size: int
    mtime_ns: int
    device: int
    inode: int
    relative_path: str = ""


@dataclass(frozen=True)
class CandidateGroup:
    content_hash: str
    file_size: int
    files: tuple[CandidateFile, ...]


@dataclass(frozen=True)
class PlannedItem:
    content_hash: str
    file_size: int
    keep: CandidateFile
    delete: CandidateFile


@dataclass(frozen=True)
class PlanResult:
    items: tuple[PlannedItem, ...]
    delete_counts: dict[int, int]
    skipped_groups: tuple[str, ...]


def _deletes_are_safe(
    deletes: Iterable[CandidateFile],
    *,
    directory_file_counts: dict[str, int] | None,
    scheduled_directory_deletes: Counter[str],
    protect_last_file: bool,
) -> bool:
    if not protect_last_file or directory_file_counts is None:
        return True
    proposed = Counter(d.top_level_dir for d in deletes)
    for directory, count in proposed.items():
        current = directory_file_counts.get(directory)
        if current is None:
            continue
        if current - scheduled_directory_deletes[directory] - count < 1:
            return False
    return True


def generate_plan(
    groups: Iterable[CandidateGroup],
    *,
    policy: str,
    root_order: list[int],
    directory_file_counts: dict[str, int] | None = None,
    protect_last_file: bool = False,
    path_priority_patterns: list[str] | None = None,
    relative_path_priority_patterns: list[str] | None = None,
) -> PlanResult:
    if policy not in {"keep-first-root", "keep-newest", "keep-oldest", "balanced-roots", "path-priority", "relative-path-preference"}:
        raise ValueError(f"Unsupported policy: {policy}")

    items: list[PlannedItem] = []
    delete_counts: Counter[int] = Counter()
    scheduled_directory_deletes: Counter[str] = Counter()
    skipped: list[str] = []

    for group in sorted(groups, key=lambda g: (g.content_hash, g.file_size)):
        members = sorted(group.files, key=lambda f: str(f.path))
        if len(members) < 2:
            skipped.append(group.content_hash)
            continue

        valid_keeps: list[CandidateFile] = []
        for candidate in members:
            deletes = [m for m in members if m != candidate]
            if _deletes_are_safe(
                deletes,
                directory_file_counts=directory_file_counts,
                scheduled_directory_deletes=scheduled_directory_deletes,
                protect_last_file=protect_last_file,
            ):
                valid_keeps.append(candidate)

        if not valid_keeps:
            skipped.append(group.content_hash)
            continue

        if policy == "balanced-roots":
            keep = min(valid_keeps, key=lambda c: balanced_score(c, members, delete_counts, root_order))
        else:
            keep = min(
                valid_keeps,
                key=lambda c: preference_key(
                    c,
                    policy,
                    root_order,
                    path_priority_patterns=path_priority_patterns,
                    relative_path_priority_patterns=relative_path_priority_patterns,
                ),
            )

        for delete in members:
            if delete == keep:
                continue
            items.append(PlannedItem(group.content_hash, group.file_size, keep, delete))
            delete_counts[delete.root_id] += 1
            scheduled_directory_deletes[delete.top_level_dir] += 1

    return PlanResult(tuple(items), dict(delete_counts), tuple(skipped))
