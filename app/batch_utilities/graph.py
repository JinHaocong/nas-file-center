from collections import defaultdict
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
from typing import Any, Callable, Sequence

from app.path_safety import (
    is_path_allowed,
    is_reserved_quarantine_path,
    validate_mutation_destination,
    UnsafePathError,
)


@dataclass(frozen=True)
class TargetItemCandidate:
    source_path: str
    target_path: str
    index_root_id: int | None = None
    index_root_path: str | None = None
    relative_path: str = ""
    size: int = 0
    mtime_ns: int = 0
    device: int = 0
    inode: int = 0
    original_cand_id: int = 0
    resolved_source_path: str | None = None
    resolved_target_path: str | None = None
    is_dir: bool = False
    object_type: str = "file"
    wrapper_path: str | None = None

    def get_resolved_source_path(self) -> str:
        return self.resolved_source_path or self.source_path

    def get_resolved_target_path(self) -> str:
        return self.resolved_target_path or self.target_path


@dataclass(frozen=True)
class BlockingConflict:
    source_path: str
    target_path: str | None
    conflict_type: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphResolutionResult:
    ordered_items: tuple[TargetItemCandidate, ...]
    conflicts: tuple[BlockingConflict, ...]
    has_blocking_conflicts: bool
    directory_observations: tuple[dict[str, Any], ...] = ()
    target_observations: tuple[dict[str, Any], ...] = ()
    dependency_edges: tuple[dict[str, str], ...] = ()


def _resolve_physical_source(item: TargetItemCandidate) -> str:
    if item.resolved_source_path:
        return item.resolved_source_path
    try:
        return str(Path(item.source_path).expanduser().resolve(strict=True))
    except Exception:
        return item.source_path



def resolve_suffix_transform_graph(
    *,
    items: Sequence[TargetItemCandidate],
    allowed_roots: Sequence[Path],
    quarantine_root: Path | None,
    lstat_func: Callable[[str | os.PathLike[str]], os.stat_result] | None = None,
) -> GraphResolutionResult:
    _lstat = lstat_func or os.lstat
    conflicts: list[BlockingConflict] = []

    # 1. Map items by resolved source and detect duplicate physical sources (Blocker B)
    items_by_resolved_source: dict[str, list[TargetItemCandidate]] = defaultdict(list)
    for item in items:
        res_src = _resolve_physical_source(item)
        items_by_resolved_source[res_src].append(item)

    for res_src, cands in items_by_resolved_source.items():
        if len(cands) > 1:
            sources = sorted(c.source_path for c in cands)
            for cand in cands:
                conflicts.append(
                    BlockingConflict(
                        source_path=cand.source_path,
                        target_path=cand.target_path,
                        conflict_type="PLANNED_TARGET_COLLISION",
                        reason=f"Multiple source candidates refer to the same physical source file '{res_src}'",
                        details={"resolved_source_path": res_src, "colliding_sources": sources},
                    )
                )

    # 2. Target validation via validate_mutation_destination (Blocker C) & Canonical target resolution
    resolved_targets_by_src: dict[str, str] = {}
    effective_items: list[TargetItemCandidate] = []

    for item in items:
        tgt_lex = item.target_path
        tgt_p = Path(tgt_lex)

        # Lexical symlink check
        is_link = False
        try:
            st_lex = _lstat(tgt_lex)
            if stat.S_ISLNK(st_lex.st_mode):
                is_link = True
        except (FileNotFoundError, OSError):
            pass

        if is_link:
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="TARGET_SYMLINK",
                    reason=f"Target path '{tgt_lex}' already exists as a symlink",
                    details={"target_path": tgt_lex},
                )
            )
            resolved_targets_by_src[item.source_path] = str(tgt_p)
            effective_items.append(item)
            continue


        try:
            canon_p = validate_mutation_destination(
                tgt_lex,
                roots=allowed_roots,
                quarantine_root=quarantine_root,
            )
            canon_tgt = str(canon_p)
            resolved_targets_by_src[item.source_path] = canon_tgt
            eff_item = TargetItemCandidate(
                source_path=item.source_path,
                target_path=item.target_path,
                index_root_id=item.index_root_id,
                index_root_path=item.index_root_path,
                relative_path=item.relative_path,
                size=item.size,
                mtime_ns=item.mtime_ns,
                device=item.device,
                inode=item.inode,
                original_cand_id=item.original_cand_id,
                resolved_source_path=_resolve_physical_source(item),
                resolved_target_path=canon_tgt,
            )
            effective_items.append(eff_item)
        except UnsafePathError as e:
            if quarantine_root and is_reserved_quarantine_path(tgt_lex, quarantine_root):
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="RESERVED_TARGET",
                        reason=f"Target path '{tgt_lex}' is within reserved quarantine storage",
                        details={"target_path": tgt_lex, "error": str(e)},
                    )
                )
            else:
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="TARGET_OUTSIDE_ALLOWED_ROOT",
                        reason=f"Target path '{tgt_lex}' is outside allowed roots",
                        details={"target_path": tgt_lex, "error": str(e)},
                    )
                )
            resolved_targets_by_src[item.source_path] = str(tgt_p)
            effective_items.append(item)
        except ValueError as e:
            msg = str(e)
            if "超过文件系统限制" in msg or "过长" in msg:
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="NAME_TOO_LONG",
                        reason=f"Target filename length exceeds maximum limit: {e}",
                        details={"target_path": tgt_lex, "error": msg},
                    )
                )
            elif "symlink" in msg:
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="TARGET_SYMLINK",
                        reason=f"Target path '{tgt_lex}' already exists as a symlink",
                        details={"target_path": tgt_lex, "error": msg},
                    )
                )
            else:
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="TARGET_EXISTS",
                        reason=f"Invalid target path: {e}",
                        details={"target_path": tgt_lex, "error": msg},
                    )
                )
            resolved_targets_by_src[item.source_path] = str(tgt_p)
            effective_items.append(item)

    # 3. Canonical planned target collisions (Blocker B)
    items_by_resolved_target: dict[str, list[TargetItemCandidate]] = defaultdict(list)
    for item in effective_items:
        res_tgt = resolved_targets_by_src[item.source_path]
        items_by_resolved_target[res_tgt].append(item)

    for res_tgt, cands in items_by_resolved_target.items():
        if len(cands) > 1:
            sources = sorted(c.source_path for c in cands)
            for cand in cands:
                conflicts.append(
                    BlockingConflict(
                        source_path=cand.source_path,
                        target_path=cand.target_path,
                        conflict_type="PLANNED_TARGET_COLLISION",
                        reason=f"Multiple sources plan the same target path '{res_tgt}'",
                        details={"target_path": cand.target_path, "resolved_target_path": res_tgt, "colliding_sources": sources},
                    )
                )

    # 4. Casefold checks (Blocker D)
    # (a) source -> target case-only
    for item in effective_items:
        src_p = Path(item.source_path)
        tgt_p = Path(item.target_path)
        res_src_p = Path(_resolve_physical_source(item))
        res_tgt_p = Path(resolved_targets_by_src[item.source_path])
        if (
            (src_p.parent == tgt_p.parent and src_p.name.casefold() == tgt_p.name.casefold() and src_p.name != tgt_p.name)
            or
            (res_src_p.parent == res_tgt_p.parent and res_src_p.name.casefold() == res_tgt_p.name.casefold() and res_src_p.name != res_tgt_p.name)
        ):
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="CASE_ONLY_COLLISION",
                    reason="Case-only rename is not supported",
                    details={"source_path": item.source_path, "target_path": item.target_path},
                )
            )

    # (b) planned target <-> planned target casefold in same directory
    casefold_targets_by_dir: dict[tuple[str, str], list[TargetItemCandidate]] = defaultdict(list)
    for item in effective_items:
        res_tgt_p = Path(resolved_targets_by_src[item.source_path])
        casefold_targets_by_dir[(str(res_tgt_p.parent), res_tgt_p.name.casefold())].append(item)

    for (p_dir, cf_name), cands in casefold_targets_by_dir.items():
        if len(cands) > 1:
            distinct_names = {Path(resolved_targets_by_src[c.source_path]).name for c in cands}
            if len(distinct_names) > 1:
                for cand in cands:
                    conflicts.append(
                        BlockingConflict(
                            source_path=cand.source_path,
                            target_path=cand.target_path,
                            conflict_type="CASE_ONLY_COLLISION",
                            reason=f"Target path '{cand.target_path}' collides with another planned target under casefold comparison",
                            details={"target_path": cand.target_path, "dir": p_dir},
                        )
                    )

    # (c) planned target <-> existing directory entry casefold (scan parent directories)
    target_parent_dirs = sorted({Path(resolved_targets_by_src[item.source_path]).parent for item in effective_items}, key=lambda p: str(p))
    directory_observations: list[dict[str, Any]] = []
    dir_entries_by_parent: dict[Path, list[str]] = {}
    failed_parent_dirs: set[Path] = set()

    for p_dir in target_parent_dirs:
        entries: list[str] = []
        scan_status = "OK"
        try:
            if p_dir.exists() and p_dir.is_dir():
                with os.scandir(p_dir) as it:
                    for entry in it:
                        entries.append(entry.name)
        except OSError:
            scan_status = "FAILED"
            failed_parent_dirs.add(p_dir)

        entries.sort()
        dir_entries_by_parent[p_dir] = entries
        directory_observations.append({
            "parent": str(p_dir),
            "scan_status": scan_status,
        })
        for e_name in entries:
            directory_observations.append({
                "parent": str(p_dir),
                "name": e_name,
                "casefold": e_name.casefold(),
            })

    for item in effective_items:
        res_tgt_p = Path(resolved_targets_by_src[item.source_path])
        p_dir = res_tgt_p.parent
        tgt_name = res_tgt_p.name

        if p_dir in failed_parent_dirs:
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="CASE_ONLY_COLLISION",
                    reason=f"Failed to perform directory casefold observation on parent '{p_dir}'",
                    details={"target_path": item.target_path, "parent_dir": str(p_dir)},
                )
            )
            continue

        entries = dir_entries_by_parent.get(p_dir, [])
        for e_name in entries:
            if e_name.casefold() == tgt_name.casefold() and e_name != tgt_name:
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="CASE_ONLY_COLLISION",
                        reason=f"Target '{tgt_name}' collides with existing file '{e_name}' under casefold comparison",
                        details={"target_path": item.target_path, "existing_entry": e_name},
                    )
                )

    # 5. Live target existence & observations
    target_observations: list[dict[str, Any]] = []
    existing_targets_on_disk: set[str] = set()

    for item in effective_items:
        res_tgt = resolved_targets_by_src[item.source_path]
        obs: dict[str, Any] = {"target_path": res_tgt, "exists": False, "is_symlink": False}
        try:
            st = _lstat(res_tgt)
            obs["exists"] = True
            obs["size"] = st.st_size
            obs["mtime_ns"] = st.st_mtime_ns
            obs["ino"] = st.st_ino
            obs["dev"] = st.st_dev
            existing_targets_on_disk.add(res_tgt)

            if stat.S_ISLNK(st.st_mode):
                obs["is_symlink"] = True
                conflicts.append(
                    BlockingConflict(
                        source_path=item.source_path,
                        target_path=item.target_path,
                        conflict_type="TARGET_SYMLINK",
                        reason=f"Target path '{res_tgt}' already exists as a symlink",
                        details={"target_path": item.target_path},
                    )
                )
        except FileNotFoundError:
            pass
        except OSError as e:
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="TARGET_EXISTS",
                    reason=f"Failed to inspect target path: {e}",
                    details={"target_path": item.target_path, "error": str(e)},
                )
            )
        target_observations.append(obs)

    target_observations.sort(key=lambda o: o["target_path"])

    # 6. Phase G5 Blocked Occupant Propagation (Blocker E)
    blocked_sources: set[str] = {c.source_path for c in conflicts}
    blocked_resolved_sources: set[str] = {
        _resolve_physical_source(item) for item in effective_items if item.source_path in blocked_sources
    }

    while True:
        newly_blocked = False
        for item in effective_items:
            if item.source_path in blocked_sources:
                continue
            res_tgt = resolved_targets_by_src[item.source_path]
            if res_tgt in existing_targets_on_disk:
                if res_tgt not in items_by_resolved_source:
                    conflicts.append(
                        BlockingConflict(
                            source_path=item.source_path,
                            target_path=item.target_path,
                            conflict_type="TARGET_EXISTS",
                            reason=f"Target '{item.target_path}' already exists on disk and will not vacate",
                            details={"target_path": item.target_path},
                        )
                    )
                    blocked_sources.add(item.source_path)
                    blocked_resolved_sources.add(_resolve_physical_source(item))
                    newly_blocked = True
                else:
                    occupants = items_by_resolved_source[res_tgt]
                    if any(
                        occ.source_path in blocked_sources or _resolve_physical_source(occ) in blocked_resolved_sources
                        for occ in occupants
                    ):
                        conflicts.append(
                            BlockingConflict(
                                source_path=item.source_path,
                                target_path=item.target_path,
                                conflict_type="TARGET_EXISTS",
                                reason=f"Target occupant '{occupants[0].source_path}' is blocked and will not vacate target '{item.target_path}'",
                                details={"target_path": item.target_path, "occupant_source": occupants[0].source_path},
                            )
                        )
                        blocked_sources.add(item.source_path)
                        blocked_resolved_sources.add(_resolve_physical_source(item))
                        newly_blocked = True
        if not newly_blocked:
            break

    # 7. Dependency Graph & Kahn's Topological Sort on Unblocked Items (Blocker F)
    unblocked_items = [item for item in effective_items if item.source_path not in blocked_sources]
    unblocked_by_res_src = {_resolve_physical_source(item): item for item in unblocked_items}

    prereqs: dict[str, set[str]] = {_resolve_physical_source(item): set() for item in unblocked_items}
    dependents: dict[str, set[str]] = {_resolve_physical_source(item): set() for item in unblocked_items}
    in_degree: dict[str, int] = {_resolve_physical_source(item): 0 for item in unblocked_items}
    dependency_edges: list[dict[str, str]] = []

    for item in unblocked_items:
        res_tgt = resolved_targets_by_src[item.source_path]
        if res_tgt in unblocked_by_res_src:
            occupant = unblocked_by_res_src[res_tgt]
            occ_src = _resolve_physical_source(occupant)
            item_src = _resolve_physical_source(item)
            if occ_src != item_src:
                prereqs[item_src].add(occ_src)
                dependents[occ_src].add(item_src)
                in_degree[item_src] += 1
                dependency_edges.append({"from_source": occupant.source_path, "to_source": item.source_path})

    dependency_edges.sort(key=lambda e: (e["from_source"], e["to_source"]))

    ready_sources = sorted([src for src, deg in in_degree.items() if deg == 0])
    ordered_sequence: list[TargetItemCandidate] = []

    while ready_sources:
        curr_src = ready_sources.pop(0)
        ordered_sequence.append(unblocked_by_res_src[curr_src])

        newly_ready: list[str] = []
        for dep_src in dependents[curr_src]:
            in_degree[dep_src] -= 1
            if in_degree[dep_src] == 0:
                newly_ready.append(dep_src)

        if newly_ready:
            ready_sources.extend(newly_ready)
            ready_sources.sort()

    if len(ordered_sequence) < len(unblocked_items):
        cycle_nodes = [unblocked_by_res_src[src] for src, deg in in_degree.items() if deg > 0]
        for cand in cycle_nodes:
            conflicts.append(
                BlockingConflict(
                    source_path=cand.source_path,
                    target_path=cand.target_path,
                    conflict_type="RENAME_CYCLE",
                    reason=f"Rename cycle detected involving '{cand.source_path}' -> '{cand.target_path}'",
                    details={"source_path": cand.source_path, "target_path": cand.target_path},
                )
            )

    seen_conflicts = set()
    deduped_conflicts: list[BlockingConflict] = []
    for c in conflicts:
        key = (c.conflict_type, c.source_path, c.target_path)
        if key not in seen_conflicts:
            seen_conflicts.add(key)
            deduped_conflicts.append(c)

    deduped_conflicts.sort(key=lambda c: (c.source_path, c.conflict_type))
    has_blocking = len(deduped_conflicts) > 0
    final_ordered = tuple(ordered_sequence)

    return GraphResolutionResult(
        ordered_items=final_ordered,
        conflicts=tuple(deduped_conflicts),
        has_blocking_conflicts=has_blocking,
        directory_observations=tuple(directory_observations),
        target_observations=tuple(target_observations),
        dependency_edges=tuple(dependency_edges),
    )

