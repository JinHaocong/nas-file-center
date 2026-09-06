from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.filters.compiler import compile_filter_to_sql
from app.filters.excludes import DEFAULT_EXCLUDE_DIR_NAMES, build_exclude_predicates
from app.filters.validation import validate_filter_ast
from app.models import FilterPolicy, IndexRoot, IndexedPath
from app.organizers.engine import generate_organizer_proposals
from app.organizers.planner import plan_organizer_operations
from app.path_safety import require_allowed_path, require_unreserved_path
from app.workflows.errors import (
    VirtualGraphCollisionError,
    VirtualGraphCycleError,
    WorkflowSafetyLimitExceededError,
    WorkflowValidationError,
)
from app.workflows.graph import VirtualCandidate, VirtualPathGraph
from app.workflows.revisions import compute_definition_sha256
from app.workflows.schema import (
    FilterStep,
    MoveStep,
    OrganizeStep,
    QuarantineStep,
    RenameStep,
    ScanStep,
    TouchStep,
    WorkflowDefinition,
)

MAX_WORKFLOW_CANDIDATES = 50_000
MAX_WORKFLOW_PLAN_ITEMS = 100_000


@dataclass
class CompilationResult:
    matched_count: int
    matched_bytes: int
    planned_operations: list[dict[str, Any]]
    compile_digest: str
    runtime_inputs: dict[str, Any]
    compile_context: dict[str, Any]


class WorkflowCompiler:
    def __init__(
        self,
        session: Session,
        allowed_roots: Iterable[Path | str],
        quarantine_root: Path | str | None = None,
    ):
        self.session = session
        self.allowed_roots = [str(r) for r in allowed_roots]
        self.quarantine_root = str(quarantine_root) if quarantine_root else None

    def compile(
        self,
        definition: WorkflowDefinition,
        *,
        workflow_id: int | None = None,
        workflow_revision: int | None = None,
        definition_sha256: str | None = None,
        override_root_ids: list[int] | None = None,
        max_candidates: int = MAX_WORKFLOW_CANDIDATES,
        max_plan_items: int = MAX_WORKFLOW_PLAN_ITEMS,
    ) -> CompilationResult:
        """Compile a validated workflow definition into planned operations with compile_digest."""
        if definition.mode == "organizer":
            return self._compile_organizer_workflow(
                definition,
                workflow_id=workflow_id,
                workflow_revision=workflow_revision,
                definition_sha256=definition_sha256,
                override_root_ids=override_root_ids,
                max_candidates=max_candidates,
                max_plan_items=max_plan_items,
            )
        elif definition.mode == "file":
            return self._compile_file_workflow(
                definition,
                workflow_id=workflow_id,
                workflow_revision=workflow_revision,
                definition_sha256=definition_sha256,
                override_root_ids=override_root_ids,
                max_candidates=max_candidates,
                max_plan_items=max_plan_items,
            )
        else:
            raise WorkflowValidationError(f"Unsupported workflow mode: {definition.mode}")

    def _compile_organizer_workflow(
        self,
        definition: WorkflowDefinition,
        *,
        workflow_id: int | None = None,
        workflow_revision: int | None = None,
        definition_sha256: str | None = None,
        override_root_ids: list[int] | None = None,
        max_candidates: int = MAX_WORKFLOW_CANDIDATES,
        max_plan_items: int = MAX_WORKFLOW_PLAN_ITEMS,
    ) -> CompilationResult:
        scan_step: ScanStep = definition.steps[0]  # type: ignore
        organize_step: OrganizeStep = definition.steps[1]  # type: ignore
        snapshot_raw = organize_step.profile_snapshot
        snapshot = snapshot_raw.model_dump() if hasattr(snapshot_raw, "model_dump") else (snapshot_raw if isinstance(snapshot_raw, dict) else {})

        effective_root_ids = override_root_ids if override_root_ids is not None else scan_step.root_ids
        target_root_str: str | None = None

        if effective_root_ids is not None:
            if len(effective_root_ids) != 1:
                raise WorkflowValidationError(
                    f"Organizer workflow requires exactly one root, got {len(effective_root_ids)}",
                    code="ORGANIZER_SINGLE_ROOT_REQUIRED" if len(effective_root_ids) > 1 else "ROOT_REQUIRED",
                )
            first_root_id = effective_root_ids[0]
            root_record = self.session.scalar(select(IndexRoot.root).where(IndexRoot.id == first_root_id))
            if not root_record:
                raise WorkflowValidationError(
                    f"Index root {first_root_id} not found",
                    code="INDEX_ROOT_NOT_FOUND",
                )
            target_root_str = root_record
        elif snapshot.get("root"):
            target_root_str = snapshot.get("root")

        if not target_root_str or not str(target_root_str).strip():
            raise WorkflowValidationError("No target root found for organizer workflow", code="ROOT_REQUIRED")

        try:
            safe_root = require_unreserved_path(
                require_allowed_path(str(target_root_str).strip(), self.allowed_roots),
                self.quarantine_root,
            )
        except Exception as e:
            raise WorkflowValidationError(str(e), code="INDEX_ROOT_NOT_FOUND")

        image_extensions = snapshot.get("image_extensions") or []
        if isinstance(image_extensions, str):
            try:
                image_extensions = json.loads(image_extensions)
            except Exception:
                image_extensions = []
        video_extensions = snapshot.get("video_extensions") or []
        if isinstance(video_extensions, str):
            try:
                video_extensions = json.loads(video_extensions)
            except Exception:
                video_extensions = []
        preserve_tags = snapshot.get("preserve_tags") or []
        if isinstance(preserve_tags, str):
            try:
                preserve_tags = json.loads(preserve_tags)
            except Exception:
                preserve_tags = []
        cleanup_patterns = snapshot.get("cleanup_patterns") or []
        if isinstance(cleanup_patterns, str):
            try:
                cleanup_patterns = json.loads(cleanup_patterns)
            except Exception:
                cleanup_patterns = []

        # Read global exclusion policy
        policy = self.session.get(FilterPolicy, 1)
        excludes: list[str] = []
        if policy and policy.exclude_dir_names_json:
            try:
                excludes = json.loads(policy.exclude_dir_names_json)
            except Exception:
                excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)
        else:
            excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)

        quarantine_ex = [self.quarantine_root] if self.quarantine_root else None
        summary, proposals = generate_organizer_proposals(
            safe_root,
            allowed_roots=self.allowed_roots,
            image_extensions=image_extensions,
            video_extensions=video_extensions,
            rename_template=snapshot.get("rename_template") or "{name} {statistics}",
            statistics_template=snapshot.get("statistics_template") or "[{images}P{?videos: {videos}V} {size}]",
            preserve_tags=preserve_tags,
            cleanup_patterns=cleanup_patterns,
            numbering_mode=snapshot.get("numbering_mode") or "none",
            numbering_start=int(snapshot.get("numbering_start") or 1),
            numbering_padding=int(snapshot.get("numbering_padding") or 3),
            mtime_mode=snapshot.get("mtime_mode") or "none",
            mtime_delay_seconds=float(snapshot.get("mtime_delay_seconds") or 2.0),
            recursive=bool(snapshot.get("recursive", False)),
            excluded_roots=quarantine_ex,
            exclude_dir_names=excludes,
        )

        if len(proposals) > max_candidates:
            raise WorkflowSafetyLimitExceededError(
                f"Candidate count ({len(proposals)}) exceeds safety limit ({max_candidates})",
                details={"candidates": len(proposals), "limit": max_candidates},
            )

        if summary.get("conflicts", 0) > 0:
            conflict_reasons = [p.conflict_reason for p in proposals if p.conflict and p.conflict_reason]
            raise VirtualGraphCollisionError(
                f"Organizer proposals contain {summary['conflicts']} conflicts",
                details={"conflicts": conflict_reasons[:5]},
            )

        items, cycle_sources = plan_organizer_operations(
            proposals,
            include_touch=True,
            mtime_mode=snapshot.get("mtime_mode") or "none",
        )
        if cycle_sources:
            raise VirtualGraphCycleError(
                f"Detected rename cycle in organizer proposals: {sorted(cycle_sources)}",
                details={"cycle_sources": sorted(cycle_sources)},
            )

        if len(items) > max_plan_items:
            raise WorkflowSafetyLimitExceededError(
                f"Planned operations count ({len(items)}) exceeds safety limit ({max_plan_items})",
                details={"planned_operations_count": len(items), "limit": max_plan_items},
            )

        runtime_inputs = {
            "root_ids": sorted(effective_root_ids) if effective_root_ids is not None else [],
        }

        compile_context = {
            "effective_exclude_dir_names": sorted(list(set(excludes))),
            "filter_policy_updated_at": policy.updated_at.isoformat() if policy and policy.updated_at else None,
        }

        digest_payload = {
            "workflow_id": workflow_id,
            "workflow_revision": workflow_revision,
            "definition_sha256": definition_sha256 or compute_definition_sha256(definition.model_dump()),
            "runtime_inputs": runtime_inputs,
            "compile_context": compile_context,
            "planned_operations": items,
        }
        digest = compute_definition_sha256(digest_payload)

        return CompilationResult(
            matched_count=summary.get("total_directories", len(proposals)),
            matched_bytes=summary.get("total_size", 0),
            planned_operations=items,
            compile_digest=digest,
            runtime_inputs=runtime_inputs,
            compile_context=compile_context,
        )

    def _compile_file_workflow(
        self,
        definition: WorkflowDefinition,
        *,
        workflow_id: int | None = None,
        workflow_revision: int | None = None,
        definition_sha256: str | None = None,
        override_root_ids: list[int] | None = None,
        max_candidates: int = MAX_WORKFLOW_CANDIDATES,
        max_plan_items: int = MAX_WORKFLOW_PLAN_ITEMS,
    ) -> CompilationResult:
        scan_step: ScanStep = definition.steps[0]  # type: ignore
        effective_root_ids = override_root_ids if override_root_ids is not None else scan_step.root_ids

        # Root filtering
        all_roots = self.session.scalars(select(IndexRoot)).all()
        root_map = {r.id: r.root for r in all_roots}
        root_key_to_id = {r.root: r.id for r in all_roots}

        if not effective_root_ids:
            raise WorkflowValidationError("At least one root is required", code="ROOT_REQUIRED")

        if len(effective_root_ids) > 16:
            raise WorkflowValidationError(
                f"Cannot scan more than 16 roots, got {len(effective_root_ids)}",
                code="ROOT_LIMIT_EXCEEDED",
            )

        for rid in effective_root_ids:
            if rid not in root_map:
                raise WorkflowValidationError(f"Index root {rid} not found", code="INDEX_ROOT_NOT_FOUND")
            try:
                require_allowed_path(root_map[rid], self.allowed_roots)
            except Exception:
                raise WorkflowValidationError(f"Index root {rid} is outside allowed roots", code="INDEX_ROOT_NOT_FOUND")

        target_roots = [root_map[rid] for rid in effective_root_ids]

        # Step 1: Candidate query on IndexedPath
        where_clauses = [
            IndexedPath.is_dir.is_(False),
            IndexedPath.root_key.in_(target_roots),
        ]

        if scan_step.subpath:
            sub = scan_step.subpath.strip().lstrip("/\\")
            if sub:
                esc_sub = sub.replace("!", "!!").replace("%", "!%").replace("_", "!_")
                where_clauses.append(
                    IndexedPath.relative_path.like(f"{esc_sub}/%", escape="!")
                    | (IndexedPath.relative_path == sub)
                )

        # Global exclude policy
        policy = self.session.get(FilterPolicy, 1)
        excludes = []
        if policy and policy.exclude_dir_names_json:
            try:
                excludes = json.loads(policy.exclude_dir_names_json)
            except Exception:
                excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)
        else:
            excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)

        where_clauses.append(
            build_exclude_predicates(
                excludes,
                quarantine_root=self.quarantine_root,
            )
        )

        # Filter steps
        for step in definition.steps:
            if isinstance(step, FilterStep):
                validated_node = validate_filter_ast(step.filter)
                where_clauses.append(compile_filter_to_sql(validated_node))

        combined_where = and_(*where_clauses)

        # Check candidate counts
        count_stmt = select(func.count(IndexedPath.id)).where(combined_where)
        sum_stmt = select(func.coalesce(func.sum(IndexedPath.size), 0)).where(combined_where)

        matched_count = self.session.scalar(count_stmt) or 0
        matched_bytes = self.session.scalar(sum_stmt) or 0

        if matched_count > max_candidates:
            raise WorkflowSafetyLimitExceededError(
                f"Candidate count ({matched_count}) exceeds safety limit ({max_candidates})",
                details={"matched_count": matched_count, "limit": max_candidates},
            )

        # Fetch candidates
        candidate_stmt = (
            select(IndexedPath)
            .where(combined_where)
            .order_by(IndexedPath.relative_path.asc(), IndexedPath.id.asc())
        )
        candidates = self.session.scalars(candidate_stmt).all()

        # Step 2: Virtual Simulation
        graph = VirtualPathGraph(
            allowed_roots=self.allowed_roots,
            quarantine_root=self.quarantine_root,
        )

        for c in candidates:
            rid = root_key_to_id.get(c.root_key, 0)
            graph.add_candidate(
                VirtualCandidate(
                    id=c.id,
                    original_path=c.absolute_path,
                    original_root_id=rid,
                    current_path=c.absolute_path,
                    current_root_id=rid,
                    size=c.size,
                    mtime_ns=c.mtime_ns,
                )
            )

        # Execute action steps with step index
        for idx, step in enumerate(definition.steps):
            if isinstance(step, RenameStep):
                graph.apply_rename(step, step_index=idx)
            elif isinstance(step, MoveStep):
                dest_root_rec = self.session.get(IndexRoot, step.destination_root_id)
                if not dest_root_rec:
                    raise WorkflowValidationError(
                        f"Destination root {step.destination_root_id} not found",
                        code="INDEX_ROOT_NOT_FOUND",
                    )
                graph.apply_move(step, dest_root_rec.root, step_index=idx)
            elif isinstance(step, TouchStep):
                graph.apply_touch(step, step_index=idx)
            elif isinstance(step, QuarantineStep):
                graph.apply_quarantine(step, step_index=idx)

        planned_ops = graph.resolve_ordered_operations()

        if len(planned_ops) > max_plan_items:
            raise WorkflowSafetyLimitExceededError(
                f"Planned operations count ({len(planned_ops)}) exceeds safety limit ({max_plan_items})",
                details={"planned_operations_count": len(planned_ops), "limit": max_plan_items},
            )

        runtime_inputs = {
            "root_ids": sorted(effective_root_ids) if effective_root_ids is not None else [],
        }

        compile_context = {
            "effective_exclude_dir_names": sorted(excludes),
            "filter_policy_updated_at": policy.updated_at.isoformat() if policy and policy.updated_at else None,
        }

        digest_payload = {
            "workflow_id": workflow_id,
            "workflow_revision": workflow_revision,
            "definition_sha256": definition_sha256 or compute_definition_sha256(definition.model_dump()),
            "runtime_inputs": runtime_inputs,
            "compile_context": compile_context,
            "planned_operations": planned_ops,
        }
        digest = compute_definition_sha256(digest_payload)

        return CompilationResult(
            matched_count=matched_count,
            matched_bytes=matched_bytes,
            planned_operations=planned_ops,
            compile_digest=digest,
            runtime_inputs=runtime_inputs,
            compile_context=compile_context,
        )
