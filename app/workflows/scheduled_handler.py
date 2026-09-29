from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.models import BatchPlan, WorkJob, Workflow, WorkflowRevision
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler
from app.workflows.schema import (
    RuntimeInputs,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
)
from app.workflows.service import WorkflowService


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _strict_positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _load_scheduled_state(job: WorkJob) -> dict[str, Any]:
    try:
        state = json.loads(job.state_json or "{}")
    except Exception as exc:
        raise ValueError("Scheduled workflow job state is invalid JSON") from exc
    if not isinstance(state, dict):
        raise ValueError("Scheduled workflow job state must be an object")

    workflow_id = _strict_positive_int(state.get("workflow_id"), field="workflow_id")
    workflow_revision = _strict_positive_int(
        state.get("workflow_revision"),
        field="workflow_revision",
    )

    definition_sha256 = state.get("definition_sha256")
    if not isinstance(definition_sha256, str):
        raise ValueError("definition_sha256 must be a string")
    definition_sha256 = definition_sha256.lower()
    if not _SHA256_RE.fullmatch(definition_sha256):
        raise ValueError("definition_sha256 must be a 64-character SHA256 hex string")

    action = state.get("action")
    if action not in {"preview", "draft"}:
        raise ValueError("action must be 'preview' or 'draft'")

    raw_runtime = state.get("runtime_inputs")
    try:
        runtime_inputs = (
            RuntimeInputs.model_validate(raw_runtime)
            if raw_runtime is not None
            else None
        )
    except ValidationError as exc:
        raise ValueError(f"Invalid scheduled workflow runtime_inputs: {exc}") from exc

    requested_by_user_id = state.get("requested_by_user_id")
    if requested_by_user_id is not None:
        requested_by_user_id = _strict_positive_int(
            requested_by_user_id,
            field="requested_by_user_id",
        )

    return {
        "workflow_id": workflow_id,
        "workflow_revision": workflow_revision,
        "definition_sha256": definition_sha256,
        "action": action,
        "runtime_inputs": runtime_inputs,
        "requested_by_user_id": requested_by_user_id,
    }


def _assert_pinned_revision(
    context: JobContext,
    *,
    workflow_id: int,
    workflow_revision: int,
    definition_sha256: str,
) -> tuple[Workflow, WorkflowRevision]:
    with context.SessionLocal() as session:
        workflow = session.get(Workflow, workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow #{workflow_id} not found")
        if workflow.archived_at is not None:
            raise ValueError(f"Workflow #{workflow_id} is archived")

        revision = session.scalar(
            select(WorkflowRevision).where(
                WorkflowRevision.workflow_id == workflow_id,
                WorkflowRevision.revision == workflow_revision,
            )
        )
        if revision is None:
            raise ValueError(
                f"Workflow #{workflow_id} revision {workflow_revision} not found"
            )
        if revision.definition_sha256.lower() != definition_sha256:
            raise ValueError(
                "Pinned workflow definition SHA no longer matches stored revision"
            )
        return workflow, revision


def _preview_result_summary(preview: dict[str, Any]) -> dict[str, Any]:
    organizer_summary = preview.get("organizer_summary")
    dedupe_summary = preview.get("dedupe_summary")
    utility_summary = preview.get("utility_summary")

    return {
        "workflow_id": preview.get("workflow_id"),
        "workflow_revision": preview.get("workflow_revision"),
        "definition_sha256": preview.get("definition_sha256"),
        "workflow_mode": preview.get("workflow_mode"),
        "preview_source": preview.get("preview_source"),
        "compile_digest": preview.get("compile_digest"),
        "matched_count": preview.get("matched_count"),
        "matched_bytes": preview.get("matched_bytes"),
        "planned_operations_count": preview.get("planned_operations_count"),
        "organizer_preview_digest": (
            organizer_summary.get("preview_digest")
            if isinstance(organizer_summary, dict)
            else None
        ),
        "dedupe_preview_digest": (
            dedupe_summary.get("preview_digest")
            if isinstance(dedupe_summary, dict)
            else None
        ),
        "utility_candidate_count": (
            utility_summary.get("candidate_count")
            if isinstance(utility_summary, dict)
            else None
        ),
        "utility_ready_count": (
            utility_summary.get("ready_count")
            if isinstance(utility_summary, dict)
            else None
        ),
    }


@register_handler
class ScheduledWorkflowHandler(TaskHandler):
    job_type = "workflow-scheduled"
    supports_pause = False
    supports_cancel = False
    supports_retry = False
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = _load_scheduled_state(job)
        workflow_id = state["workflow_id"]
        workflow_revision = state["workflow_revision"]
        definition_sha256 = state["definition_sha256"]
        action = state["action"]
        runtime_inputs = state["runtime_inputs"]

        workflow, _revision = _assert_pinned_revision(
            context,
            workflow_id=workflow_id,
            workflow_revision=workflow_revision,
            definition_sha256=definition_sha256,
        )

        context.checkpoint(
            progress_current=0,
            progress_total=2 if action == "draft" else 1,
            progress_message=(
                f"Previewing pinned workflow #{workflow_id} r{workflow_revision}..."
            ),
            checkpoint_data={
                "schema_version": 1,
                "phase": "preview",
                "workflow_id": workflow_id,
                "workflow_revision": workflow_revision,
                "definition_sha256": definition_sha256,
                "action": action,
            },
        )

        service = WorkflowService(context.SessionLocal, settings)
        preview = service.preview_workflow(
            workflow_id,
            WorkflowPreviewRequest(
                revision=workflow_revision,
                runtime_inputs=runtime_inputs,
                page=1,
                page_size=1,
                only_changed=False,
            ),
        )

        actual_sha = str(preview.get("definition_sha256") or "").lower()
        if actual_sha != definition_sha256:
            raise ValueError(
                "Pinned workflow definition SHA changed during Preview"
            )

        preview_summary = _preview_result_summary(preview)

        if action == "preview":
            context.checkpoint(
                progress_current=1,
                progress_total=1,
                progress_message="Pinned workflow Preview completed",
                checkpoint_data={
                    "schema_version": 1,
                    "phase": "completed",
                    "action": "preview",
                    "preview": preview_summary,
                    "plan_id": None,
                },
            )
            return

        workflow_mode = preview.get("workflow_mode")
        if workflow_mode == "utility":
            raise ValueError(
                "Utility workflow schedules are Preview-only in Scheduler S3"
            )

        organizer_preview_digest = None
        organizer_summary = preview.get("organizer_summary")
        if isinstance(organizer_summary, dict):
            raw_digest = organizer_summary.get("preview_digest")
            if isinstance(raw_digest, str) and raw_digest:
                organizer_preview_digest = raw_digest

        context.checkpoint(
            progress_current=1,
            progress_total=2,
            progress_message="Preview bound; generating Draft Plan...",
            checkpoint_data={
                "schema_version": 1,
                "phase": "generate_draft",
                "action": "draft",
                "preview": preview_summary,
            },
        )

        generated = service.generate_plan(
            state["requested_by_user_id"],
            workflow_id,
            WorkflowGeneratePlanRequest(
                expected_compile_digest=str(preview["compile_digest"]),
                expected_preview_digest=organizer_preview_digest,
                revision=workflow_revision,
                runtime_inputs=runtime_inputs,
                plan_name=(
                    f"Scheduled - {workflow.name} (r{workflow_revision})"
                ),
            ),
        )

        if generated.get("status") != "draft":
            raise RuntimeError(
                f"Scheduled Workflow Generate returned non-draft status: {generated.get('status')!r}"
            )

        plan_id = _strict_positive_int(generated.get("plan_id"), field="plan_id")
        with context.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None:
                raise RuntimeError(f"Generated Draft Plan #{plan_id} is missing")
            if plan.status != "draft":
                raise RuntimeError(
                    f"Generated Plan #{plan_id} escaped Draft state: {plan.status!r}"
                )

        context.checkpoint(
            progress_current=2,
            progress_total=2,
            progress_message=f"Draft Plan #{plan_id} created; execution not started",
            checkpoint_data={
                "schema_version": 1,
                "phase": "completed",
                "action": "draft",
                "preview": preview_summary,
                "plan_id": plan_id,
                "plan_name": generated.get("plan_name"),
                "plan_status": "draft",
                "expected_changes": generated.get("expected_changes"),
                "compile_digest": generated.get("compile_digest"),
                "auto_freeze": False,
                "auto_validate": False,
                "auto_execute": False,
            },
        )
