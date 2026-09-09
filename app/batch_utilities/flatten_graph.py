import os
from pathlib import Path
from collections import defaultdict
from typing import Sequence, Callable
import stat

from app.path_safety import validate_mutation_destination, UnsafePathError, is_reserved_quarantine_path
from app.batch_utilities.graph import (
    TargetItemCandidate,
    BlockingConflict,
    GraphResolutionResult,
    _resolve_physical_source,
)
from app.batch_utilities.errors import BatchUtilityScopeOverlapError

def check_wrapper_overlap(wrapper_paths: Sequence[str]) -> None:
    resolved_paths = []
    for w_lex in wrapper_paths:
        w_path = Path(w_lex)
        if not w_path.is_absolute():
            raise ValueError(f"Wrapper path must be absolute: {w_lex}")
        try:
            r = w_path.resolve(strict=True)
            resolved_paths.append((w_lex, r))
        except OSError:
            pass # Invalid path or not found is caught elsewhere or ignored
    
    # Check for identical physical paths
    seen_physical = {}
    for lex, phys in resolved_paths:
        if phys in seen_physical:
            raise BatchUtilityScopeOverlapError(
                f"Duplicate physical wrappers detected: {lex} and {seen_physical[phys]}"
            )
        seen_physical[phys] = lex
        
    # Check for ancestor/descendant overlap
    # A path is an ancestor of another if it is a prefix of the other's parts
    for i, (lex1, phys1) in enumerate(resolved_paths):
        for j, (lex2, phys2) in enumerate(resolved_paths):
            if i == j:
                continue
            try:
                # phys2 is relative to phys1?
                phys2.relative_to(phys1)
                raise BatchUtilityScopeOverlapError(
                    f"Ancestor/descendant overlap detected: {lex1} contains {lex2}"
                )
            except ValueError:
                pass

def resolve_flatten_graph(
    *,
    items: Sequence[TargetItemCandidate],
    allowed_roots: Sequence[Path],
    quarantine_root: Path | None,
    lstat_func: Callable[[str | os.PathLike[str]], os.stat_result] | None = None,
) -> GraphResolutionResult:
    _lstat = lstat_func or os.lstat
    conflicts: list[BlockingConflict] = []
    
    # 1. Map items by resolved source and detect duplicate physical sources
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

    # 2. Target validation via validate_mutation_destination
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

    # 3. Canonical planned target collisions
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
                        reason=f"Multiple candidates map to target '{res_tgt}'",
                        details={"target_path": res_tgt, "colliding_sources": sources},
                    )
                )

    # 4. Existing target conflicts (TARGET_EXISTS)
    for item in items:
        tgt_lex = item.target_path
        try:
            st = _lstat(tgt_lex)
            conflicts.append(
                BlockingConflict(
                    source_path=item.source_path,
                    target_path=item.target_path,
                    conflict_type="TARGET_EXISTS",
                    reason=f"Target path '{tgt_lex}' already exists in live filesystem",
                    details={"target_path": tgt_lex},
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
                    reason=f"Error checking target path '{tgt_lex}': {e}",
                    details={"target_path": tgt_lex, "error": str(e)},
                )
            )
            
    # Topological sort is not needed for flattening one level because source files move to the parent dir.
    # No items can be descendants of other items targets (a file moving up one level cannot form a chain with another file)
    # The order can just be the alphabetical order of sources for determinism.
    ordered_items = sorted(effective_items, key=lambda x: x.source_path)

    has_blocking = len(conflicts) > 0
    return GraphResolutionResult(
        ordered_items=tuple(ordered_items),
        conflicts=tuple(conflicts),
        has_blocking_conflicts=has_blocking,
        directory_observations=(),
        target_observations=(),
        dependency_edges=()
    )
