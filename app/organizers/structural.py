from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.batch_utilities.single_child_wrapper import discover_single_child_wrappers
from app.fs_ops import NoreplaceProbeCleanupError
from app.path_safety import require_allowed_path, require_unreserved_path


STRUCTURAL_ACTION = "single_child_wrapper_collapse"


@dataclass(frozen=True)
class OrganizerStructuralCompilation:
    operations: tuple[dict[str, Any], ...]
    candidate_rows: tuple[dict[str, Any], ...]
    structural_digest: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _norm(path: str | Path) -> str:
    return os.path.normpath(os.fspath(path))


def _proposal_value(proposal: Any, key: str, default: Any = None) -> Any:
    if isinstance(proposal, dict):
        return proposal.get(key, default)
    return getattr(proposal, key, default)


def _proposal_metadata(proposal: Any) -> dict[str, Any]:
    value = _proposal_value(proposal, "metadata", {})
    return value if isinstance(value, dict) else {}


def compile_organizer_structural_stage(
    root: Path | str,
    *,
    proposals: Sequence[Any],
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None,
    preview_digest: str,
    source_snapshot_digest: str,
    limit: int = 50_000,
) -> OrganizerStructuralCompilation:
    """Turn read-only wrapper proposals into an authoritative Stage-A plan.

    Organizer Preview intentionally avoids capability probes. Generate is the
    first point where the existing Gate6-B descriptor-bound discovery/capability
    probe is allowed to run. Every READY decision must exactly match the frozen
    Preview shape and physical identities before a MOVE -> rmdir_empty pair can
    be emitted.
    """
    safe_root = require_unreserved_path(
        require_allowed_path(root, allowed_roots),
        quarantine_root,
    )

    wrapper_proposals = [
        proposal
        for proposal in proposals
        if _proposal_value(proposal, "proposal_type") == "wrapper_collapse"
        and bool(_proposal_value(proposal, "changed", False))
        and not bool(_proposal_value(proposal, "conflict", False))
    ]
    if not wrapper_proposals:
        return OrganizerStructuralCompilation(
            operations=(),
            candidate_rows=(),
            structural_digest=_digest([]),
        )
    if len(wrapper_proposals) > limit:
        raise ValueError(
            f"Organizer structural candidate limit exceeded: {len(wrapper_proposals)} > {limit}"
        )

    scopes = sorted(
        {
            _norm(Path(_proposal_metadata(proposal)["wrapper_path"]).parent)
            for proposal in wrapper_proposals
        }
    )

    authoritative: dict[str, Any] = {}
    try:
        for scope in scopes:
            decisions = discover_single_child_wrappers(
                scope,
                str(safe_root),
                limit=limit,
            )
            for decision in decisions:
                authoritative[_norm(decision.wrapper_path)] = decision
    except NoreplaceProbeCleanupError as exc:
        raise ValueError(
            "Organizer structural capability probe cleanup failed; refusing to generate Stage A Plan"
        ) from exc

    rows: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    sequence = 1

    for proposal in sorted(
        wrapper_proposals,
        key=lambda row: _norm(_proposal_metadata(row)["wrapper_path"]),
    ):
        metadata = _proposal_metadata(proposal)
        wrapper_path = _norm(metadata["wrapper_path"])
        child_path = _norm(_proposal_value(proposal, "source"))
        target_path = _norm(_proposal_value(proposal, "target"))

        decision = authoritative.get(wrapper_path)
        if decision is None:
            raise ValueError(
                f"Organizer wrapper candidate disappeared before Generate: {wrapper_path}"
            )
        if not decision.selectable:
            reason = decision.capability_reason or decision.state
            raise ValueError(
                f"Organizer wrapper candidate is no longer READY: {wrapper_path} ({reason})"
            )
        if decision.child_object_type != "directory":
            raise ValueError(
                f"Organizer wrapper child is no longer a directory: {decision.child_path}"
            )

        expected_pairs = {
            "wrapper_path": (wrapper_path, _norm(decision.wrapper_path)),
            "child_path": (child_path, _norm(decision.child_path or "")),
            "target_path": (target_path, _norm(decision.target_path or "")),
            "wrapper_device": (int(metadata["wrapper_device"]), int(decision.wrapper_device)),
            "wrapper_inode": (int(metadata["wrapper_inode"]), int(decision.wrapper_inode)),
            "child_device": (int(metadata["child_device"]), int(decision.child_device or 0)),
            "child_inode": (int(metadata["child_inode"]), int(decision.child_inode or 0)),
        }
        mismatched = [
            key for key, (expected, actual) in expected_pairs.items()
            if expected != actual
        ]
        if mismatched:
            raise ValueError(
                "Organizer wrapper candidate changed between Preview and Generate: "
                + ", ".join(mismatched)
            )

        bound = {
            "candidate_id": decision.candidate_id,
            "utility_action": STRUCTURAL_ACTION,
            "organizer_structural": True,
            "organizer_structural_action": STRUCTURAL_ACTION,
            "wrapper_path": decision.wrapper_path,
            "wrapper_device": int(decision.wrapper_device),
            "wrapper_inode": int(decision.wrapper_inode),
            "child_path": decision.child_path,
            "child_device": int(decision.child_device or 0),
            "child_inode": int(decision.child_inode or 0),
            "child_object_type": decision.child_object_type,
            "capability_reason": decision.capability_reason,
            "target_path": decision.target_path,
            "preview_digest": preview_digest,
            "source_snapshot_digest": source_snapshot_digest,
        }
        rows.append(dict(bound))
        operations.append({
            "sequence": sequence,
            "operation": "move",
            "source": decision.child_path,
            "target": decision.target_path,
            **bound,
        })
        sequence += 1
        operations.append({
            "sequence": sequence,
            "operation": "rmdir_empty",
            "source": decision.wrapper_path,
            "target": None,
            **bound,
        })
        sequence += 1

    return OrganizerStructuralCompilation(
        operations=tuple(operations),
        candidate_rows=tuple(rows),
        structural_digest=_digest(rows),
    )
