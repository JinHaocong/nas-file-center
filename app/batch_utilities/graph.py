from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Any, Callable, Sequence

from app.path_safety import is_path_allowed, is_reserved_quarantine_path


@dataclass(frozen=True)
class TargetItemCandidate:
    source_path: str
    target_path: str
    index_root_id: int
    index_root_path: str
    relative_path: str
    size: int
    mtime_ns: int
    device: int
    inode: int
    original_cand_id: int


@dataclass(frozen=True)
class BlockingConflict:
    source_path: str
    target_path: str | None
    conflict_type: str
    reason: str
    details: dict[str, Any]


@dataclass(frozen=True)
class GraphResolutionResult:
    ordered_items: tuple[TargetItemCandidate, ...]
    conflicts: tuple[BlockingConflict, ...]
    has_blocking_conflicts: bool


def resolve_suffix_transform_graph(
    *,
    items: Sequence[TargetItemCandidate],
    allowed_roots: Sequence[Path],
    quarantine_root: Path | None,
    lstat_func: Callable[[str | os.PathLike[str]], os.stat_result] | None = None,
) -> GraphResolutionResult:
    _lstat = lstat_func or os.lstat
    conflicts: list[BlockingConflict] = []

    # 1. Map items by source and target
    items_by_source: dict[str, TargetItemCandidate] = {}
    items_by_target: dict[str, list[TargetItemCandidate]] = defaultdict(list)
    casefold_targets_by_dir: dict[tuple[Path, str], list[TargetItemCandidate]] = defaultdict(list)

    for item in items:
        items_by_source[item.source_path] = item
        items_by_target[item.target_path].append(item)
        tgt_p = Path(item.target_path)
        casefold_targets_by_dir[(tgt_p.parent, tgt_p.name.casefold())].append(item)

    # 2. Planned target collisions
    for target_path, cands in items_by_target.items():
        if len(cands) > 1:
            sources = sorted(c.source_path for c in cands)
            for cand in cands:
                conflicts.append(
                    BlockingConflict(
                        source_path=cand.source_path,
                        target_path=cand.target_path,
                        conflict_type="PLANNED_TARGET_COLLISION",
                        reason=f"Multiple sources plan the same target path '{target_path}'",
                        details={"target_path": target_path, "colliding_sources": sources},
                    )
                )

    # 3. Casefold collisions
    for item in items:
        src_p = Path(item.source_path)
        tgt_p = Path(item.target_path)
        if (
            src_p.parent == tgt_p.parent
            and src_p.name.casefold() == tgt_p.name.casefold()
            and src_p.name != tgt_p.name
        ):
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="CASE_COLLISION",
                    reason="Case-only rename is not supported",
                    details={"source_path": item.source_path, "target_path": item.target_path},
                )
            )

    for (parent_dir, fold_name), cands in casefold_targets_by_dir.items():
        if len(cands) > 1:
            # Check if there are distinct target names that collide in casefold
            distinct_names = {Path(c.target_path).name for c in cands}
            if len(distinct_names) > 1:
                for cand in cands:
                    conflicts.append(
                        BlockingConflict(
                            source_path=cand.source_path,
                            target_path=cand.target_path,
                            conflict_type="CASE_COLLISION",
                            reason=f"Target path '{cand.target_path}' collides with another planned target under casefold comparison",
                            details={"target_path": cand.target_path, "dir": str(parent_dir)},
                        )
                    )

    # 4. Target path validation & Filesystem occupancy check
    for item in items:
        tgt_p = Path(item.target_path)
        name_bytes = tgt_p.name.encode("utf-8")

        # NAME_MAX
        if len(name_bytes) > 255:
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="NAME_MAX_EXCEEDED",
                    reason=f"Target filename length ({len(name_bytes)} bytes) exceeds 255 bytes",
                    details={"target_path": item.target_path, "length": len(name_bytes)},
                )
            )

        # Boundary checks
        if not is_path_allowed(tgt_p, allowed_roots):
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="PATH_OUTSIDE_ALLOWED_ROOT",
                    reason="Target path is outside allowed roots",
                    details={"target_path": item.target_path},
                )
            )

        if is_reserved_quarantine_path(tgt_p, quarantine_root):
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="RESERVED_QUARANTINE_PATH",
                    reason="Target path is within reserved quarantine storage",
                    details={"target_path": item.target_path},
                )
            )

        # Filesystem stat check on target
        try:
            st = _lstat(item.target_path)
            # Target exists on disk
            if stat.S_ISLNK(st.st_mode):
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="TARGET_IS_SYMLINK",
                        reason="Target path already exists as a symlink",
                        details={"target_path": item.target_path},
                    )
                )
            else:
                # Target exists and is not a symlink
                if item.target_path not in items_by_source:
                    conflicts.append(
                        BlockingConflict(
                            source_path=item.source_path,
                            target_path=item.target_path,
                            conflict_type="TARGET_COLLISION",
                            reason=f"Target '{item.target_path}' already exists on disk and will not vacate",
                            details={"target_path": item.target_path},
                        )
                    )
        except FileNotFoundError:
            # Target does not exist on disk, completely safe
            pass
        except OSError as e:
            # e.g. ELOOP or permission error
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="TARGET_COLLISION",
                    reason=f"Failed to inspect target path: {e}",
                    details={"target_path": item.target_path, "error": str(e)},
                )
            )

    # 5. Dependency graph & Topological sort
    # Rule: If A.target == B.source, then B must execute before A (B vacates target of A).
    # Prereq edge: B -> A. That is, A depends on B.
    prereqs: dict[str, set[str]] = {item.source_path: set() for item in items}
    dependents: dict[str, set[str]] = {item.source_path: set() for item in items}
    in_degree: dict[str, int] = {item.source_path: 0 for item in items}

    for item in items:
        target = item.target_path
        if target in items_by_source:
            # occupant B is items_by_source[target]
            occupant = items_by_source[target]
            # B must run before item A
            prereqs[item.source_path].add(occupant.source_path)
            dependents[occupant.source_path].add(item.source_path)
            in_degree[item.source_path] += 1

    # Deterministic Kahn's algorithm
    ready_sources = sorted([src for src, deg in in_degree.items() if deg == 0])
    ordered_sequence: list[TargetItemCandidate] = []

    while ready_sources:
        curr_src = ready_sources.pop(0)
        ordered_sequence.append(items_by_source[curr_src])

        newly_ready: list[str] = []
        for dep_src in dependents[curr_src]:
            in_degree[dep_src] -= 1
            if in_degree[dep_src] == 0:
                newly_ready.append(dep_src)

        if newly_ready:
            ready_sources.extend(newly_ready)
            ready_sources.sort()

    # Cycle detection
    if len(ordered_sequence) < len(items):
        # Nodes with in_degree > 0 are part of or blocked by a cycle
        unresolved = [items_by_source[src] for src, deg in in_degree.items() if deg > 0]
        for cand in unresolved:
            conflicts.append(
                BlockingConflict(
                    source_path=cand.source_path,
                    target_path=cand.target_path,
                    conflict_type="CYCLE_DETECTED",
                    reason=f"Rename cycle detected involving '{cand.source_path}' -> '{cand.target_path}'",
                    details={"source_path": cand.source_path, "target_path": cand.target_path},
                )
            )

    # Deduplicate conflicts
    seen_conflicts = set()
    deduped_conflicts: list[BlockingConflict] = []
    for c in conflicts:
        key = (c.conflict_type, c.source_path, c.target_path)
        if key not in seen_conflicts:
            seen_conflicts.add(key)
            deduped_conflicts.append(c)

    has_blocking = len(deduped_conflicts) > 0
    final_ordered = tuple(ordered_sequence) if not has_blocking else tuple()

    return GraphResolutionResult(
        ordered_items=final_ordered,
        conflicts=tuple(deduped_conflicts),
        has_blocking_conflicts=has_blocking,
    )
