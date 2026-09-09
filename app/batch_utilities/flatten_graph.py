from collections import defaultdict
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
from app.batch_utilities.graph import (
    TargetItemCandidate,
    BlockingConflict,
    GraphResolutionResult,
    _resolve_physical_source,
)
from app.batch_utilities.errors import (
    BatchUtilityInvalidConfigError,
    BatchUtilityScopeNotFoundError,
    BatchUtilityScopeOverlapError,
    BatchUtilitySymlinkBlockedError,
    BatchUtilityCrossRootError,
)


def validate_wrappers_preflight(
    wrapper_paths: Sequence[str],
    allowed_roots: Sequence[Path],
    quarantine_root: Path | None,
) -> None:
    """
    Perform pre-flight validation on wrapper directories before scanning.
    Enforces strict no-follow validation before any path resolution:
      - Symlink: BATCH_UTILITY_SYMLINK_BLOCKED
      - Missing: BATCH_UTILITY_SCOPE_NOT_FOUND
      - Outside allowed root: BATCH_UTILITY_CROSS_ROOT
      - Reserved quarantine: BATCH_UTILITY_INVALID_CONFIG
      - Not directory / exactly an allowed root: BATCH_UTILITY_INVALID_CONFIG
      - Scope overlap: BATCH_UTILITY_SCOPE_OVERLAP
    """
    for w_lex in wrapper_paths:
        w_path = Path(w_lex)
        if not w_path.is_absolute():
            raise BatchUtilityInvalidConfigError(
                f"Wrapper path must be absolute: {w_lex}",
                details={"wrapper_path": w_lex},
            )

        # 1. No-follow lstat first
        norm_lex = os.path.normpath(w_lex)
        try:
            st_norm = os.lstat(norm_lex)
            if stat.S_ISLNK(st_norm.st_mode):
                raise BatchUtilitySymlinkBlockedError(
                    f"Wrapper path '{w_lex}' is a symlink",
                    details={"wrapper_path": w_lex},
                )
            st = os.lstat(w_lex)
        except FileNotFoundError:
            raise BatchUtilityScopeNotFoundError(
                f"Wrapper directory '{w_lex}' does not exist",
                details={"wrapper_path": w_lex},
            )
        except OSError as e:
            raise BatchUtilityScopeNotFoundError(
                f"Failed to access wrapper '{w_lex}': {e}",
                details={"wrapper_path": w_lex, "error": str(e)},
            )

        if stat.S_ISLNK(st.st_mode):
            raise BatchUtilitySymlinkBlockedError(
                f"Wrapper path '{w_lex}' is a symlink",
                details={"wrapper_path": w_lex},
            )

        if not stat.S_ISDIR(st.st_mode):
            raise BatchUtilityInvalidConfigError(
                f"Wrapper path '{w_lex}' is not a directory",
                details={"wrapper_path": w_lex},
            )

        # 2. Safety bounds checks
        if quarantine_root and is_reserved_quarantine_path(w_lex, quarantine_root):
            raise BatchUtilityCrossRootError(
                f"Wrapper '{w_lex}' is within reserved quarantine storage",
                details={"wrapper_path": w_lex},
            )

        try:
            if not is_path_allowed(w_lex, allowed_roots):
                raise BatchUtilityCrossRootError(
                    f"Wrapper path '{w_lex}' is outside allowed roots",
                    details={"wrapper_path": w_lex},
                )
        except BatchUtilityCrossRootError:
            raise
        except OSError as e:
            raise BatchUtilityInvalidConfigError(
                f"Failed to resolve wrapper path '{w_lex}': {e}",
                details={"wrapper_path": w_lex, "errno": getattr(e, "errno", None)},
            )

        norm_w = os.path.normpath(w_lex)
        for r in allowed_roots:
            norm_r = str(r)
            if norm_w == norm_r:
                raise BatchUtilityInvalidConfigError(
                    f"Wrapper '{w_lex}' cannot be an allowed root",
                    details={"wrapper_path": w_lex},
                )
            try:
                if w_path.resolve(strict=True) == r.resolve(strict=True):
                    raise BatchUtilityInvalidConfigError(
                        f"Wrapper '{w_lex}' cannot be an allowed root",
                        details={"wrapper_path": w_lex},
                    )
            except OSError as e:
                raise BatchUtilityInvalidConfigError(
                    f"Failed to resolve wrapper path '{w_lex}': {e}",
                    details={"wrapper_path": w_lex, "errno": getattr(e, "errno", None)},
                )

    # 3. Check for physical duplicate / ancestor-descendant overlap
    check_wrapper_overlap(wrapper_paths)


def check_wrapper_overlap(wrapper_paths: Sequence[str]) -> None:
    resolved_paths = []
    seen_dev_ino = {}
    for w_lex in wrapper_paths:
        w_path = Path(w_lex)
        if not w_path.is_absolute():
            raise BatchUtilityInvalidConfigError(f"Wrapper path must be absolute: {w_lex}")
        try:
            r = w_path.resolve(strict=True)
            st = os.stat(r)
            dev_ino = (st.st_dev, st.st_ino)
        except OSError as e:
            raise BatchUtilityInvalidConfigError(
                f"Failed to resolve wrapper path '{w_lex}': {e}",
                details={"wrapper_path": w_lex, "errno": getattr(e, "errno", None)},
            )
        resolved_paths.append((w_lex, r, dev_ino))

    seen_physical = {}
    for lex, phys, dev_ino in resolved_paths:
        if phys in seen_physical:
            raise BatchUtilityScopeOverlapError(
                f"Duplicate physical wrappers detected: '{lex}' and '{seen_physical[phys]}'",
                details={"wrapper_1": lex, "wrapper_2": seen_physical[phys]},
            )
        seen_physical[phys] = lex

        if dev_ino in seen_dev_ino:
            raise BatchUtilityScopeOverlapError(
                f"Duplicate physical wrappers detected: '{lex}' and '{seen_dev_ino[dev_ino]}'",
                details={"wrapper_1": lex, "wrapper_2": seen_dev_ino[dev_ino]},
            )
        seen_dev_ino[dev_ino] = lex

    for i, (lex1, phys1, _) in enumerate(resolved_paths):
        for j, (lex2, phys2, _) in enumerate(resolved_paths):
            if i == j:
                continue
            try:
                phys2.relative_to(phys1)
                raise BatchUtilityScopeOverlapError(
                    f"Ancestor/descendant overlap detected: '{lex1}' contains '{lex2}'",
                    details={"ancestor": lex1, "descendant": lex2},
                )
            except ValueError:
                pass


def resolve_flatten_graph(
    *,
    items: Sequence[TargetItemCandidate],
    allowed_roots: Sequence[Path],
    quarantine_root: Path | None,
    wrapper_observations: Sequence[dict[str, Any]] | None = None,
    lstat_func: Callable[[str | os.PathLike[str]], os.stat_result] | None = None,
    scandir_func: Any | None = None,
) -> GraphResolutionResult:
    _lstat = lstat_func or os.lstat
    _scandir = scandir_func or os.scandir
    conflicts: list[BlockingConflict] = []

    def _get_child_names(scandir_callable: Any, path_str: str) -> list[str]:
        res = scandir_callable(path_str)
        if hasattr(res, "__enter__"):
            with res as it:
                return sorted(e.name for e in it)
        else:
            return sorted(e.name for e in res)

    wrapper_obs_map: dict[str, dict[str, Any]] = {}
    if wrapper_observations:
        for obs in wrapper_observations:
            wrapper_obs_map[obs["wrapper_path"]] = obs

    wrapper_status: dict[str, tuple[bool, bool, str, dict[str, Any]]] = {}

    def _validate_wrapper(w_lex: str, exp: dict[str, Any] | None) -> tuple[bool, bool, str, dict[str, Any]]:
        try:
            st_w = _lstat(w_lex)
            if stat.S_ISLNK(st_w.st_mode):
                return (
                    True,
                    False,
                    f"WRAPPER_IDENTITY_CHANGED: Wrapper '{w_lex}' is a symlink",
                    {"wrapper_path": w_lex, "error": "WRAPPER_SYMLINK"},
                )
            if not stat.S_ISDIR(st_w.st_mode):
                return (
                    True,
                    False,
                    f"WRAPPER_IDENTITY_CHANGED: Wrapper '{w_lex}' is not a directory",
                    {"wrapper_path": w_lex, "error": "NOT_A_DIRECTORY"},
                )
            if exp is not None:
                if exp.get("scan_status") != "OK":
                    return (
                        True,
                        False,
                        f"WRAPPER_IDENTITY_CHANGED: Wrapper '{w_lex}' initial scan status was not OK",
                        {"wrapper_path": w_lex},
                    )
                if (
                    st_w.st_dev != exp.get("device")
                    or st_w.st_ino != exp.get("inode")
                ):
                    return (
                        True,
                        False,
                        f"WRAPPER_IDENTITY_CHANGED: Wrapper '{w_lex}' physical identity changed",
                        {
                            "wrapper_path": w_lex,
                            "expected_device": exp.get("device"),
                            "current_device": st_w.st_dev,
                            "expected_inode": exp.get("inode"),
                            "current_inode": st_w.st_ino,
                        },
                    )
                # Check enumeration fingerprint and mtime
                enum_mismatches = []
                details: dict[str, Any] = {"wrapper_path": w_lex}
                if "direct_children" in exp and exp["direct_children"] is not None:
                    try:
                        curr_children = _get_child_names(_scandir, w_lex)
                        if curr_children != exp["direct_children"]:
                            enum_mismatches.append("children")
                            details["expected_children"] = exp["direct_children"]
                            details["current_children"] = curr_children
                    except OSError as e:
                        raise BatchUtilityInvalidConfigError(
                            f"Failed to scan wrapper directory '{w_lex}': {e}",
                            details={
                                "wrapper_path": w_lex,
                                "errno": getattr(e, "errno", None),
                                "stage": "CONTINUITY",
                            },
                        )
                if st_w.st_mtime_ns != exp.get("mtime_ns"):
                    enum_mismatches.append("mtime_ns")
                    details["expected_mtime_ns"] = exp.get("mtime_ns")
                    details["current_mtime_ns"] = st_w.st_mtime_ns

                if enum_mismatches:
                    return (
                        False,
                        True,
                        f"WRAPPER_IDENTITY_CHANGED: Wrapper '{w_lex}' enumeration/mtime changed ({', '.join(enum_mismatches)})",
                        details,
                    )
            return (False, False, "", {})
        except FileNotFoundError:
            return (
                True,
                False,
                f"WRAPPER_IDENTITY_CHANGED: Wrapper '{w_lex}' does not exist",
                {"wrapper_path": w_lex, "error": "WRAPPER_MISSING"},
            )
        except OSError as e:
            return (
                True,
                False,
                f"WRAPPER_IDENTITY_CHANGED: Failed to access wrapper '{w_lex}': {e}",
                {"wrapper_path": w_lex, "errno": getattr(e, "errno", None)},
            )

    # Standalone wrapper-level continuity pass for all observed wrappers
    for obs in (wrapper_observations or []):
        w_lex = obs.get("wrapper_path")
        if not w_lex:
            continue
        wrapper_status[w_lex] = _validate_wrapper(w_lex, obs)

    def _check_wrapper(w_lex: str) -> tuple[bool, bool, str, dict[str, Any]]:
        if w_lex in wrapper_status:
            return wrapper_status[w_lex]
        exp = wrapper_obs_map.get(w_lex)
        status = _validate_wrapper(w_lex, exp)
        wrapper_status[w_lex] = status
        return status

    # Check if any wrapper failed continuity and has no candidate items
    observed_wrappers_with_items = {item.wrapper_path for item in items if item.wrapper_path}
    for w_lex, (is_c_rep, is_e_chg, w_reason, w_details) in wrapper_status.items():
        if (is_c_rep or is_e_chg) and w_lex not in observed_wrappers_with_items:
            conflicts.append(
                BlockingConflict(
                    source_path=w_lex,
                    target_path=w_lex,
                    conflict_type="WRAPPER_IDENTITY_CHANGED",
                    reason=w_reason,
                    details={"source_path": w_lex, **w_details},
                )
            )

    # Phase A: Fresh no-follow source observation & authority revalidation
    source_blocked_paths: set[str] = set()
    item_res_sources: dict[str, str] = {}
    items_by_resolved_source: dict[str, list[TargetItemCandidate]] = defaultdict(list)

    for item in items:
        src_lex = item.source_path
        tgt_lex = item.target_path
        src_p = Path(src_lex)
        is_blocked = False

        # 0. Wrapper continuity check
        w_container_replaced = False
        w_enum_changed = False
        w_reason = ""
        w_details: dict[str, Any] = {}
        if item.wrapper_path:
            w_container_replaced, w_enum_changed, w_reason, w_details = _check_wrapper(item.wrapper_path)
            if w_container_replaced:
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="WRAPPER_IDENTITY_CHANGED",
                        reason=w_reason,
                        details={"source_path": src_lex, **w_details},
                    )
                )
                is_blocked = True

        # 1. Fresh no-follow observation via lstat
        if not is_blocked:
            try:
                st_src = _lstat(src_lex)
            except FileNotFoundError:
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="SOURCE_MISSING",
                        reason="SOURCE_MISSING",
                        details={"source_path": src_lex, "error": "SOURCE_MISSING"},
                    )
                )
                is_blocked = True
            except OSError as e:
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="SOURCE_INACCESSIBLE",
                        reason=f"SOURCE_INACCESSIBLE: Failed to stat source path '{src_lex}': {e}",
                        details={"source_path": src_lex, "errno": getattr(e, "errno", None)},
                    )
                )
                is_blocked = True

        # 2. Symlink check on source
        if not is_blocked:
            if stat.S_ISLNK(st_src.st_mode):
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="WRAPPER_CHILD_SYMLINK",
                        reason=f"Source path '{src_lex}' is a symlink",
                        details={"source_path": src_lex},
                    )
                )
                is_blocked = True

        # 3. Object type verification & type race detection
        if not is_blocked:
            is_reg = stat.S_ISREG(st_src.st_mode)
            is_dir = stat.S_ISDIR(st_src.st_mode)
            if not (is_reg or is_dir):
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="UNSUPPORTED_OBJECT",
                        reason=f"UNSUPPORTED_OBJECT: Source '{src_lex}' is neither regular file nor directory",
                        details={"source_path": src_lex, "mode": st_src.st_mode},
                    )
                )
                is_blocked = True
            elif item.is_dir or (item.object_type == "directory"):
                if not is_dir:
                    conflicts.append(
                        BlockingConflict(
                            source_path=src_lex,
                            target_path=tgt_lex,
                            conflict_type="SOURCE_TYPE_CHANGED",
                            reason=f"SOURCE_TYPE_CHANGED: Directory source '{src_lex}' mutated to non-directory",
                            details={"source_path": src_lex, "expected_type": "directory", "current_type": "file" if is_reg else "unsupported"},
                        )
                    )
                    is_blocked = True
            else:
                # Discovery candidate observed regular file
                if not is_reg:
                    conflicts.append(
                        BlockingConflict(
                            source_path=src_lex,
                            target_path=tgt_lex,
                            conflict_type="SOURCE_TYPE_CHANGED",
                            reason=f"SOURCE_TYPE_CHANGED: File source '{src_lex}' mutated to non-file",
                            details={"source_path": src_lex, "expected_type": "file", "current_type": "directory" if is_dir else "unsupported"},
                        )
                    )
                    is_blocked = True

        # 3.5 Physical identity continuity verification against discovery candidate
        if not is_blocked:
            if item.device != 0 or item.inode != 0 or item.mtime_ns != 0:
                is_reg = stat.S_ISREG(st_src.st_mode)
                is_dir = stat.S_ISDIR(st_src.st_mode)
                mismatch_fields = []
                if st_src.st_dev != item.device:
                    mismatch_fields.append("device")
                if st_src.st_ino != item.inode:
                    mismatch_fields.append("inode")
                if st_src.st_mtime_ns != item.mtime_ns:
                    mismatch_fields.append("mtime_ns")
                if is_reg and st_src.st_size != item.size:
                    mismatch_fields.append("size")

                if mismatch_fields:
                    conflicts.append(
                        BlockingConflict(
                            source_path=src_lex,
                            target_path=tgt_lex,
                            conflict_type="SOURCE_IDENTITY_CHANGED",
                            reason=f"SOURCE_IDENTITY_CHANGED: Physical identity of source '{src_lex}' changed since discovery ({', '.join(mismatch_fields)})",
                            details={
                                "source_path": src_lex,
                                "mismatch_fields": mismatch_fields,
                                "expected_device": item.device,
                                "current_device": st_src.st_dev,
                                "expected_inode": item.inode,
                                "current_inode": st_src.st_ino,
                                "expected_mtime_ns": item.mtime_ns,
                                "current_mtime_ns": st_src.st_mtime_ns,
                                "expected_size": item.size,
                                "current_size": st_src.st_size,
                            },
                        )
                    )
                    is_blocked = True

        # 4. Strict physical resolution: resolve(strict=True)
        if not is_blocked:
            try:
                res_src = str(src_p.expanduser().resolve(strict=True))
            except FileNotFoundError:
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="SOURCE_MISSING",
                        reason="SOURCE_MISSING",
                        details={"source_path": src_lex, "error": "SOURCE_MISSING"},
                    )
                )
                is_blocked = True
            except OSError as e:
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="SOURCE_INACCESSIBLE",
                        reason=f"SOURCE_INACCESSIBLE: Failed to resolve source path '{src_lex}': {e}",
                        details={"source_path": src_lex, "errno": getattr(e, "errno", None)},
                    )
                )
                is_blocked = True

        # 5. Check allowed roots & quarantine containment
        if not is_blocked:
            if quarantine_root and is_reserved_quarantine_path(res_src, quarantine_root):
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="TARGET_OUTSIDE_ALLOWED_ROOT",
                        reason=f"Resolved source path '{res_src}' is within reserved quarantine storage",
                        details={"source_path": src_lex, "resolved_source_path": res_src},
                    )
                )
                is_blocked = True
            elif not is_path_allowed(res_src, allowed_roots):
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="TARGET_OUTSIDE_ALLOWED_ROOT",
                        reason=f"Resolved source path '{res_src}' is outside allowed roots",
                        details={"source_path": src_lex, "resolved_source_path": res_src},
                    )
                )
                is_blocked = True

        if not is_blocked and w_enum_changed:
            conflicts.append(
                BlockingConflict(
                    source_path=src_lex,
                    target_path=tgt_lex,
                    conflict_type="WRAPPER_IDENTITY_CHANGED",
                    reason=w_reason,
                    details={"source_path": src_lex, **w_details},
                )
            )
            is_blocked = True

        if is_blocked:
            source_blocked_paths.add(src_lex)
        else:
            item_res_sources[src_lex] = res_src
            items_by_resolved_source[res_src].append(item)

    # Detect duplicate physical sources among valid candidates
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
                source_blocked_paths.add(cand.source_path)

    # Phase B: Target validation via validate_mutation_destination & canonical target resolution
    resolved_targets_by_src: dict[str, str] = {}
    effective_items: list[TargetItemCandidate] = []

    for item in items:
        src_lex = item.source_path
        tgt_lex = item.target_path
        tgt_p = Path(tgt_lex)

        # Skip items whose source was blocked during Phase A
        if src_lex in source_blocked_paths:
            continue

        res_src = item_res_sources[src_lex]

        # Lexical symlink check on target
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
                    source_path=src_lex,
                    target_path=tgt_lex,
                    conflict_type="TARGET_SYMLINK",
                    reason=f"Target path '{tgt_lex}' already exists as a symlink",
                    details={"target_path": tgt_lex},
                )
            )
            resolved_targets_by_src[src_lex] = str(tgt_p)
            effective_items.append(item)
            continue

        try:
            canon_p = validate_mutation_destination(
                tgt_lex,
                roots=allowed_roots,
                quarantine_root=quarantine_root,
            )
            canon_tgt = str(canon_p)
            resolved_targets_by_src[src_lex] = canon_tgt

            # Check source and target belong to same containing root
            src_root = next((r for r in allowed_roots if Path(res_src).is_relative_to(r)), None)
            tgt_root = next((r for r in allowed_roots if canon_p.is_relative_to(r)), None)
            if src_root is None or tgt_root is None or src_root != tgt_root:
                conflicts.append(
                    BlockingConflict(
                        source_path=src_lex,
                        target_path=tgt_lex,
                        conflict_type="TARGET_OUTSIDE_ALLOWED_ROOT",
                        reason=f"Source '{res_src}' and target '{canon_tgt}' do not belong to the same containing root",
                        details={"source_path": src_lex, "resolved_source_path": res_src, "target_path": canon_tgt},
                    )
                )
                effective_items.append(item)
                continue

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
                resolved_source_path=res_src,
                resolved_target_path=canon_tgt,
                is_dir=item.is_dir,
                object_type=item.object_type,
                wrapper_path=item.wrapper_path,
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

    # 3. Planned target collisions
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

    # 4. Casefold checks (Blocker 1)
    # (a) planned target <-> planned target casefold in same parent directory
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

    # (b) planned target <-> existing directory entry casefold (scan target parent directories)
    target_parent_dirs = sorted({Path(resolved_targets_by_src[item.source_path]).parent for item in effective_items}, key=lambda p: str(p))
    directory_observations: list[dict[str, Any]] = []
    dir_entries_by_parent: dict[Path, list[str]] = {}
    failed_parent_dirs: set[Path] = set()

    for p_dir in target_parent_dirs:
        entries: list[str] = []
        scan_status = "OK"
        errno_val: int | None = None
        try:
            if p_dir.exists() and p_dir.is_dir():
                with _scandir(p_dir) as it:
                    for entry in it:
                        entries.append(entry.name)
        except OSError as e:
            scan_status = "FAILED"
            errno_val = getattr(e, "errno", None)
            failed_parent_dirs.add(p_dir)

        entries.sort()
        dir_entries_by_parent[p_dir] = entries
        obs_entry: dict[str, Any] = {
            "parent": str(p_dir),
            "scan_status": scan_status,
        }
        if errno_val is not None:
            obs_entry["errno"] = errno_val
        directory_observations.append(obs_entry)

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

    # 6. Vacating Occupant Semantics & Blocked Occupant Propagation (Blocker 2)
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

            # Check ancestor occupant dependency: if target contains a source that is blocked
            for occ_res_src, occ_list in items_by_resolved_source.items():
                try:
                    if Path(occ_res_src).is_relative_to(Path(res_tgt)) and occ_res_src != res_tgt:
                        if any(occ.source_path in blocked_sources for occ in occ_list):
                            conflicts.append(
                                BlockingConflict(
                                    source_path=item.source_path,
                                    target_path=item.target_path,
                                    conflict_type="TARGET_EXISTS",
                                    reason=f"Descendant source '{occ_list[0].source_path}' inside target '{item.target_path}' is blocked and will not vacate",
                                    details={"target_path": item.target_path, "descendant_source": occ_list[0].source_path},
                                )
                            )
                            blocked_sources.add(item.source_path)
                            blocked_resolved_sources.add(_resolve_physical_source(item))
                            newly_blocked = True
                            break
                except (ValueError, AttributeError):
                    pass

        if not newly_blocked:
            break

    # 7. Dependency Graph & Kahn's Topological Sort on Unblocked Items (Blocker 2)
    unblocked_items = [item for item in effective_items if item.source_path not in blocked_sources]
    unblocked_by_res_src = {_resolve_physical_source(item): item for item in unblocked_items}

    prereqs: dict[str, set[str]] = {_resolve_physical_source(item): set() for item in unblocked_items}
    dependents: dict[str, set[str]] = {_resolve_physical_source(item): set() for item in unblocked_items}
    in_degree: dict[str, int] = {_resolve_physical_source(item): 0 for item in unblocked_items}
    dependency_edges: list[dict[str, str]] = []

    for item in unblocked_items:
        res_tgt = resolved_targets_by_src[item.source_path]
        item_src = _resolve_physical_source(item)

        # Rule 1: Direct occupant (target == another source)
        if res_tgt in unblocked_by_res_src:
            occupant = unblocked_by_res_src[res_tgt]
            occ_src = _resolve_physical_source(occupant)
            if occ_src != item_src:
                if occ_src not in prereqs[item_src]:
                    prereqs[item_src].add(occ_src)
                    dependents[occ_src].add(item_src)
                    in_degree[item_src] += 1
                    dependency_edges.append({"from_source": occupant.source_path, "to_source": item.source_path})

        # Rule 2: Ancestor / descendant dependency
        for other in unblocked_items:
            other_src = _resolve_physical_source(other)
            if other_src == item_src:
                continue

            # (a) Target of item is ancestor of other's source: other is inside item's target.
            # Other must vacate before item can place target.
            try:
                if Path(other_src).is_relative_to(Path(res_tgt)) and other_src != res_tgt:
                    if other_src not in prereqs[item_src]:
                        prereqs[item_src].add(other_src)
                        dependents[other_src].add(item_src)
                        in_degree[item_src] += 1
                        dependency_edges.append({"from_source": other.source_path, "to_source": item.source_path})
            except (ValueError, AttributeError):
                pass

            # (b) Target of other is inside target of item: item creates parent dir, other moves child inside.
            other_tgt = resolved_targets_by_src[other.source_path]
            try:
                if Path(other_tgt).is_relative_to(Path(res_tgt)) and other_tgt != res_tgt:
                    if item_src not in prereqs[other_src]:
                        prereqs[other_src].add(item_src)
                        dependents[item_src].add(other_src)
                        in_degree[other_src] += 1
                        dependency_edges.append({"from_source": item.source_path, "to_source": other.source_path})
            except (ValueError, AttributeError):
                pass

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

    # Cycle detection
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

    return GraphResolutionResult(
        ordered_items=tuple(ordered_sequence),
        conflicts=tuple(deduped_conflicts),
        has_blocking_conflicts=has_blocking,
        directory_observations=tuple(directory_observations),
        target_observations=tuple(target_observations),
        dependency_edges=tuple(dependency_edges),
    )
