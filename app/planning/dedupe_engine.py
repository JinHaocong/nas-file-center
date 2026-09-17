from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from app.planning.dedupe_config import (
    AdvancedDedupeConfig,
    canonical_json_dumps,
    extract_file_extension,
    validate_and_canonicalize_config,
)


LCA_DIRECT = "LCA_DIRECT"


def normalize_dedupe_path(path: str | Path) -> str:
    """Pure lexical normalization of POSIX path.

    - Preserves internal and leading/trailing filename whitespace
    - Canonicalizes single or repeated leading slashes (e.g. '//data/a' -> '/data/a')
    - Resolves '.' and '..' lexically
    - Case-sensitive
    - No filesystem access
    """
    s = str(path)
    if not s:
        return ""
    if s.startswith("/"):
        idx = 0
        while idx < len(s) and s[idx] == "/":
            idx += 1
        s = "/" + s[idx:]
    norm = os.path.normpath(s)
    if norm.startswith("//"):
        idx = 0
        while idx < len(norm) and norm[idx] == "/":
            idx += 1
        norm = "/" + norm[idx:]
    return norm


def _validate_authoritative_scan_roots(scan_roots: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(scan_roots, (list, tuple)) or len(scan_roots) == 0:
        raise ValueError("scan_roots must be a non-empty sequence of absolute path strings")
    norm_roots: list[str] = []
    seen: set[str] = set()
    for idx, r in enumerate(scan_roots):
        if type(r) is not str:
            raise ValueError(f"scan_roots[{idx}] must be a string, got {type(r).__name__}")
        if not r.startswith("/"):
            raise ValueError(f"scan_roots[{idx}] must be an absolute path starting with '/', got {r!r}")
        norm = normalize_dedupe_path(r)
        if not norm or not norm.startswith("/"):
            raise ValueError(f"scan_roots[{idx}] normalized to invalid path: {norm!r}")
        if norm in seen:
            raise ValueError(f"scan_roots contains duplicate root after normalization: {norm!r}")
        seen.add(norm)
        norm_roots.append(norm)
    return tuple(norm_roots)


def _is_lexical_contained(sub_path: str, root_path: str) -> bool:
    norm_sub = normalize_dedupe_path(sub_path)
    norm_root = normalize_dedupe_path(root_path)
    if norm_root == "/":
        return norm_sub.startswith("/")
    return norm_sub == norm_root or norm_sub.startswith(norm_root + "/")


def _lexical_relpath(sub_path: str, root_path: str) -> str:
    norm_sub = normalize_dedupe_path(sub_path)
    norm_root = normalize_dedupe_path(root_path)
    if norm_sub == norm_root:
        return ""
    if norm_root == "/":
        return norm_sub.lstrip("/")
    prefix = norm_root + "/"
    if norm_sub.startswith(prefix):
        return norm_sub[len(prefix):]
    return os.path.relpath(norm_sub, norm_root)


def directory_ancestors_to_scan_root(
    file_path: str | Path,
    scan_root_path: str | Path,
) -> tuple[str, ...]:
    """Return lexical directory ancestry from file parent through Scan Root."""
    norm_file = normalize_dedupe_path(file_path)
    norm_root = normalize_dedupe_path(scan_root_path)
    if not norm_file.startswith("/") or not norm_root.startswith("/"):
        raise ValueError("file_path and scan_root_path must be absolute paths")
    if not _is_lexical_contained(norm_file, norm_root) or norm_file == norm_root:
        raise ValueError("file_path must be a descendant of scan_root_path")

    current = normalize_dedupe_path(os.path.dirname(norm_file))
    if not _is_lexical_contained(current, norm_root):
        raise ValueError("file parent is outside scan_root_path")

    ancestry: list[str] = []
    while True:
        ancestry.append(current)
        if current == norm_root:
            break
        parent = normalize_dedupe_path(os.path.dirname(current))
        if parent == current or not _is_lexical_contained(parent, norm_root):
            raise ValueError("directory ancestry escaped scan_root_path")
        current = parent
    return tuple(ancestry)


def compute_same_root_lca(
    parent_paths: Sequence[str | Path],
    scan_root_path: str | Path,
) -> str:
    """Compute a deterministic lexical LCA inside one authoritative Scan Root."""
    if not parent_paths:
        raise ValueError("parent_paths must not be empty")
    norm_root = normalize_dedupe_path(scan_root_path)
    if not norm_root.startswith("/"):
        raise ValueError("scan_root_path must be absolute")

    normalized: list[str] = []
    for parent in parent_paths:
        norm_parent = normalize_dedupe_path(parent)
        if not norm_parent.startswith("/") or not _is_lexical_contained(norm_parent, norm_root):
            raise ValueError("all parent_paths must be inside the same authoritative scan root")
        normalized.append(norm_parent)

    try:
        lca = normalize_dedupe_path(os.path.commonpath(normalized))
    except ValueError as exc:
        raise ValueError("parent_paths do not share one lexical root") from exc
    if not _is_lexical_contained(lca, norm_root):
        raise ValueError("computed LCA escaped authoritative scan root")
    return lca


def derive_recursive_balance_bucket(
    parent_path: str | Path,
    lca_path: str | Path,
) -> str:
    """Return the first real child from LCA, or synthetic LCA_DIRECT."""
    parent = normalize_dedupe_path(parent_path)
    lca = normalize_dedupe_path(lca_path)
    if parent == lca:
        return LCA_DIRECT
    if not _is_lexical_contained(parent, lca):
        raise ValueError("parent_path must be equal to or below lca_path")
    rel = _lexical_relpath(parent, lca)
    if not rel or rel == ".":
        return LCA_DIRECT
    first = rel.split("/", 1)[0]
    if lca == "/":
        return "/" + first
    return normalize_dedupe_path(lca + "/" + first)


def accumulate_recursive_released_bytes(
    current: Mapping[str, int] | None,
    *,
    file_path: str | Path,
    scan_root_path: str | Path,
    file_size: int,
) -> dict[str, int]:
    """Purely add released bytes to the parent and every real ancestor to root."""
    if type(file_size) is not int or isinstance(file_size, bool) or file_size < 0:
        raise ValueError("file_size must be a non-negative integer")
    updated = {
        normalize_dedupe_path(path): int(value)
        for path, value in dict(current or {}).items()
    }
    for directory in directory_ancestors_to_scan_root(file_path, scan_root_path):
        updated[directory] = updated.get(directory, 0) + file_size
    return updated


@dataclass(frozen=True)
class DedupeMemberSnapshot:
    absolute_path: str
    relative_path: str
    scan_root_index: int
    scan_root_path: str
    mtime_ns: int
    size: int
    eligible_as_keep: bool = True
    safety_reasons: tuple[str, ...] = field(default_factory=tuple)
    top_level_dir: str | None = None

    def __post_init__(self):
        if type(self.absolute_path) is not str:
            raise ValueError(f"absolute_path must be a string, got {type(self.absolute_path).__name__}")
        if type(self.relative_path) is not str:
            raise ValueError(f"relative_path must be a string, got {type(self.relative_path).__name__}")
        if type(self.scan_root_index) is not int or isinstance(self.scan_root_index, bool):
            raise ValueError(f"scan_root_index cannot be boolean; strict non-negative integer required, got {self.scan_root_index!r}")
        if self.scan_root_index < 0:
            raise ValueError(f"scan_root_index must be >= 0, got {self.scan_root_index}")
        if type(self.scan_root_path) is not str:
            raise ValueError(f"scan_root_path must be a string, got {type(self.scan_root_path).__name__}")
        if type(self.mtime_ns) is not int or isinstance(self.mtime_ns, bool):
            raise ValueError(f"mtime_ns cannot be boolean; strict integer required, got {self.mtime_ns!r}")
        if type(self.size) is not int or isinstance(self.size, bool):
            raise ValueError(f"size cannot be boolean; strict non-negative integer required, got {self.size!r}")
        if self.size < 0:
            raise ValueError(f"size must be >= 0, got {self.size}")
        if type(self.eligible_as_keep) is not bool:
            raise ValueError(f"eligible_as_keep must be a boolean, got {self.eligible_as_keep!r}")
        if self.top_level_dir is not None and type(self.top_level_dir) is not str:
            raise ValueError(f"top_level_dir must be a string if provided, got {type(self.top_level_dir).__name__}")
        if not isinstance(self.safety_reasons, (list, tuple)):
            raise ValueError(f"safety_reasons must be a list or tuple, got {type(self.safety_reasons).__name__}")
        for r in self.safety_reasons:
            if type(r) is not str:
                raise ValueError(f"safety_reasons elements must be strings, got {type(r).__name__}")
        object.__setattr__(self, "safety_reasons", tuple(self.safety_reasons))


@dataclass(frozen=True)
class DedupeGroupSnapshot:
    provenance_id: str | int
    content_hash: str
    file_size: int
    members: tuple[DedupeMemberSnapshot, ...]

    def __post_init__(self):
        if type(self.provenance_id) not in (int, str) or isinstance(self.provenance_id, bool):
            raise ValueError(f"provenance_id must be a string or integer scalar, got {self.provenance_id!r}")
        if type(self.provenance_id) is str and not self.provenance_id.strip():
            raise ValueError("provenance_id string cannot be empty or blank")
        if type(self.content_hash) is not str or not self.content_hash.strip():
            raise ValueError("content_hash must be a non-empty string")
        if type(self.file_size) is not int or isinstance(self.file_size, bool):
            raise ValueError(f"file_size cannot be boolean; strict non-negative integer required, got {self.file_size!r}")
        if self.file_size < 0:
            raise ValueError(f"file_size must be >= 0, got {self.file_size}")
        if not isinstance(self.members, (list, tuple)):
            raise ValueError(f"members must be a list or tuple of DedupeMemberSnapshot, got {type(self.members).__name__}")
        for m in self.members:
            if not isinstance(m, DedupeMemberSnapshot):
                raise ValueError(f"members must only contain DedupeMemberSnapshot instances, got {type(m).__name__}")
        object.__setattr__(self, "members", tuple(self.members))


@dataclass(frozen=True)
class FactorContribution:
    factor: str
    configured_weight: int
    actual_contribution: int
    reason: str


@dataclass(frozen=True)
class MemberDecisionExplain:
    absolute_path: str
    scan_root_index: int
    eligible_as_keep: bool
    safety_reasons: list[str]
    total_score: int
    contributions: list[FactorContribution]
    is_top_candidate: bool
    recommended_keep: bool
    selection_reason: str
    balance_info: dict[str, Any] | None = None
    relative_path: str = ""
    scan_root_path: str = ""


@dataclass(frozen=True)
class GroupDecisionResult:
    status: Literal["actionable", "skipped"]
    skip_reason: str | None
    file_size: int
    recommended_keep: DedupeMemberSnapshot | None
    members: list[MemberDecisionExplain]
    quarantine_candidates: list[str]
    reclaimable_bytes: int
    group_decision_fingerprint: str
    group_provenance_id: int | str = 0


@dataclass(frozen=True)
class AdvancedDedupeResult:
    groups: list[GroupDecisionResult]
    actionable_group_count: int
    skipped_group_count: int
    planned_quarantine_count: int
    expected_reclaim_bytes: int
    released_bytes_by_scan_root: dict[int, int]
    summary: dict[str, Any]


def _stable_group_path_fingerprint(group: DedupeGroupSnapshot) -> str:
    norm_paths = sorted(normalize_dedupe_path(m.absolute_path) for m in group.members)
    return hashlib.sha256(canonical_json_dumps(norm_paths).encode("utf-8")).hexdigest()


def compute_group_fingerprint(group: DedupeGroupSnapshot) -> str:
    members_data = []
    for m in sorted(group.members, key=lambda x: normalize_dedupe_path(x.absolute_path)):
        members_data.append({
            "absolute_path": normalize_dedupe_path(m.absolute_path),
            "relative_path": m.relative_path,
            "scan_root_index": m.scan_root_index,
            "scan_root_path": normalize_dedupe_path(m.scan_root_path),
            "mtime_ns": m.mtime_ns,
            "size": m.size,
            "eligible_as_keep": m.eligible_as_keep,
            "safety_reasons": sorted(m.safety_reasons),
        })
    payload = {
        "provenance_id": str(group.provenance_id),
        "content_hash": group.content_hash,
        "file_size": group.file_size,
        "members": members_data,
    }
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def compute_decision_fingerprint(
    status: str,
    skip_reason: str | None,
    file_size: int,
    recommended_keep_path: str | None,
    quarantine_candidates: list[str],
    members: list[MemberDecisionExplain],
) -> str:
    members_payload = []
    for m in sorted(members, key=lambda x: normalize_dedupe_path(x.absolute_path)):
        contribs = [
            {
                "factor": c.factor,
                "configured_weight": c.configured_weight,
                "actual_contribution": c.actual_contribution,
                "reason": c.reason,
            }
            for c in m.contributions
        ]
        members_payload.append({
            "absolute_path": normalize_dedupe_path(m.absolute_path),
            "scan_root_index": m.scan_root_index,
            "eligible_as_keep": m.eligible_as_keep,
            "safety_reasons": sorted(m.safety_reasons),
            "total_score": m.total_score,
            "contributions": contribs,
            "is_top_candidate": m.is_top_candidate,
            "recommended_keep": m.recommended_keep,
            "selection_reason": m.selection_reason,
            "balance_info": m.balance_info,
        })
    payload = {
        "status": status,
        "skip_reason": skip_reason,
        "file_size": file_size,
        "recommended_keep_path": normalize_dedupe_path(recommended_keep_path) if recommended_keep_path else None,
        "quarantine_candidates": sorted(normalize_dedupe_path(p) for p in quarantine_candidates),
        "members": members_payload,
    }
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def _make_skipped_group_result(
    group: DedupeGroupSnapshot,
    skip_reason: str,
    selection_reason: str = "skipped",
) -> GroupDecisionResult:
    explains = [
        MemberDecisionExplain(
            absolute_path=m.absolute_path,
            scan_root_index=m.scan_root_index,
            eligible_as_keep=m.eligible_as_keep,
            safety_reasons=list(m.safety_reasons),
            total_score=0,
            contributions=[],
            is_top_candidate=False,
            recommended_keep=False,
            selection_reason=selection_reason,
            relative_path=m.relative_path,
            scan_root_path=m.scan_root_path,
        )
        for m in group.members
    ]
    explains.sort(key=lambda x: normalize_dedupe_path(x.absolute_path))
    fp = compute_decision_fingerprint("skipped", skip_reason, group.file_size, None, [], explains)
    return GroupDecisionResult(
        status="skipped",
        skip_reason=skip_reason,
        file_size=group.file_size,
        recommended_keep=None,
        members=explains,
        quarantine_candidates=[],
        reclaimable_bytes=0,
        group_decision_fingerprint=fp,
        group_provenance_id=group.provenance_id,
    )


def make_skipped_group_result(
    group: DedupeGroupSnapshot,
    skip_reason: str,
    selection_reason: str = "skipped",
) -> GroupDecisionResult:
    return _make_skipped_group_result(group, skip_reason, selection_reason)


def _recursive_same_root_balance(
    group: DedupeGroupSnapshot,
    top_candidates: Sequence[DedupeMemberSnapshot],
    *,
    norm_scan_roots: Sequence[str],
    current_released_bytes_by_directory: Mapping[str, int] | None,
    current_direct_released_bytes_by_directory: Mapping[str, int] | None,
) -> tuple[DedupeMemberSnapshot, dict[str, Any]]:
    root_index = group.members[0].scan_root_index
    scan_root = norm_scan_roots[root_index]
    parent_by_path = {
        m.absolute_path: normalize_dedupe_path(os.path.dirname(normalize_dedupe_path(m.absolute_path)))
        for m in group.members
    }
    lca = compute_same_root_lca(list(parent_by_path.values()), scan_root)
    bucket_by_path = {
        m.absolute_path: derive_recursive_balance_bucket(parent_by_path[m.absolute_path], lca)
        for m in group.members
    }
    bucket_keys = sorted(set(bucket_by_path.values()), key=str)
    current_dirs = {
        normalize_dedupe_path(path): int(value)
        for path, value in dict(current_released_bytes_by_directory or {}).items()
    }
    current_direct = {
        normalize_dedupe_path(path): int(value)
        for path, value in dict(current_direct_released_bytes_by_directory or {}).items()
    }
    before = {
        bucket: (current_direct.get(lca, 0) if bucket == LCA_DIRECT else current_dirs.get(bucket, 0))
        for bucket in bucket_keys
    }
    before_values = list(before.values())
    spread_before = max(before_values, default=0) - min(before_values, default=0)
    sim_options = []
    for cand in top_candidates:
        sim = dict(before)
        for other in group.members:
            if other.absolute_path != cand.absolute_path:
                bucket = bucket_by_path[other.absolute_path]
                sim[bucket] = sim.get(bucket, 0) + group.file_size
        vals = list(sim.values())
        spread = max(vals, default=0) - min(vals, default=0)
        sum_sq = sum(v ** 2 for v in vals)
        tie_key = normalize_dedupe_path(cand.absolute_path)
        sim_options.append(((spread, sum_sq, tie_key), cand, sim))
    best_key, winner, best_after = min(sim_options, key=lambda opt: opt[0])
    return winner, {
        "selection_mode": "recursive_directory_balanced_by_bytes",
        "lca": lca,
        "bucket": bucket_by_path[winner.absolute_path],
        "bucket_released_bytes_before": before,
        "bucket_released_bytes_after": best_after,
        "spread_before": spread_before,
        "spread_after": best_key[0],
        "sum_squares_after": best_key[1],
    }


def _project_scan_root_balance(
    group: DedupeGroupSnapshot,
    *,
    keep_root_index: int,
    norm_scan_roots: Sequence[str],
    current_released_bytes: Mapping[int, int] | None,
) -> tuple[dict[int, int], int, int]:
    projected = {
        index: int(dict(current_released_bytes or {}).get(index, 0))
        for index in range(len(norm_scan_roots))
    }
    members_per_root = Counter(m.scan_root_index for m in group.members)
    for root_index, member_count in members_per_root.items():
        quarantine_count = member_count - (1 if root_index == keep_root_index else 0)
        projected[root_index] = projected.get(root_index, 0) + quarantine_count * group.file_size
    values = [projected.get(index, 0) for index in range(len(norm_scan_roots))]
    spread = max(values, default=0) - min(values, default=0)
    sum_sq = sum(value ** 2 for value in values)
    return projected, spread, sum_sq


def _recursive_cross_root_balance(
    group: DedupeGroupSnapshot,
    top_candidates: Sequence[DedupeMemberSnapshot],
    *,
    norm_scan_roots: Sequence[str],
    current_released_bytes: Mapping[int, int] | None,
    current_released_bytes_by_directory: Mapping[str, int] | None,
    current_direct_released_bytes_by_directory: Mapping[str, int] | None,
) -> tuple[DedupeMemberSnapshot, dict[str, Any]]:
    root_before = {
        index: int(dict(current_released_bytes or {}).get(index, 0))
        for index in range(len(norm_scan_roots))
    }
    root_values_before = list(root_before.values())
    root_spread_before = max(root_values_before, default=0) - min(root_values_before, default=0)
    roots_with_top_candidates = sorted({m.scan_root_index for m in top_candidates})
    root_options: list[tuple[tuple[int, int], int, dict[int, int]]] = []
    for root_index in roots_with_top_candidates:
        projected, spread, sum_sq = _project_scan_root_balance(
            group,
            keep_root_index=root_index,
            norm_scan_roots=norm_scan_roots,
            current_released_bytes=current_released_bytes,
        )
        root_options.append(((spread, sum_sq), root_index, projected))
    best_root_metric = min(option[0] for option in root_options)
    tied_root_options = [option for option in root_options if option[0] == best_root_metric]
    concrete_options: list[tuple[tuple[int, int, str], DedupeMemberSnapshot, dict[str, Any]]] = []
    for root_metric, root_index, projected_root_bytes in tied_root_options:
        root_top_candidates = [m for m in top_candidates if m.scan_root_index == root_index]
        root_members = tuple(m for m in group.members if m.scan_root_index == root_index)
        if len(root_top_candidates) == 1:
            candidate = root_top_candidates[0]
            directory_metric = (0, 0)
            directory_info: dict[str, Any] = {
                "selection_mode": "recursive_directory_balanced_by_bytes",
                "lca": None,
                "bucket": None,
                "bucket_released_bytes_before": {},
                "bucket_released_bytes_after": {},
                "spread_before": 0,
                "spread_after": 0,
                "sum_squares_after": 0,
            }
        else:
            root_group = DedupeGroupSnapshot(
                provenance_id=group.provenance_id,
                content_hash=group.content_hash,
                file_size=group.file_size,
                members=root_members,
            )
            candidate, directory_info = _recursive_same_root_balance(
                root_group,
                root_top_candidates,
                norm_scan_roots=norm_scan_roots,
                current_released_bytes_by_directory=current_released_bytes_by_directory,
                current_direct_released_bytes_by_directory=current_direct_released_bytes_by_directory,
            )
            directory_metric = (int(directory_info["spread_after"]), int(directory_info["sum_squares_after"]))
        info = dict(directory_info)
        info.update({
            "selected_scan_root_index": root_index,
            "scan_root_released_bytes_before": root_before,
            "scan_root_released_bytes_after": projected_root_bytes,
            "scan_root_spread_before": root_spread_before,
            "scan_root_spread_after": root_metric[0],
            "scan_root_sum_squares_after": root_metric[1],
        })
        concrete_options.append(((directory_metric[0], directory_metric[1], normalize_dedupe_path(candidate.absolute_path)), candidate, info))
    _key, winner, balance_info = min(concrete_options, key=lambda option: option[0])
    return winner, balance_info


def _recursive_keep_blocked(
    group: DedupeGroupSnapshot,
    candidate: DedupeMemberSnapshot,
    *,
    directory_file_counts: Mapping[str, int],
    scheduled_quarantine_counts: Mapping[str, int] | None,
) -> bool:
    proposed: Counter[str] = Counter()
    for other in group.members:
        if other.absolute_path == candidate.absolute_path:
            continue
        for directory in directory_ancestors_to_scan_root(other.absolute_path, other.scan_root_path):
            proposed[directory] += 1
    scheduled = dict(scheduled_quarantine_counts or {})
    for directory, proposed_count in proposed.items():
        normalized = normalize_dedupe_path(directory)
        current_count = directory_file_counts.get(normalized)
        if current_count is None:
            return True
        if int(current_count) - int(scheduled.get(normalized, 0)) - proposed_count < 1:
            return True
    return False


def _mark_recursive_blocked_members(
    group: DedupeGroupSnapshot,
    blocked_paths: set[str],
) -> DedupeGroupSnapshot:
    members: list[DedupeMemberSnapshot] = []
    for member in group.members:
        if member.absolute_path in blocked_paths:
            reasons = tuple(member.safety_reasons)
            if "RECURSIVE_PROTECT_LAST_FILE" not in reasons:
                reasons = (*reasons, "RECURSIVE_PROTECT_LAST_FILE")
            members.append(DedupeMemberSnapshot(
                absolute_path=member.absolute_path,
                relative_path=member.relative_path,
                scan_root_index=member.scan_root_index,
                scan_root_path=member.scan_root_path,
                mtime_ns=member.mtime_ns,
                size=member.size,
                eligible_as_keep=False,
                safety_reasons=reasons,
                top_level_dir=member.top_level_dir,
            ))
        else:
            members.append(member)
    return DedupeGroupSnapshot(
        provenance_id=group.provenance_id,
        content_hash=group.content_hash,
        file_size=group.file_size,
        members=tuple(members),
    )


def evaluate_group(
    group: DedupeGroupSnapshot,
    config: AdvancedDedupeConfig,
    *,
    scan_roots: Sequence[str],
    current_released_bytes: dict[int, int] | None = None,
    current_released_bytes_by_directory: Mapping[str, int] | None = None,
    current_direct_released_bytes_by_directory: Mapping[str, int] | None = None,
    recursive_protect_last_file_counts: Mapping[str, int] | None = None,
    recursive_scheduled_quarantine_counts: Mapping[str, int] | None = None,
) -> GroupDecisionResult:
    config = validate_and_canonicalize_config(config)
    if len(group.members) < 2:
        return _make_skipped_group_result(group, "INSUFFICIENT_MEMBERS", "insufficient_members")
    norm_paths = [normalize_dedupe_path(m.absolute_path) for m in group.members]
    if len(norm_paths) != len(set(norm_paths)):
        return _make_skipped_group_result(group, "DUPLICATE_MEMBER_PATH", "duplicate_member_path")
    norm_scan_roots = _validate_authoritative_scan_roots(scan_roots)
    for m in group.members:
        norm_abs = normalize_dedupe_path(m.absolute_path)
        norm_root = normalize_dedupe_path(m.scan_root_path)
        if m.scan_root_index < 0 or m.scan_root_index >= len(norm_scan_roots):
            return _make_skipped_group_result(group, "INVALID_SCAN_ROOT_INDEX", "invalid_scan_root_index")
        if norm_root != norm_scan_roots[m.scan_root_index]:
            return _make_skipped_group_result(group, "SCAN_ROOT_PATH_MISMATCH", "scan_root_path_mismatch")
        if not norm_abs.startswith("/") or not norm_root.startswith("/"):
            return _make_skipped_group_result(group, "INVALID_ABSOLUTE_PATH", "invalid_absolute_path")
        if not _is_lexical_contained(norm_abs, norm_root):
            return _make_skipped_group_result(group, "PATH_OUTSIDE_SCAN_ROOT", "path_outside_scan_root")
        expected_rel = _lexical_relpath(norm_abs, norm_root)
        actual_rel = normalize_dedupe_path(m.relative_path) if m.relative_path.startswith("/") else os.path.normpath(m.relative_path)
        if actual_rel != expected_rel:
            return _make_skipped_group_result(group, "RELATIVE_PATH_MISMATCH", "relative_path_mismatch")
        if m.size != group.file_size:
            return _make_skipped_group_result(group, "MEMBER_SIZE_MISMATCH", "member_size_mismatch")

    eligible_members = [m for m in group.members if m.eligible_as_keep]
    if len(eligible_members) == 0:
        return _make_skipped_group_result(group, "NO_ELIGIBLE_KEEP_CANDIDATE", "ineligible")

    member_contributions: dict[str, list[FactorContribution]] = {}
    factors = config.factors
    pp_active_rule_idx: int | None = None
    if factors.path_priority.enabled and factors.path_priority.rules and factors.path_priority.weight > 0:
        for r_idx, rule in enumerate(factors.path_priority.rules):
            if any(fnmatchcase(m.absolute_path if rule.scope == "absolute" else m.relative_path, rule.pattern) for m in eligible_members):
                pp_active_rule_idx = r_idx
                break

    for m in eligible_members:
        contribs: list[FactorContribution] = []
        if not factors.path_priority.enabled or factors.path_priority.weight == 0:
            contribs.append(FactorContribution("path_priority", factors.path_priority.weight, 0, "factor disabled"))
        elif pp_active_rule_idx is None:
            contribs.append(FactorContribution("path_priority", factors.path_priority.weight, 0, "no path rule matched"))
        else:
            rule = factors.path_priority.rules[pp_active_rule_idx]
            test_path = m.absolute_path if rule.scope == "absolute" else m.relative_path
            if fnmatchcase(test_path, rule.pattern):
                contribs.append(FactorContribution("path_priority", factors.path_priority.weight, factors.path_priority.weight, f"matched active rule #{pp_active_rule_idx}: {rule.pattern}"))
            else:
                contribs.append(FactorContribution("path_priority", factors.path_priority.weight, 0, f"did not match active rule #{pp_active_rule_idx}: {rule.pattern}"))

        if not factors.preferred_extension.enabled or factors.preferred_extension.weight == 0:
            contribs.append(FactorContribution("preferred_extension", factors.preferred_extension.weight, 0, "factor disabled"))
        else:
            pe_active_ext: str | None = None
            for ext in factors.preferred_extension.extensions:
                if any(extract_file_extension(cand.absolute_path) == ext for cand in eligible_members):
                    pe_active_ext = ext
                    break
            if pe_active_ext is None:
                contribs.append(FactorContribution("preferred_extension", factors.preferred_extension.weight, 0, "no preferred extension matched"))
            elif extract_file_extension(m.absolute_path) == pe_active_ext:
                contribs.append(FactorContribution("preferred_extension", factors.preferred_extension.weight, factors.preferred_extension.weight, f"matched preferred extension '{pe_active_ext}'"))
            else:
                contribs.append(FactorContribution("preferred_extension", factors.preferred_extension.weight, 0, f"did not match preferred extension '{pe_active_ext}'"))

        if factors.mtime.mode == "none" or factors.mtime.weight == 0:
            contribs.append(FactorContribution("mtime", factors.mtime.weight, 0, "factor disabled"))
        elif factors.mtime.mode == "newest":
            max_mtime = max(x.mtime_ns for x in eligible_members)
            if m.mtime_ns == max_mtime:
                contribs.append(FactorContribution("mtime", factors.mtime.weight, factors.mtime.weight, f"newest mtime ({max_mtime} ns)"))
            else:
                contribs.append(FactorContribution("mtime", factors.mtime.weight, 0, f"older mtime ({m.mtime_ns} < {max_mtime})"))
        elif factors.mtime.mode == "oldest":
            min_mtime = min(x.mtime_ns for x in eligible_members)
            if m.mtime_ns == min_mtime:
                contribs.append(FactorContribution("mtime", factors.mtime.weight, factors.mtime.weight, f"oldest mtime ({min_mtime} ns)"))
            else:
                contribs.append(FactorContribution("mtime", factors.mtime.weight, 0, f"newer mtime ({m.mtime_ns} > {min_mtime})"))
        member_contributions[m.absolute_path] = contribs

    scores = {m.absolute_path: sum(c.actual_contribution for c in member_contributions[m.absolute_path]) for m in eligible_members}
    max_score = max(scores.values())
    top_candidates = [m for m in eligible_members if scores[m.absolute_path] == max_score]
    recursive_blocked_paths: set[str] = set()
    if config.selection_mode == "recursive_directory_balanced_by_bytes" and recursive_protect_last_file_counts is not None:
        safe_top_candidates: list[DedupeMemberSnapshot] = []
        for candidate in top_candidates:
            if _recursive_keep_blocked(
                group,
                candidate,
                directory_file_counts=recursive_protect_last_file_counts,
                scheduled_quarantine_counts=recursive_scheduled_quarantine_counts,
            ):
                recursive_blocked_paths.add(candidate.absolute_path)
            else:
                safe_top_candidates.append(candidate)
        if not safe_top_candidates:
            protected_group = _mark_recursive_blocked_members(group, recursive_blocked_paths)
            return _make_skipped_group_result(
                protected_group,
                "RECURSIVE_PROTECT_LAST_FILE_NO_SAFE_SELECTION",
                "recursive_protect_last_file",
            )
        top_candidates = safe_top_candidates

    winner: DedupeMemberSnapshot
    winner_reason: str
    winner_balance_info: dict[str, Any] | None = None
    if len(eligible_members) == 1:
        winner = eligible_members[0]
        winner_reason = "sole_eligible"
    elif config.selection_mode == "weighted":
        if len(top_candidates) == 1:
            winner = top_candidates[0]
            winner_reason = "unique_top_score"
        else:
            winner = min(top_candidates, key=lambda c: normalize_dedupe_path(c.absolute_path))
            winner_reason = "deterministic_path_tie_break"
    elif config.selection_mode == "balanced_by_bytes":
        if len(top_candidates) == 1:
            winner = top_candidates[0]
            winner_reason = "unique_top_score"
        else:
            sorted_roots = list(range(len(norm_scan_roots)))
            curr_rel = dict(current_released_bytes or {})
            vals_before = [curr_rel.get(r, 0) for r in sorted_roots]
            spread_before = max(vals_before, default=0) - min(vals_before, default=0)
            sim_options = []
            for cand in top_candidates:
                sim = dict(curr_rel)
                for other in group.members:
                    if other.absolute_path != cand.absolute_path:
                        sim[other.scan_root_index] = sim.get(other.scan_root_index, 0) + group.file_size
                vals = [sim.get(r, 0) for r in sorted_roots]
                spread = max(vals, default=0) - min(vals, default=0)
                sum_sq = sum(v ** 2 for v in vals)
                sim_options.append(((spread, sum_sq, normalize_dedupe_path(cand.absolute_path)), cand, spread))
            best_sim = min(sim_options, key=lambda opt: opt[0])
            winner = best_sim[1]
            winner_reason = "balanced_by_bytes"
            winner_balance_info = {"spread_before": spread_before, "spread_after": best_sim[2]}
    elif config.selection_mode == "recursive_directory_balanced_by_bytes":
        if len(top_candidates) == 1:
            winner = top_candidates[0]
            winner_reason = "unique_top_score"
        elif len({m.scan_root_index for m in group.members}) == 1:
            winner, winner_balance_info = _recursive_same_root_balance(
                group,
                top_candidates,
                norm_scan_roots=norm_scan_roots,
                current_released_bytes_by_directory=current_released_bytes_by_directory,
                current_direct_released_bytes_by_directory=current_direct_released_bytes_by_directory,
            )
            winner_reason = "recursive_directory_balanced_by_bytes"
        else:
            winner, winner_balance_info = _recursive_cross_root_balance(
                group,
                top_candidates,
                norm_scan_roots=norm_scan_roots,
                current_released_bytes=current_released_bytes,
                current_released_bytes_by_directory=current_released_bytes_by_directory,
                current_direct_released_bytes_by_directory=current_direct_released_bytes_by_directory,
            )
            winner_reason = "recursive_directory_balanced_by_bytes"

    explains: list[MemberDecisionExplain] = []
    for m in group.members:
        if not m.eligible_as_keep:
            explains.append(MemberDecisionExplain(
                absolute_path=m.absolute_path,
                scan_root_index=m.scan_root_index,
                eligible_as_keep=False,
                safety_reasons=list(m.safety_reasons),
                total_score=0,
                contributions=[],
                is_top_candidate=False,
                recommended_keep=False,
                selection_reason="ineligible",
                relative_path=m.relative_path,
                scan_root_path=m.scan_root_path,
            ))
        elif m.absolute_path in recursive_blocked_paths:
            reasons = list(m.safety_reasons)
            if "RECURSIVE_PROTECT_LAST_FILE" not in reasons:
                reasons.append("RECURSIVE_PROTECT_LAST_FILE")
            explains.append(MemberDecisionExplain(
                absolute_path=m.absolute_path,
                scan_root_index=m.scan_root_index,
                eligible_as_keep=False,
                safety_reasons=reasons,
                total_score=scores[m.absolute_path],
                contributions=member_contributions[m.absolute_path],
                is_top_candidate=True,
                recommended_keep=False,
                selection_reason="recursive_protect_last_file",
                relative_path=m.relative_path,
                scan_root_path=m.scan_root_path,
            ))
        else:
            is_winner = m.absolute_path == winner.absolute_path
            is_top = m.absolute_path in {tc.absolute_path for tc in top_candidates}
            explains.append(MemberDecisionExplain(
                absolute_path=m.absolute_path,
                scan_root_index=m.scan_root_index,
                eligible_as_keep=True,
                safety_reasons=list(m.safety_reasons),
                total_score=scores[m.absolute_path],
                contributions=member_contributions[m.absolute_path],
                is_top_candidate=is_top,
                recommended_keep=is_winner,
                selection_reason=winner_reason if is_winner else "quarantined",
                balance_info=winner_balance_info if is_winner else None,
                relative_path=m.relative_path,
                scan_root_path=m.scan_root_path,
            ))
    explains.sort(key=lambda x: normalize_dedupe_path(x.absolute_path))
    quarantine_candidates = sorted(
        [m.absolute_path for m in group.members if m.absolute_path != winner.absolute_path],
        key=normalize_dedupe_path,
    )
    reclaimable_bytes = group.file_size * len(quarantine_candidates)
    fp = compute_decision_fingerprint(
        status="actionable",
        skip_reason=None,
        file_size=group.file_size,
        recommended_keep_path=winner.absolute_path,
        quarantine_candidates=quarantine_candidates,
        members=explains,
    )
    return GroupDecisionResult(
        status="actionable",
        skip_reason=None,
        file_size=group.file_size,
        recommended_keep=winner,
        members=explains,
        quarantine_candidates=quarantine_candidates,
        reclaimable_bytes=reclaimable_bytes,
        group_decision_fingerprint=fp,
        group_provenance_id=group.provenance_id,
    )


def run_advanced_dedupe(
    groups: Iterable[DedupeGroupSnapshot],
    config: AdvancedDedupeConfig,
    *,
    scan_roots: Sequence[str],
    protect_last_file_counts: Mapping[str, int] | None = None,
    pre_skipped_reasons: Mapping[int | str, str] | None = None,
) -> AdvancedDedupeResult:
    config = validate_and_canonicalize_config(config)
    norm_scan_roots = _validate_authoritative_scan_roots(scan_roots)
    authoritative_indices = list(range(len(norm_scan_roots)))
    sorted_groups = sorted(
        list(groups),
        key=lambda g: (-g.file_size, g.content_hash, _stable_group_path_fingerprint(g)),
    )
    released_bytes_by_scan_root: dict[int, int] = {r: 0 for r in authoritative_indices}
    released_bytes_by_directory: dict[str, int] = {}
    direct_released_bytes_by_directory: dict[str, int] = {}
    scheduled_directory_deletes: Counter[str] = Counter()
    scheduled_recursive_quarantines: Counter[str] = Counter()
    recursive_mode = config.selection_mode == "recursive_directory_balanced_by_bytes"
    results: list[GroupDecisionResult] = []
    actionable_count = 0
    skipped_count = 0
    planned_quarantine_count = 0
    expected_reclaim_bytes = 0

    for group in sorted_groups:
        if pre_skipped_reasons and group.provenance_id in pre_skipped_reasons:
            res = _make_skipped_group_result(group, pre_skipped_reasons[group.provenance_id], "fs_safety_failed")
            results.append(res)
            skipped_count += 1
            continue

        if protect_last_file_counts is not None and not recursive_mode:
            modified_members = []
            any_modified = False
            for m in group.members:
                if not m.eligible_as_keep:
                    modified_members.append(m)
                    continue
                proposed_deletes: Counter[str] = Counter()
                for other in group.members:
                    if other.absolute_path != m.absolute_path:
                        top_dir = other.top_level_dir
                        if not top_dir:
                            root_p = Path(other.scan_root_path)
                            rel_p = Path(other.relative_path)
                            top_dir = str(root_p / rel_p.parts[0] if len(rel_p.parts) > 1 else root_p)
                        proposed_deletes[top_dir] += 1
                is_safe = True
                for top_dir, count in proposed_deletes.items():
                    current_cnt = protect_last_file_counts.get(top_dir)
                    if current_cnt is not None and current_cnt - scheduled_directory_deletes[top_dir] - count < 1:
                        is_safe = False
                        break
                if not is_safe:
                    modified_members.append(DedupeMemberSnapshot(
                        absolute_path=m.absolute_path,
                        relative_path=m.relative_path,
                        scan_root_index=m.scan_root_index,
                        scan_root_path=m.scan_root_path,
                        mtime_ns=m.mtime_ns,
                        size=m.size,
                        eligible_as_keep=False,
                        safety_reasons=(*m.safety_reasons, "PROTECT_LAST_FILE"),
                        top_level_dir=m.top_level_dir,
                    ))
                    any_modified = True
                else:
                    modified_members.append(m)
            if any_modified:
                orig_eligible_count = sum(1 for m in group.members if m.eligible_as_keep)
                group = DedupeGroupSnapshot(
                    provenance_id=group.provenance_id,
                    content_hash=group.content_hash,
                    file_size=group.file_size,
                    members=tuple(modified_members),
                )
                if orig_eligible_count > 0 and not any(m.eligible_as_keep for m in modified_members):
                    res = _make_skipped_group_result(group, "PROTECT_LAST_FILE_NO_SAFE_SELECTION", "protect_last_file")
                    results.append(res)
                    skipped_count += 1
                    continue

        res = evaluate_group(
            group,
            config,
            current_released_bytes=released_bytes_by_scan_root,
            current_released_bytes_by_directory=released_bytes_by_directory,
            current_direct_released_bytes_by_directory=direct_released_bytes_by_directory,
            recursive_protect_last_file_counts=(protect_last_file_counts if recursive_mode else None),
            recursive_scheduled_quarantine_counts=(scheduled_recursive_quarantines if recursive_mode else None),
            scan_roots=norm_scan_roots,
        )
        results.append(res)
        if res.status == "actionable":
            actionable_count += 1
            planned_quarantine_count += len(res.quarantine_candidates)
            expected_reclaim_bytes += res.reclaimable_bytes
            for m in group.members:
                if res.recommended_keep and m.absolute_path != res.recommended_keep.absolute_path:
                    if m.scan_root_index in released_bytes_by_scan_root:
                        released_bytes_by_scan_root[m.scan_root_index] += group.file_size
                    released_bytes_by_directory = accumulate_recursive_released_bytes(
                        released_bytes_by_directory,
                        file_path=m.absolute_path,
                        scan_root_path=m.scan_root_path,
                        file_size=group.file_size,
                    )
                    parent_dir = normalize_dedupe_path(os.path.dirname(normalize_dedupe_path(m.absolute_path)))
                    direct_released_bytes_by_directory[parent_dir] = direct_released_bytes_by_directory.get(parent_dir, 0) + group.file_size
                    if recursive_mode and protect_last_file_counts is not None:
                        for directory in directory_ancestors_to_scan_root(m.absolute_path, m.scan_root_path):
                            scheduled_recursive_quarantines[directory] += 1
                    top_dir = m.top_level_dir
                    if not top_dir:
                        root_p = Path(m.scan_root_path)
                        rel_p = Path(m.relative_path)
                        top_dir = str(root_p / rel_p.parts[0] if len(rel_p.parts) > 1 else root_p)
                    scheduled_directory_deletes[top_dir] += 1
        else:
            skipped_count += 1

    summary = {
        "selection_mode": config.selection_mode,
        "actionable_group_count": actionable_count,
        "skipped_group_count": skipped_count,
        "planned_quarantine_count": planned_quarantine_count,
        "expected_reclaim_bytes": expected_reclaim_bytes,
        "all_scan_roots": authoritative_indices,
    }
    return AdvancedDedupeResult(
        groups=results,
        actionable_group_count=actionable_count,
        skipped_group_count=skipped_count,
        planned_quarantine_count=planned_quarantine_count,
        expected_reclaim_bytes=expected_reclaim_bytes,
        released_bytes_by_scan_root=released_bytes_by_scan_root,
        summary=summary,
    )
