from __future__ import annotations

import re
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.filters.validation import INT64_MAX, validate_filter_ast, FilterValidationError
from app.models import IndexRoot
from app.planning.dedupe_config import canonical_config_dict, validate_and_canonicalize_config
from app.workflows.errors import WorkflowValidationError
from app.workflows.schema import (
    DedupeStep,
    FilterStep,
    MoveStep,
    OrganizeStep,
    QuarantineStep,
    RenameStep,
    RuntimeInputs,
    ScanStep,
    TouchStep,
    WorkflowDefinition,
    WorkflowStep,
)

RESERVED_UNSUPPORTED_STEPS = frozenset({"copy", "delete", "remove", "unlink"})
ALLOWED_STEP_TYPES = frozenset({"scan", "filter", "rename", "move", "touch", "quarantine", "organize", "dedupe"})


def validate_raw_steps_types(raw_steps: list[Any], mode: str | None = None) -> None:
    """Pre-validation on raw dictionary or step objects before or during Pydantic parsing to enforce UNSUPPORTED_STEP code."""
    reserved = frozenset({"copy", "delete", "remove", "unlink"})
    if mode != "dedupe":
        reserved = reserved | {"dedupe"}
    for idx, raw in enumerate(raw_steps):
        if hasattr(raw, "type"):
            step_type = str(getattr(raw, "type", "")).strip().lower()
        elif isinstance(raw, dict):
            step_type = str(raw.get("type", "")).strip().lower()
        else:
            raise WorkflowValidationError(f"Step at index {idx} must be an object", code="INVALID_STEP_PAYLOAD")

        if not step_type:
            raise WorkflowValidationError(f"Step at index {idx} missing 'type'", code="INVALID_STEP_PAYLOAD")
        if step_type in reserved:
            raise WorkflowValidationError(
                f"Workflow does not support step type '{step_type}'",
                code="UNSUPPORTED_STEP",
                details={"index": idx, "type": step_type},
            )
        if step_type not in ALLOWED_STEP_TYPES:
            raise WorkflowValidationError(
                f"Unknown step type '{step_type}'",
                code="UNSUPPORTED_STEP",
                details={"index": idx, "type": step_type},
            )


def validate_workflow_definition(
    definition: WorkflowDefinition,
    session: Session | None = None,
) -> None:
    """Validate workflow definition grammar, pipeline structure, and individual step arguments."""
    if not definition.steps:
        raise WorkflowValidationError("Workflow must contain at least one step", code="EMPTY_STEPS")

    seen_ids: set[str] = set()
    for idx, step in enumerate(definition.steps):
        step_id = step.id.strip() if step.id else ""
        if not step_id:
            raise WorkflowValidationError(f"Step at index {idx} must have a non-empty 'id'", code="INVALID_STEP_ID")
        if step_id in seen_ids:
            raise WorkflowValidationError(f"Duplicate step id '{step_id}' at index {idx}", code="DUPLICATE_STEP_ID")
        seen_ids.add(step_id)

    # Pipeline grammar validation by mode
    if definition.mode == "dedupe":
        if len(definition.steps) != 1:
            raise WorkflowValidationError(
                "Dedupe workflow must contain exactly 1 step: 'dedupe'",
                code="INVALID_PIPELINE_STRUCTURE",
                details={"step_count": len(definition.steps)},
            )
        if not isinstance(definition.steps[0], DedupeStep):
            raise WorkflowValidationError(
                "Step 0 in dedupe workflow must be 'dedupe'",
                code="INVALID_PIPELINE_STRUCTURE",
            )
    elif definition.mode == "organizer":
        for idx, step in enumerate(definition.steps):
            if isinstance(step, DedupeStep):
                raise WorkflowValidationError(
                    "Step 'dedupe' is only allowed in 'dedupe' mode workflows",
                    code="INVALID_PIPELINE_STRUCTURE",
                    details={"index": idx},
                )
        if len(definition.steps) != 2:
            raise WorkflowValidationError(
                "Organizer workflow must contain exactly 2 steps: 'scan' and 'organize'",
                code="INVALID_PIPELINE_STRUCTURE",
                details={"step_count": len(definition.steps)},
            )
        if not isinstance(definition.steps[0], ScanStep):
            raise WorkflowValidationError(
                "Step 0 in organizer workflow must be 'scan'",
                code="INVALID_PIPELINE_STRUCTURE",
            )
        if not isinstance(definition.steps[1], OrganizeStep):
            raise WorkflowValidationError(
                "Step 1 in organizer workflow must be 'organize'",
                code="INVALID_PIPELINE_STRUCTURE",
            )
    elif definition.mode == "file":
        for idx, step in enumerate(definition.steps):
            if isinstance(step, DedupeStep):
                raise WorkflowValidationError(
                    "Step 'dedupe' is only allowed in 'dedupe' mode workflows",
                    code="INVALID_PIPELINE_STRUCTURE",
                    details={"index": idx},
                )
        if not isinstance(definition.steps[0], ScanStep):
            raise WorkflowValidationError(
                "First step in 'file' workflow must be 'scan'",
                code="INVALID_PIPELINE_STRUCTURE",
            )
        saw_action = False
        quarantine_index = -1
        for idx, step in enumerate(definition.steps):
            if isinstance(step, OrganizeStep):
                raise WorkflowValidationError(
                    "Step 'organize' is only allowed in 'organizer' mode workflows",
                    code="INVALID_PIPELINE_STRUCTURE",
                    details={"index": idx},
                )
            if isinstance(step, ScanStep):
                if idx != 0:
                    raise WorkflowValidationError(
                        "Step 'scan' can only appear at index 0",
                        code="INVALID_PIPELINE_STRUCTURE",
                        details={"index": idx},
                    )
            elif isinstance(step, FilterStep):
                if saw_action:
                    raise WorkflowValidationError(
                        f"Filter step '{step.id}' cannot appear after action steps",
                        code="INVALID_PIPELINE_STRUCTURE",
                        details={"index": idx},
                    )
            elif isinstance(step, (RenameStep, MoveStep, TouchStep, QuarantineStep)):
                saw_action = True
                if isinstance(step, QuarantineStep):
                    quarantine_index = idx

        if quarantine_index != -1 and quarantine_index != len(definition.steps) - 1:
            raise WorkflowValidationError(
                "Step 'quarantine' must be the terminal (final) step in the workflow",
                code="INVALID_PIPELINE_STRUCTURE",
                details={"quarantine_index": quarantine_index, "total_steps": len(definition.steps)},
            )
    else:
        raise WorkflowValidationError(f"Unsupported workflow mode '{definition.mode}'", code="UNSUPPORTED_MODE")

    # Step-specific parameter validations
    for idx, step in enumerate(definition.steps):
        _validate_single_step(step, idx, session)


def _validate_single_step(step: WorkflowStep, idx: int, session: Session | None = None) -> None:
    if isinstance(step, ScanStep):
        if step.subpath:
            sub = step.subpath.strip()
            if ".." in sub or sub.startswith("/") or sub.startswith("\\"):
                raise WorkflowValidationError(
                    f"Scan subpath '{step.subpath}' must be a safe relative path",
                    code="INVALID_SUBPATH",
                    details={"index": idx, "step_id": step.id},
                )
        if step.root_ids and session is not None:
            roots = session.scalars(select(IndexRoot.id).where(IndexRoot.id.in_(step.root_ids))).all()
            missing = set(step.root_ids) - set(roots)
            if missing:
                raise WorkflowValidationError(
                    f"Index root ID(s) not found: {sorted(missing)}",
                    code="INDEX_ROOT_NOT_FOUND",
                    details={"missing_root_ids": sorted(missing)},
                )

    elif isinstance(step, FilterStep):
        try:
            validate_filter_ast(step.filter)
        except FilterValidationError as exc:
            raise WorkflowValidationError(
                f"Filter validation failed for step '{step.id}': {exc}",
                code="INVALID_FILTER_EXPRESSION",
                details={"index": idx, "step_id": step.id, "reason": str(exc)},
            ) from exc

    elif isinstance(step, RenameStep):
        if not step.pattern:
            raise WorkflowValidationError(
                f"Rename step '{step.id}' pattern cannot be empty",
                code="INVALID_RENAME_PATTERN",
                details={"index": idx, "step_id": step.id},
            )
        if "/" in step.pattern or "\\" in step.pattern:
            raise WorkflowValidationError(
                f"Rename step '{step.id}' pattern cannot contain path separators ('/' or '\\')",
                code="INVALID_RENAME_PATTERN",
                details={"index": idx, "step_id": step.id},
            )
        if "/" in step.replacement or "\\" in step.replacement:
            raise WorkflowValidationError(
                f"Rename step '{step.id}' replacement cannot contain path separators ('/' or '\\')",
                code="INVALID_RENAME_REPLACEMENT",
                details={"index": idx, "step_id": step.id},
            )

    elif isinstance(step, MoveStep):
        if step.destination_root_id <= 0:
            raise WorkflowValidationError(
                f"Move step '{step.id}' destination_root_id must be a positive integer",
                code="INVALID_DESTINATION_ROOT",
                details={"index": idx, "step_id": step.id},
            )
        if session is not None:
            dest_root = session.scalar(select(IndexRoot.id).where(IndexRoot.id == step.destination_root_id))
            if not dest_root:
                raise WorkflowValidationError(
                    f"Destination index root ID {step.destination_root_id} not found",
                    code="INDEX_ROOT_NOT_FOUND",
                    details={"index": idx, "destination_root_id": step.destination_root_id},
                )
        if step.destination_subpath:
            sub = step.destination_subpath.strip()
            if ".." in sub or sub.startswith("/") or sub.startswith("\\"):
                raise WorkflowValidationError(
                    f"Move destination_subpath '{step.destination_subpath}' must be a safe relative path",
                    code="INVALID_SUBPATH",
                    details={"index": idx, "step_id": step.id},
                )

    elif isinstance(step, TouchStep):
        if step.mtime_ns is not None:
            if step.mtime_ns < 0 or step.mtime_ns > INT64_MAX:
                raise WorkflowValidationError(
                    f"Touch step '{step.id}' mtime_ns out of range (0 to {INT64_MAX})",
                    code="INVALID_MTIME_NS",
                    details={"index": idx, "step_id": step.id, "mtime_ns": step.mtime_ns},
                )

    elif isinstance(step, QuarantineStep):
        if not step.reason or not step.reason.strip():
            raise WorkflowValidationError(
                f"Quarantine step '{step.id}' reason cannot be empty",
                code="INVALID_QUARANTINE_REASON",
                details={"index": idx, "step_id": step.id},
            )

    elif isinstance(step, OrganizeStep):
        snapshot = step.profile_snapshot
        if hasattr(snapshot, "name"):
            name = str(snapshot.name or "").strip()
        elif isinstance(snapshot, dict):
            name = str(snapshot.get("name") or "").strip()
        else:
            raise WorkflowValidationError(
                f"Organize step '{step.id}' profile_snapshot must be an OrganizerProfileSnapshot object",
                code="INVALID_PROFILE_SNAPSHOT",
                details={"index": idx, "step_id": step.id},
            )
        if not name:
            raise WorkflowValidationError(
                f"Organize step '{step.id}' profile_snapshot must contain a valid 'name'",
                code="INVALID_PROFILE_SNAPSHOT",
                details={"index": idx, "step_id": step.id},
            )

    elif isinstance(step, DedupeStep):
        validate_and_canonicalize_workflow_scorer_config(step.scorer_config, step_idx=idx, step_id=step.id)


def validate_and_canonicalize_workflow_scorer_config(
    raw_config: Any,
    *,
    step_idx: int | None = None,
    step_id: str | None = None,
) -> dict[str, Any]:
    """Validate and canonicalize scorer_config for dedupe workflow, mapping errors to 422 WorkflowValidationError."""
    try:
        cfg = validate_and_canonicalize_config(raw_config)
        return canonical_config_dict(cfg)
    except ValueError as exc:
        msg = str(exc)
        code = "DEDUPE_FACTOR_UNAVAILABLE" if "DEDUPE_FACTOR_UNAVAILABLE" in msg else "DEDUPE_INVALID_CONFIG"
        details: dict[str, Any] = {"reason": msg}
        if step_idx is not None:
            details["index"] = step_idx
        if step_id is not None:
            details["step_id"] = step_id
        raise WorkflowValidationError(
            msg,
            code=code,
            details=details,
            status_code=422,
        ) from exc


def resolve_mode_runtime_inputs(
    mode: str,
    root_ids: list[int] | None,
    runtime_inputs: RuntimeInputs | None,
) -> tuple[int | None, list[int] | None]:
    """Resolve and validate runtime inputs based on workflow mode.

    Returns:
        tuple of (scan_job_id, effective_root_ids)
    """
    if mode == "dedupe":
        if root_ids is not None or (runtime_inputs is not None and runtime_inputs.root_ids is not None):
            raise WorkflowValidationError(
                "root_ids is forbidden in dedupe workflow mode",
                code="ROOT_IDS_FORBIDDEN",
                status_code=422,
            )
        if runtime_inputs is None or runtime_inputs.scan_job_id is None:
            raise WorkflowValidationError(
                "runtime_inputs.scan_job_id is required for dedupe workflow",
                code="SCAN_JOB_ID_REQUIRED",
                status_code=422,
            )
        return runtime_inputs.scan_job_id, None
    elif mode in {"file", "organizer"}:
        if runtime_inputs is not None and runtime_inputs.scan_job_id is not None:
            raise WorkflowValidationError(
                "scan_job_id is forbidden in file/organizer workflow mode",
                code="SCAN_JOB_ID_FORBIDDEN",
                status_code=422,
            )
        if root_ids is not None and runtime_inputs is not None:
            raise WorkflowValidationError(
                "Ambiguous root inputs: cannot provide both top-level 'root_ids' and 'runtime_inputs'",
                code="AMBIGUOUS_RUNTIME_INPUTS",
                status_code=422,
            )
        effective_roots = (
            runtime_inputs.root_ids
            if runtime_inputs and runtime_inputs.root_ids is not None
            else root_ids
        )
        return None, effective_roots
    else:
        raise WorkflowValidationError(f"Unsupported workflow mode '{mode}'", code="UNSUPPORTED_MODE")


