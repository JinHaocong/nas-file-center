from __future__ import annotations

from collections import Counter
from fnmatch import fnmatchcase
from typing import Iterable


def root_rank(root_id: int, root_order: Iterable[int]) -> int:
    order = list(root_order)
    try:
        return order.index(root_id)
    except ValueError:
        return len(order) + root_id


def _pattern_rank(value: str, patterns: list[str] | None) -> int:
    if not patterns:
        return 10**9
    for index, pattern in enumerate(patterns):
        if fnmatchcase(value, pattern):
            return index
    return len(patterns) + 10**6


def preference_key(
    candidate,
    policy: str,
    root_order: list[int],
    *,
    path_priority_patterns: list[str] | None = None,
    relative_path_priority_patterns: list[str] | None = None,
):
    path_key = str(candidate.path)
    if policy == "keep-first-root":
        return (root_rank(candidate.root_id, root_order), path_key)
    if policy == "keep-newest":
        return (-candidate.mtime_ns, root_rank(candidate.root_id, root_order), path_key)
    if policy == "keep-oldest":
        return (candidate.mtime_ns, root_rank(candidate.root_id, root_order), path_key)
    if policy == "path-priority":
        return (_pattern_rank(path_key, path_priority_patterns), root_rank(candidate.root_id, root_order), path_key)
    if policy == "relative-path-preference":
        rel = candidate.relative_path or path_key
        return (_pattern_rank(rel, relative_path_priority_patterns), root_rank(candidate.root_id, root_order), path_key)
    raise ValueError(f"Unsupported policy: {policy}")


def balanced_score(candidate, members, delete_counts: Counter[int], root_order: list[int]):
    projected = Counter(delete_counts)
    for member in members:
        if member != candidate:
            projected[member.root_id] += 1
    roots = list(dict.fromkeys([*root_order, *(m.root_id for m in members)]))
    values = [projected[root] for root in roots]
    spread = max(values, default=0) - min(values, default=0)
    squared = sum(v * v for v in values)
    return (spread, squared, root_rank(candidate.root_id, root_order), str(candidate.path))
