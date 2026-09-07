from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Literal

from app.planning.dedupe_config import (
    AdvancedDedupeConfig,
    canonical_json_dumps,
    extract_file_extension,
)


@dataclass(frozen=True)
class DedupeMemberSnapshot:
    absolute_path: str
    relative_path: str
    scan_root_index: int
    scan_root_path: str
    mtime_ns: int
    size: int
    eligible_as_keep: bool = True
    safety_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DedupeGroupSnapshot:
    provenance_id: str | int
    content_hash: str
    file_size: int
    members: list[DedupeMemberSnapshot]


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
    norm_paths = sorted(os.path.normpath(m.absolute_path) for m in group.members)
    return hashlib.sha256(";".join(norm_paths).encode("utf-8")).hexdigest()


def compute_group_fingerprint(group: DedupeGroupSnapshot) -> str:
    members_data = []
    for m in sorted(group.members, key=lambda x: os.path.normpath(x.absolute_path)):
        members_data.append({
            "absolute_path": os.path.normpath(m.absolute_path),
            "relative_path": m.relative_path,
            "scan_root_index": m.scan_root_index,
            "scan_root_path": m.scan_root_path,
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
    for m in sorted(members, key=lambda x: os.path.normpath(x.absolute_path)):
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
            "absolute_path": os.path.normpath(m.absolute_path),
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
        "recommended_keep_path": os.path.normpath(recommended_keep_path) if recommended_keep_path else None,
        "quarantine_candidates": sorted(os.path.normpath(p) for p in quarantine_candidates),
        "members": members_payload,
    }
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def evaluate_group(
    group: DedupeGroupSnapshot,
    config: AdvancedDedupeConfig,
    current_released_bytes: dict[int, int] | None = None,
    all_scan_roots: list[int] | None = None,
) -> GroupDecisionResult:
    # 1. Structural Validation
    if len(group.members) < 2:
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
                selection_reason="insufficient_members",
            )
            for m in group.members
        ]
        fp = compute_decision_fingerprint("skipped", "INSUFFICIENT_MEMBERS", group.file_size, None, [], explains)
        return GroupDecisionResult(
            status="skipped",
            skip_reason="INSUFFICIENT_MEMBERS",
            file_size=group.file_size,
            recommended_keep=None,
            members=explains,
            quarantine_candidates=[],
            reclaimable_bytes=0,
            group_decision_fingerprint=fp,
        )

    norm_paths = [os.path.normpath(m.absolute_path) for m in group.members]
    if len(norm_paths) != len(set(norm_paths)):
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
                selection_reason="duplicate_member_path",
            )
            for m in group.members
        ]
        fp = compute_decision_fingerprint("skipped", "DUPLICATE_MEMBER_PATH", group.file_size, None, [], explains)
        return GroupDecisionResult(
            status="skipped",
            skip_reason="DUPLICATE_MEMBER_PATH",
            file_size=group.file_size,
            recommended_keep=None,
            members=explains,
            quarantine_candidates=[],
            reclaimable_bytes=0,
            group_decision_fingerprint=fp,
        )

    for m in group.members:
        if m.scan_root_index < 0:
            explains = [
                MemberDecisionExplain(
                    absolute_path=x.absolute_path,
                    scan_root_index=x.scan_root_index,
                    eligible_as_keep=x.eligible_as_keep,
                    safety_reasons=list(x.safety_reasons),
                    total_score=0,
                    contributions=[],
                    is_top_candidate=False,
                    recommended_keep=False,
                    selection_reason="invalid_scan_root_index",
                )
                for x in group.members
            ]
            fp = compute_decision_fingerprint("skipped", "INVALID_SCAN_ROOT_INDEX", group.file_size, None, [], explains)
            return GroupDecisionResult(
                status="skipped",
                skip_reason="INVALID_SCAN_ROOT_INDEX",
                file_size=group.file_size,
                recommended_keep=None,
                members=explains,
                quarantine_candidates=[],
                reclaimable_bytes=0,
                group_decision_fingerprint=fp,
            )
        if m.size != group.file_size:
            explains = [
                MemberDecisionExplain(
                    absolute_path=x.absolute_path,
                    scan_root_index=x.scan_root_index,
                    eligible_as_keep=x.eligible_as_keep,
                    safety_reasons=list(x.safety_reasons),
                    total_score=0,
                    contributions=[],
                    is_top_candidate=False,
                    recommended_keep=False,
                    selection_reason="member_size_mismatch",
                )
                for x in group.members
            ]
            fp = compute_decision_fingerprint("skipped", "MEMBER_SIZE_MISMATCH", group.file_size, None, [], explains)
            return GroupDecisionResult(
                status="skipped",
                skip_reason="MEMBER_SIZE_MISMATCH",
                file_size=group.file_size,
                recommended_keep=None,
                members=explains,
                quarantine_candidates=[],
                reclaimable_bytes=0,
                group_decision_fingerprint=fp,
            )

    # 2. Safety Eligibility Check
    eligible_members = [m for m in group.members if m.eligible_as_keep]

    if len(eligible_members) == 0:
        explains = [
            MemberDecisionExplain(
                absolute_path=m.absolute_path,
                scan_root_index=m.scan_root_index,
                eligible_as_keep=False,
                safety_reasons=list(m.safety_reasons),
                total_score=0,
                contributions=[],
                is_top_candidate=False,
                recommended_keep=False,
                selection_reason="ineligible",
            )
            for m in group.members
        ]
        fp = compute_decision_fingerprint("skipped", "NO_ELIGIBLE_KEEP_CANDIDATE", group.file_size, None, [], explains)
        return GroupDecisionResult(
            status="skipped",
            skip_reason="NO_ELIGIBLE_KEEP_CANDIDATE",
            file_size=group.file_size,
            recommended_keep=None,
            members=explains,
            quarantine_candidates=[],
            reclaimable_bytes=0,
            group_decision_fingerprint=fp,
        )

    # 3. Factor Scoring for Eligible Candidates
    member_contributions: dict[str, list[FactorContribution]] = {}

    factors = config.factors

    # A. Path Priority
    pp_active_rule_idx: int | None = None
    pp_active_rule_pattern: str | None = None
    if factors.path_priority.enabled and factors.path_priority.rules and factors.path_priority.weight > 0:
        for r_idx, rule in enumerate(factors.path_priority.rules):
            has_match = False
            for m in eligible_members:
                test_path = m.absolute_path if rule.scope == "absolute" else m.relative_path
                if fnmatchcase(test_path, rule.pattern):
                    has_match = True
                    break
            if has_match:
                pp_active_rule_idx = r_idx
                pp_active_rule_pattern = rule.pattern
                break

    for m in eligible_members:
        contribs: list[FactorContribution] = []

        # Path priority contribution
        if not factors.path_priority.enabled or factors.path_priority.weight == 0:
            contribs.append(FactorContribution("path_priority", factors.path_priority.weight, 0, "factor disabled"))
        elif pp_active_rule_idx is None:
            contribs.append(FactorContribution("path_priority", factors.path_priority.weight, 0, "no path rule matched"))
        else:
            rule = factors.path_priority.rules[pp_active_rule_idx]
            test_path = m.absolute_path if rule.scope == "absolute" else m.relative_path
            if fnmatchcase(test_path, rule.pattern):
                contribs.append(FactorContribution(
                    "path_priority",
                    factors.path_priority.weight,
                    factors.path_priority.weight,
                    f"matched active rule #{pp_active_rule_idx}: {rule.pattern}",
                ))
            else:
                contribs.append(FactorContribution(
                    "path_priority",
                    factors.path_priority.weight,
                    0,
                    f"did not match active rule #{pp_active_rule_idx}: {rule.pattern}",
                ))

        # Preferred extension contribution
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
            else:
                if extract_file_extension(m.absolute_path) == pe_active_ext:
                    contribs.append(FactorContribution(
                        "preferred_extension",
                        factors.preferred_extension.weight,
                        factors.preferred_extension.weight,
                        f"matched preferred extension '{pe_active_ext}'",
                    ))
                else:
                    contribs.append(FactorContribution(
                        "preferred_extension",
                        factors.preferred_extension.weight,
                        0,
                        f"did not match preferred extension '{pe_active_ext}'",
                    ))

        # Mtime contribution
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

    # Compute total score per eligible member
    scores: dict[str, int] = {
        m.absolute_path: sum(c.actual_contribution for c in member_contributions[m.absolute_path])
        for m in eligible_members
    }

    # Top candidates
    max_score = max(scores.values())
    top_candidates = [m for m in eligible_members if scores[m.absolute_path] == max_score]

    # 4. Selection (Single Eligible vs Weighted vs Balanced-by-Bytes)
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
            sorted_ties = sorted(top_candidates, key=lambda c: os.path.normpath(c.absolute_path))
            winner = sorted_ties[0]
            winner_reason = "deterministic_path_tie_break"
    elif config.selection_mode == "balanced_by_bytes":
        if len(top_candidates) == 1:
            winner = top_candidates[0]
            winner_reason = "unique_top_score"
        else:
            # Balancer simulation among top_candidates only
            roots_pool = set(all_scan_roots or [])
            for m in group.members:
                roots_pool.add(m.scan_root_index)
            sorted_roots = sorted(roots_pool)

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
                tie_key = os.path.normpath(cand.absolute_path)
                sim_options.append(((spread, sum_sq, tie_key), cand, spread))

            best_sim = min(sim_options, key=lambda opt: opt[0])
            winner = best_sim[1]
            winner_reason = "balanced_by_bytes"
            winner_balance_info = {
                "spread_before": spread_before,
                "spread_after": best_sim[2],
            }

    # 5. Build Member Explanations
    explains = []
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
            ))
        else:
            is_winner = (m.absolute_path == winner.absolute_path)
            is_top = (m.absolute_path in {tc.absolute_path for tc in top_candidates})
            if is_winner:
                sel_reason = winner_reason
            else:
                sel_reason = "quarantined"

            explains.append(MemberDecisionExplain(
                absolute_path=m.absolute_path,
                scan_root_index=m.scan_root_index,
                eligible_as_keep=True,
                safety_reasons=list(m.safety_reasons),
                total_score=scores[m.absolute_path],
                contributions=member_contributions[m.absolute_path],
                is_top_candidate=is_top,
                recommended_keep=is_winner,
                selection_reason=sel_reason,
                balance_info=winner_balance_info if is_winner else None,
            ))

    quarantine_candidates = [m.absolute_path for m in group.members if m.absolute_path != winner.absolute_path]
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
    )


def run_advanced_dedupe(
    groups: Iterable[DedupeGroupSnapshot],
    config: AdvancedDedupeConfig,
    scan_root_indices: list[int] | None = None,
) -> AdvancedDedupeResult:
    # 1. Global deterministic sorting of groups:
    # 1) group.file_size DESC
    # 2) content_hash ASC
    # 3) stable member-path fingerprint ASC
    raw_groups = list(groups)
    sorted_groups = sorted(
        raw_groups,
        key=lambda g: (-g.file_size, g.content_hash, _stable_group_path_fingerprint(g)),
    )

    # 2. Collect and initialize all scan roots
    roots_set = set(scan_root_indices or [])
    for g in sorted_groups:
        for m in g.members:
            roots_set.add(m.scan_root_index)
    all_scan_roots = sorted(roots_set)

    released_bytes_by_scan_root: dict[int, int] = {r: 0 for r in all_scan_roots}

    # 3. Evaluate groups sequentially, accumulating released bytes for balancer
    results: list[GroupDecisionResult] = []
    actionable_count = 0
    skipped_count = 0
    planned_quarantine_count = 0
    expected_reclaim_bytes = 0

    for group in sorted_groups:
        res = evaluate_group(
            group,
            config,
            current_released_bytes=released_bytes_by_scan_root,
            all_scan_roots=all_scan_roots,
        )
        results.append(res)
        if res.status == "actionable":
            actionable_count += 1
            planned_quarantine_count += len(res.quarantine_candidates)
            expected_reclaim_bytes += res.reclaimable_bytes
            # Accumulate released bytes by scan root for each quarantined member
            for m in group.members:
                if res.recommended_keep and m.absolute_path != res.recommended_keep.absolute_path:
                    released_bytes_by_scan_root[m.scan_root_index] = (
                        released_bytes_by_scan_root.get(m.scan_root_index, 0) + group.file_size
                    )
        else:
            skipped_count += 1

    summary = {
        "selection_mode": config.selection_mode,
        "actionable_group_count": actionable_count,
        "skipped_group_count": skipped_count,
        "planned_quarantine_count": planned_quarantine_count,
        "expected_reclaim_bytes": expected_reclaim_bytes,
        "all_scan_roots": all_scan_roots,
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
