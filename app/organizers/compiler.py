from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable

from app.organizers.advanced_rules import (
    OrganizerAdvancedRules,
    advanced_rules_enabled,
    normalize_advanced_rules,
)
from app.organizers.engine import OrganizerProposal, generate_organizer_proposals
from app.organizers.planner import detect_rename_cycles_and_sort, plan_organizer_operations
from app.path_safety import require_allowed_path, require_unreserved_path
from app.utils.sorting import natural_sort_key


MAX_ORGANIZER_PREVIEW_PROPOSALS = 50_000


@dataclass(frozen=True)
class OrganizerCompilation:
    summary: dict[str, Any]
    proposals: tuple[OrganizerProposal, ...]
    preview_operations: tuple[dict[str, Any], ...]
    config_digest: str
    source_snapshot_digest: str
    preview_digest: str
    advanced_rules: dict[str, Any]
    advanced_enabled: bool
    structural_required: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _relative_depth(root: Path, path: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return -1


def _is_excluded_path(
    path: Path,
    *,
    excluded_roots: tuple[Path, ...],
    exclude_dir_names: frozenset[str],
) -> bool:
    if any(part in exclude_dir_names for part in path.parts):
        return True
    resolved = path.resolve(strict=False)
    for excluded in excluded_roots:
        if resolved == excluded or resolved.is_relative_to(excluded):
            return True
    return False


def _validate_target_component(
    proposal: OrganizerProposal,
    *,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None,
) -> None:
    if proposal.conflict or not proposal.changed or proposal.proposal_type == "wrapper_collapse":
        return

    target = Path(proposal.target)
    target_name = target.name
    if not target_name or "/" in target_name or "\x00" in target_name:
        proposal.conflict = True
        proposal.conflict_reason = "INVALID_TARGET_NAME"
        return

    try:
        try:
            name_max = int(os.pathconf(target.parent, "PC_NAME_MAX"))
        except (OSError, ValueError, AttributeError):
            name_max = 255
        if len(os.fsencode(target_name)) > name_max:
            proposal.conflict = True
            proposal.conflict_reason = "NAME_TOO_LONG"
            return

        try:
            path_max = int(os.pathconf(target.parent, "PC_PATH_MAX"))
        except (OSError, ValueError, AttributeError):
            path_max = 4096
        if len(os.fsencode(str(target))) > path_max:
            proposal.conflict = True
            proposal.conflict_reason = "PATH_TOO_LONG"
            return
    except OSError:
        proposal.conflict = True
        proposal.conflict_reason = "PATH_LIMIT_CHECK_FAILED"
        return

    try:
        require_unreserved_path(
            require_allowed_path(target.parent, allowed_roots),
            quarantine_root,
        )
    except Exception:
        proposal.conflict = True
        proposal.conflict_reason = "OUTSIDE_ALLOWED_ROOT"
        return

    try:
        if target.is_symlink():
            proposal.conflict = True
            proposal.conflict_reason = "SYMLINK_BLOCKED"
    except OSError:
        proposal.conflict = True
        proposal.conflict_reason = "TARGET_INSPECTION_FAILED"


def _apply_depth_rule(
    root: Path,
    proposals: list[OrganizerProposal],
    rules: OrganizerAdvancedRules,
) -> None:
    # Advanced Organizer always preserves depth-1 directory names. The
    # directory_depth rule may move the rename threshold deeper, but can never
    # relax it below depth 2.
    threshold = (
        rules.directory_depth.rename_from_depth
        if rules.directory_depth.enabled
        else 2
    )
    for proposal in proposals:
        if proposal.object_type != "directory":
            continue
        depth = _relative_depth(root, Path(proposal.source))
        if depth < threshold:
            proposal.target = proposal.source
            proposal.changed = False
            proposal.conflict = False
            proposal.conflict_reason = None
            proposal.metadata["depth_preserved"] = True
            proposal.metadata["relative_depth"] = depth


def _apply_latest_child_prefix(
    root: Path,
    proposals: list[OrganizerProposal],
    rules: OrganizerAdvancedRules,
) -> None:
    rule = rules.latest_child_prefix
    if not rule.enabled:
        return

    by_parent: dict[Path, list[tuple[OrganizerProposal, int]]] = {}
    for proposal in proposals:
        if proposal.object_type != "directory":
            continue
        source = Path(proposal.source)
        parent = source.parent
        if _relative_depth(root, parent) < 1:
            continue
        try:
            st = source.stat(follow_symlinks=False)
        except OSError:
            proposal.conflict = True
            proposal.conflict_reason = "LATEST_CHILD_STAT_FAILED"
            continue
        if not stat.S_ISDIR(st.st_mode):
            continue
        by_parent.setdefault(parent, []).append((proposal, int(st.st_mtime_ns)))

    for parent, rows in by_parent.items():
        if not rows:
            continue
        newest = max(mtime for _proposal, mtime in rows)
        winners = [proposal for proposal, mtime in rows if mtime == newest]
        if len(winners) != 1:
            for proposal in winners:
                proposal.conflict = True
                proposal.conflict_reason = "LATEST_CHILD_TIE"
                proposal.metadata["latest_child_parent"] = str(parent)
                proposal.metadata["latest_child_mtime_ns"] = newest
            continue

        proposal = winners[0]
        target = Path(proposal.target)
        if not target.name.startswith(rule.prefix):
            proposal.target = str(target.with_name(f"{rule.prefix}{target.name}"))
            proposal.changed = Path(proposal.target) != Path(proposal.source)
        proposal.proposal_type = "latest_child_prefix"
        proposal.metadata["latest_child_parent"] = str(parent)
        proposal.metadata["latest_child_mtime_ns"] = newest
        proposal.metadata["latest_child_prefix"] = rule.prefix


def _discover_file_numbering(
    root: Path,
    *,
    rules: OrganizerAdvancedRules,
    excluded_roots: tuple[Path, ...],
    exclude_dir_names: frozenset[str],
) -> list[OrganizerProposal]:
    rule = rules.file_numbering
    if not rule.enabled:
        return []

    proposals: list[OrganizerProposal] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        parent = Path(current)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            candidate = parent / dirname
            try:
                if candidate.is_symlink() or _is_excluded_path(
                    candidate,
                    excluded_roots=excluded_roots,
                    exclude_dir_names=exclude_dir_names,
                ):
                    continue
            except OSError:
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        if _relative_depth(root, parent) < 1:
            continue

        file_rows: list[Path] = []
        for filename in filenames:
            source = parent / filename
            if _is_excluded_path(
                source,
                excluded_roots=excluded_roots,
                exclude_dir_names=exclude_dir_names,
            ):
                continue
            try:
                st = source.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or source.is_symlink():
                continue
            file_rows.append(source)

        file_rows.sort(key=lambda path: (natural_sort_key(path.name), path.name))
        for offset, source in enumerate(file_rows):
            number = str(rule.start + offset).zfill(rule.padding)
            suffix = source.suffix
            target = source.with_name(f"{number}{suffix}")
            proposals.append(
                OrganizerProposal(
                    source=str(source),
                    target=str(target),
                    images=0,
                    videos=0,
                    files=1,
                    folders=0,
                    total_bytes=int(source.stat(follow_symlinks=False).st_size),
                    preserved_tags=[],
                    has_suspicious_tag=False,
                    changed=target != source,
                    conflict=False,
                    proposal_type="file_rename",
                    object_type="file",
                    metadata={
                        "parent_path": str(parent),
                        "relative_parent_depth": _relative_depth(root, parent),
                        "number": rule.start + offset,
                        "padding": rule.padding,
                        "original_suffix": suffix,
                    },
                )
            )
    return proposals


def _discover_wrapper_shapes_readonly(
    root: Path,
    *,
    rules: OrganizerAdvancedRules,
    excluded_roots: tuple[Path, ...],
    exclude_dir_names: frozenset[str],
) -> list[OrganizerProposal]:
    """Discover structural wrapper shapes without capability probes or namespace writes.

    C1 preview is strictly read-only. The Gate6-B authoritative capability
    discovery intentionally creates disposable probe entries, so that probe is
    deferred to C3 structural Plan authorization.
    """
    rule = rules.single_child_wrapper_collapse
    if not rule.enabled:
        return []

    proposals: list[OrganizerProposal] = []
    try:
        depth1_entries = list(os.scandir(root))
    except OSError:
        return proposals

    for depth1_entry in sorted(depth1_entries, key=lambda entry: natural_sort_key(entry.name)):
        depth1 = Path(depth1_entry.path)
        try:
            d1_st = depth1_entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISLNK(d1_st.st_mode) or not stat.S_ISDIR(d1_st.st_mode):
            continue
        if _is_excluded_path(
            depth1,
            excluded_roots=excluded_roots,
            exclude_dir_names=exclude_dir_names,
        ):
            continue

        try:
            wrappers = list(os.scandir(depth1))
        except OSError:
            continue

        for wrapper_entry in sorted(wrappers, key=lambda entry: natural_sort_key(entry.name)):
            wrapper = Path(wrapper_entry.path)
            try:
                wrapper_st = wrapper_entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISLNK(wrapper_st.st_mode) or not stat.S_ISDIR(wrapper_st.st_mode):
                continue
            if _is_excluded_path(
                wrapper,
                excluded_roots=excluded_roots,
                exclude_dir_names=exclude_dir_names,
            ):
                continue

            try:
                children = list(os.scandir(wrapper))
            except OSError:
                continue
            if len(children) != 1:
                continue

            child_entry = children[0]
            child = Path(child_entry.path)
            target = depth1 / child.name
            try:
                child_st = child_entry.stat(follow_symlinks=False)
            except OSError:
                continue

            conflict = False
            reason: str | None = None
            if stat.S_ISLNK(child_st.st_mode):
                conflict = True
                reason = "WRAPPER_CHILD_SYMLINK"
            elif not stat.S_ISDIR(child_st.st_mode):
                conflict = True
                reason = "WRAPPER_CHILD_NOT_DIRECTORY"
            else:
                try:
                    if target.exists() or target.is_symlink():
                        conflict = True
                        reason = "WRAPPER_TARGET_EXISTS"
                except OSError:
                    conflict = True
                    reason = "WRAPPER_TARGET_INSPECTION_FAILED"

            proposals.append(
                OrganizerProposal(
                    source=str(child),
                    target=str(target),
                    images=0,
                    videos=0,
                    files=0,
                    folders=1,
                    total_bytes=0,
                    preserved_tags=[],
                    has_suspicious_tag=False,
                    changed=not conflict,
                    conflict=conflict,
                    conflict_reason=reason,
                    proposal_type="wrapper_collapse",
                    object_type="directory",
                    metadata={
                        "wrapper_path": str(wrapper),
                        "wrapper_device": int(wrapper_st.st_dev),
                        "wrapper_inode": int(wrapper_st.st_ino),
                        "child_device": int(child_st.st_dev),
                        "child_inode": int(child_st.st_ino),
                        "capability_state": "CAPABILITY_UNVERIFIED",
                        "preview_only": True,
                    },
                )
            )

    return proposals


def _apply_cross_proposal_conflicts(
    proposals: list[OrganizerProposal],
    *,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None,
) -> None:
    mutable = [
        proposal
        for proposal in proposals
        if proposal.changed and proposal.proposal_type != "wrapper_collapse"
    ]

    for proposal in mutable:
        _validate_target_component(
            proposal,
            allowed_roots=allowed_roots,
            quarantine_root=quarantine_root,
        )

    source_map = {
        os.path.normpath(proposal.source): proposal
        for proposal in mutable
    }
    target_claims: dict[tuple[str, str], OrganizerProposal] = {}
    duplicate_groups: dict[tuple[str, str], list[OrganizerProposal]] = {}

    for proposal in mutable:
        if proposal.conflict:
            continue
        target = Path(proposal.target)
        key = (os.path.normcase(str(target.parent)), target.name.casefold())
        if key in target_claims:
            duplicate_groups.setdefault(key, [target_claims[key]]).append(proposal)
        else:
            target_claims[key] = proposal

    for rows in duplicate_groups.values():
        for proposal in rows:
            proposal.conflict = True
            proposal.conflict_reason = "PLANNED_TARGET_COLLISION"

    for proposal in mutable:
        if proposal.conflict:
            continue
        target = Path(proposal.target)
        try:
            target_exists = target.exists() or target.is_symlink()
        except OSError:
            proposal.conflict = True
            proposal.conflict_reason = "TARGET_INSPECTION_FAILED"
            continue
        if not target_exists:
            continue

        target_key = os.path.normpath(str(target))
        if target_key == os.path.normpath(proposal.source):
            continue
        owner = source_map.get(target_key)
        if owner is None or owner.object_type != proposal.object_type:
            proposal.conflict = True
            proposal.conflict_reason = "TARGET_EXISTS"

    cycle_rows = [
        {"source": proposal.source, "target": proposal.target}
        for proposal in mutable
        if not proposal.conflict
    ]
    _ordered, cycle_sources = detect_rename_cycles_and_sort(cycle_rows)
    if cycle_sources:
        for proposal in mutable:
            if proposal.source in cycle_sources and not proposal.conflict:
                proposal.conflict = True
                proposal.conflict_reason = "RENAME_CYCLE"


def compile_organizer_preview(
    root: Path | str,
    *,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None,
    image_extensions: list[str],
    video_extensions: list[str],
    rename_template: str,
    statistics_template: str,
    preserve_tags: list[str],
    cleanup_patterns: list[str],
    numbering_mode: str,
    numbering_start: int,
    numbering_padding: int,
    mtime_mode: str,
    mtime_delay_seconds: float,
    recursive: bool,
    advanced_rules: dict[str, Any] | OrganizerAdvancedRules | None = None,
    excluded_roots: Iterable[Path | str] | None = None,
    exclude_dir_names: Iterable[str] | None = None,
    max_proposals: int = MAX_ORGANIZER_PREVIEW_PROPOSALS,
) -> OrganizerCompilation:
    safe_root = require_unreserved_path(
        require_allowed_path(root, allowed_roots),
        quarantine_root,
    )
    normalized_rules = normalize_advanced_rules(
        advanced_rules,
        recursive=recursive,
        mtime_mode=mtime_mode,
    )
    rules = OrganizerAdvancedRules.model_validate(normalized_rules or {})
    is_advanced = advanced_rules_enabled(rules)

    excluded = tuple(Path(path).resolve(strict=False) for path in (excluded_roots or ()))
    excluded_names = frozenset(
        str(name).strip() for name in (exclude_dir_names or ()) if str(name).strip()
    )

    legacy_summary, directory_proposals = generate_organizer_proposals(
        safe_root,
        allowed_roots=allowed_roots,
        image_extensions=image_extensions,
        video_extensions=video_extensions,
        rename_template=rename_template,
        statistics_template=statistics_template,
        preserve_tags=preserve_tags,
        cleanup_patterns=cleanup_patterns,
        numbering_mode=numbering_mode,
        numbering_start=numbering_start,
        numbering_padding=numbering_padding,
        mtime_mode=mtime_mode,
        mtime_delay_seconds=mtime_delay_seconds,
        recursive=recursive,
        excluded_roots=excluded_roots,
        exclude_dir_names=exclude_dir_names,
    )

    if is_advanced:
        _apply_depth_rule(safe_root, directory_proposals, rules)
        _apply_latest_child_prefix(safe_root, directory_proposals, rules)

    file_proposals = (
        _discover_file_numbering(
            safe_root,
            rules=rules,
            excluded_roots=excluded,
            exclude_dir_names=excluded_names,
        )
        if is_advanced
        else []
    )
    wrapper_proposals = (
        _discover_wrapper_shapes_readonly(
            safe_root,
            rules=rules,
            excluded_roots=excluded,
            exclude_dir_names=excluded_names,
        )
        if is_advanced
        else []
    )

    proposals = [*directory_proposals, *file_proposals, *wrapper_proposals]
    if len(proposals) > max_proposals:
        raise ValueError(
            f"Organizer Preview candidate limit exceeded: {len(proposals)} > {max_proposals}"
        )

    if is_advanced:
        _apply_cross_proposal_conflicts(
            proposals,
            allowed_roots=allowed_roots,
            quarantine_root=quarantine_root,
        )

    conflicts = sum(1 for proposal in proposals if proposal.conflict)
    changed = sum(1 for proposal in proposals if proposal.changed and not proposal.conflict)
    changed_directories = sum(
        1
        for proposal in directory_proposals
        if proposal.changed and not proposal.conflict
    )

    summary = {
        **legacy_summary,
        "changed_directories": changed_directories,
        "conflicts": conflicts,
        "advanced_changes": changed,
        "file_rename_candidates": len(file_proposals),
        "wrapper_candidates": len(wrapper_proposals),
        "structural_required": any(
            proposal.changed and not proposal.conflict
            for proposal in wrapper_proposals
        ),
    }

    config_payload = {
        "root": str(safe_root),
        "image_extensions": image_extensions,
        "video_extensions": video_extensions,
        "rename_template": rename_template,
        "statistics_template": statistics_template,
        "preserve_tags": preserve_tags,
        "cleanup_patterns": cleanup_patterns,
        "numbering_mode": numbering_mode,
        "numbering_start": numbering_start,
        "numbering_padding": numbering_padding,
        "mtime_mode": mtime_mode,
        "mtime_delay_seconds": mtime_delay_seconds,
        "recursive": recursive,
        "advanced_rules": normalized_rules,
        "exclude_dir_names": sorted(excluded_names),
    }
    config_digest = _sha256_json(config_payload)

    sorted_proposals = sorted(
        proposals,
        key=lambda proposal: (
            os.path.normpath(proposal.source),
            proposal.proposal_type,
            os.path.normpath(proposal.target),
        ),
    )
    proposal_rows = [proposal.to_dict() for proposal in sorted_proposals]
    proposal_digest = _sha256_json(proposal_rows)

    source_snapshot_rows: list[dict[str, Any]] = []
    for proposal in sorted_proposals:
        source = Path(proposal.source)
        try:
            source_st = os.lstat(source)
        except OSError as exc:
            raise ValueError(
                f"Organizer source changed during Preview compilation: {source}"
            ) from exc

        if stat.S_ISLNK(source_st.st_mode):
            source_type = "symlink"
        elif stat.S_ISDIR(source_st.st_mode):
            source_type = "directory"
        elif stat.S_ISREG(source_st.st_mode):
            source_type = "file"
        else:
            source_type = "special"

        source_snapshot_rows.append(
            {
                "source": str(source),
                "device": int(source_st.st_dev),
                "inode": int(source_st.st_ino),
                "size": int(source_st.st_size),
                "mtime_ns": int(source_st.st_mtime_ns),
                "ctime_ns": int(source_st.st_ctime_ns),
                "object_type": source_type,
            }
        )

    source_snapshot_digest = _sha256_json(source_snapshot_rows)
    preview_digest = _sha256_json(
        {
            "config_digest": config_digest,
            "source_snapshot_digest": source_snapshot_digest,
            "proposal_digest": proposal_digest,
            "summary": summary,
        }
    )

    if is_advanced:
        rename_proposals = [
            proposal
            for proposal in proposals
            if proposal.proposal_type != "wrapper_collapse"
        ]
        ordered_renames, cycle_sources = plan_organizer_operations(
            rename_proposals,
            include_touch=False,
            mtime_mode=mtime_mode,
        )
        if cycle_sources:
            raise ValueError(
                f"Detected rename cycle in Advanced Organizer Preview: {sorted(cycle_sources)}"
            )

        proposal_by_source = {proposal.source: proposal for proposal in rename_proposals}
        operation_rows: list[dict[str, Any]] = []
        sequence = 1

        for item in ordered_renames:
            proposal = proposal_by_source.get(item["source"])
            if proposal is None:
                continue
            operation_rows.append(
                {
                    "sequence": sequence,
                    "operation": "rename",
                    "source": item["source"],
                    "target": item["target"],
                    "changed": True,
                    "conflict": False,
                    "proposal_type": proposal.proposal_type,
                    "object_type": proposal.object_type,
                    "preview_only": True,
                    **proposal.metadata,
                }
            )
            sequence += 1

        if mtime_mode == "ordered":
            directory_proposals = [
                proposal
                for proposal in rename_proposals
                if proposal.object_type == "directory"
            ]
            touch_plan, touch_cycles = plan_organizer_operations(
                directory_proposals,
                include_touch=True,
                mtime_mode=mtime_mode,
            )
            if touch_cycles:
                raise ValueError(
                    f"Detected touch ordering cycle in Advanced Organizer Preview: {sorted(touch_cycles)}"
                )
            for item in touch_plan:
                if item.get("operation") != "touch":
                    continue
                operation_rows.append(
                    {
                        "sequence": sequence,
                        "operation": "touch",
                        "source": item["source"],
                        "target": None,
                        "changed": True,
                        "conflict": False,
                        "proposal_type": "touch",
                        "object_type": "directory",
                        "preview_only": True,
                    }
                )
                sequence += 1

        for proposal in proposals:
            if proposal.proposal_type == "wrapper_collapse" and (proposal.changed or proposal.conflict):
                operation_rows.append(
                    {
                        "sequence": sequence,
                        "operation": "move",
                        "source": proposal.source,
                        "target": proposal.target,
                        "changed": proposal.changed,
                        "conflict": proposal.conflict,
                        "conflict_reason": proposal.conflict_reason,
                        "proposal_type": proposal.proposal_type,
                        "object_type": proposal.object_type,
                        "preview_only": True,
                        **proposal.metadata,
                    }
                )
                sequence += 1
            elif proposal.conflict and proposal.proposal_type != "wrapper_collapse":
                operation_rows.append(
                    {
                        "sequence": sequence,
                        "operation": "conflict",
                        "source": proposal.source,
                        "target": proposal.target,
                        "changed": False,
                        "conflict": True,
                        "conflict_reason": proposal.conflict_reason,
                        "proposal_type": proposal.proposal_type,
                        "object_type": proposal.object_type,
                        "preview_only": True,
                        **proposal.metadata,
                    }
                )
                sequence += 1

        preview_operations = tuple(operation_rows)
    else:
        legacy_plan_items, cycle_sources = plan_organizer_operations(
            directory_proposals,
            include_touch=True,
            mtime_mode=mtime_mode,
        )
        if cycle_sources:
            raise ValueError(
                f"Detected rename cycle in Organizer Preview: {sorted(cycle_sources)}"
            )
        preview_operations = tuple(legacy_plan_items)

    return OrganizerCompilation(
        summary=summary,
        proposals=tuple(proposals),
        preview_operations=preview_operations,
        config_digest=config_digest,
        source_snapshot_digest=source_snapshot_digest,
        preview_digest=preview_digest,
        advanced_rules=normalized_rules,
        advanced_enabled=is_advanced,
        structural_required=bool(summary["structural_required"]),
    )
