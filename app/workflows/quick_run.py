"""Queue and recover a confirmed file workflow through the existing Plan lifecycle."""
from __future__ import annotations

import json
import os
from pathlib import Path
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, User, Workflow, WorkflowRevision, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.logging import log_task_event
from app.tasks.state_machine import JobLeaseLost
from app.workflows.errors import RecipeRevisionNotFoundError, WorkflowArchivedError, WorkflowError, WorkflowNotFoundError
from app.workflows.schema import WorkflowGeneratePlanRequest

QUICK_RUN_KIND = "workflow-quick-run"
_FILE_OPERATIONS = frozenset({"move", "rename", "touch", "quarantine"})
_PHASES = {
    "generate_plan": (0, "正在重新核对预览并生成执行计划"),
    "freeze": (1, "正在冻结文件状态"),
    "validate": (2, "正在校验实际文件和目标路径"),
    "enqueue": (3, "正在提交执行任务"),
    "queued": (4, "执行任务已入队"),
}


class QuickWorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(strict=True, ge=1)
    directory: str = Field(min_length=1, max_length=4096)
    expected_compile_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")

    @field_validator("directory")
    @classmethod
    def validate_directory(cls, value: str) -> str:
        if not Path(value).is_absolute() or "\x00" in value or os.path.normpath(value) != value:
            raise ValueError("请选择有效的目录路径")
        return value


class QuickWorkflowRunError(WorkflowError):
    """Expose the same error code to HTTP callers and the Worker task record."""

    @property
    def error_code(self) -> str:
        return self.code


def _json_object(value: str | None) -> dict:
    data = json.loads(value or "{}")
    if not isinstance(data, dict):
        raise QuickWorkflowRunError("工作流运行记录无效", code="WORKFLOW_QUICK_RUN_STATE", status_code=409)
    return data


def _authorize_actor(session: Session, actor_id: int, settings: Settings) -> None:
    if not settings.allow_mutation:
        raise QuickWorkflowRunError("当前为只读模式，无法执行工作流", code="MUTATION_DISABLED", status_code=403)
    actor = session.get(User, actor_id)
    if actor is None or not actor.is_active or actor.role not in {"admin", "member"}:
        raise QuickWorkflowRunError("当前账号没有运行工作流的权限", code="WORKFLOW_RUN_FORBIDDEN", status_code=403)


def _revision(session: Session, workflow_id: int, revision_number: int) -> WorkflowRevision:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise WorkflowNotFoundError()
    if workflow.archived_at is not None:
        raise WorkflowArchivedError("该工作流已归档，无法运行")
    revision = session.scalar(select(WorkflowRevision).where(
        WorkflowRevision.workflow_id == workflow_id,
        WorkflowRevision.revision == revision_number,
    ))
    if revision is None:
        raise RecipeRevisionNotFoundError()
    if _json_object(revision.definition_json).get("mode") != "file":
        raise QuickWorkflowRunError("快捷运行适用于文件工作流", code="WORKFLOW_RUN_MODE", status_code=422)
    return revision


def _checkpoint(phase: str, **data: str) -> dict:
    return {"schema_version": 1, "phase": phase, **data}


def enqueue_workflow_quick_run(
    sessions: sessionmaker,
    settings: Settings,
    *,
    actor_id: int,
    workflow_id: int,
    payload: QuickWorkflowRunRequest,
) -> dict[str, str]:
    """Bind each confirmation key to one actor and one exact request under a writer lock."""
    request = payload.model_dump()
    request.update(workflow_id=str(workflow_id), requested_by_user_id=str(actor_id))
    with sessions() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        _authorize_actor(session, actor_id, settings)
        state = case((func.json_valid(WorkJob.state_json) == 1, WorkJob.state_json), else_="{}")
        existing = session.scalar(select(WorkJob).where(
            WorkJob.kind == QUICK_RUN_KIND,
            func.json_extract(state, "$.requested_by_user_id") == str(actor_id),
            func.json_extract(state, "$.request_id") == payload.request_id,
        ).limit(1))
        if existing is not None:
            stored = _json_object(existing.state_json)
            if any(stored.get(key) != value for key, value in request.items()):
                raise QuickWorkflowRunError("本次确认已绑定另一份预览", code="WORKFLOW_RUN_REQUEST_CONFLICT", status_code=409)
            return {"job_id": str(existing.id)}

        # A deleted task must not make a still-recorded approval usable again.
        metadata = case((func.json_valid(BatchPlan.metadata_json) == 1, BatchPlan.metadata_json), else_="{}")
        used = session.scalar(select(BatchPlan.id).where(
            func.json_extract(metadata, "$.workflow_quick_run.requested_by_user_id") == str(actor_id),
            func.json_extract(metadata, "$.workflow_quick_run.request_id") == payload.request_id,
        ).limit(1))
        if used is not None:
            raise QuickWorkflowRunError("此确认已使用，任务记录已清理", code="WORKFLOW_RUN_REQUEST_USED", status_code=409)

        revision = _revision(session, workflow_id, payload.revision)
        job = WorkJob(
            kind=QUICK_RUN_KIND,
            status="queued",
            state_json=json.dumps({**request, "definition_sha256": revision.definition_sha256}, ensure_ascii=False),
            checkpoint_json=json.dumps(_checkpoint("generate_plan")),
            progress_total=4,
            progress_message="等待 Worker 准备执行",
        )
        session.add(job)
        session.flush()
        log_task_event(session, job_id=job.id, event_type="queued", message="工作流快捷运行已确认")
        job_id = str(job.id)
        session.commit()
        return {"job_id": job_id}


@register_handler
class WorkflowQuickRunHandler(TaskHandler):
    job_type = QUICK_RUN_KIND
    supports_pause = False
    supports_cancel = False
    supports_retry = False
    supports_resume = True

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        try:
            self._prepare(job, context, settings)
        except WorkflowError as exc:
            if isinstance(exc, QuickWorkflowRunError):
                raise
            raise QuickWorkflowRunError(exc.message, code=exc.code, details=exc.details, status_code=exc.status_code) from exc

    def _prepare(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        from app.service import FileCenterService
        from app.tasks.recovery import assert_active_worker_lease

        if context.worker_id is None:
            raise JobLeaseLost("工作流执行需要当前 Worker 租约")
        stored = _json_object(job.state_json)
        saved = _json_object(job.checkpoint_json)
        if saved.get("execution_job_id"):
            # The child job and this receipt were committed in one transaction.
            return
        payload = QuickWorkflowRunRequest.model_validate({key: stored.get(key) for key in QuickWorkflowRunRequest.model_fields})
        workflow_id = int(stored["workflow_id"])
        actor_id = int(stored["requested_by_user_id"])
        service = FileCenterService(settings, worker_database=(context.engine, context.SessionLocal))
        plan_id = int(saved["plan_id"]) if "plan_id" in saved else None

        def authorize(session: Session, *, check_lease: bool = False) -> None:
            if check_lease:
                assert_active_worker_lease(session, context.worker_id, now=utcnow())
            _authorize_actor(session, actor_id, settings)
            revision = _revision(session, workflow_id, payload.revision)
            if revision.definition_sha256 != stored["definition_sha256"]:
                raise QuickWorkflowRunError("工作流版本已变化，请重新生成预览", code="PREVIEW_CHANGED", status_code=409)

        def check_plan(session: Session, plan: BatchPlan) -> None:
            metadata = _json_object(plan.metadata_json)
            if (metadata.get("workflow_quick_run") != binding or
                    metadata.get("compile_digest") != payload.expected_compile_digest or
                    metadata.get("workflow_mode") != "file"):
                raise QuickWorkflowRunError("执行计划与确认的预览不一致", code="WORKFLOW_RUN_PLAN_CONFLICT", status_code=409)

            restricted = session.scalar(select(BatchPlanItem.id).where(
                BatchPlanItem.plan_id == plan.id,
                BatchPlanItem.operation.not_in(_FILE_OPERATIONS),
            ).limit(1))
            if restricted is not None:
                raise QuickWorkflowRunError("执行计划包含未授权的操作", code="WORKFLOW_RUN_FORBIDDEN_OPERATION", status_code=403)

        def get_parent(session: Session, phase: str, current_plan_id: int | None) -> WorkJob:
            authorize(session, check_lease=True)
            parent = session.get(WorkJob, context.job_id)
            if parent is None or parent.status != "running" or parent.state_json != job.state_json:
                raise JobLeaseLost("工作流运行任务已失去当前执行权")
            current = _json_object(parent.checkpoint_json)
            expected_plan_id = None if current_plan_id is None else str(current_plan_id)
            if current.get("phase") != phase or current.get("plan_id") != expected_plan_id:
                raise JobLeaseLost("工作流运行阶段已由另一 Worker 推进")
            return parent

        def snapshot(phase: str) -> None:
            progress, message = _PHASES[phase]
            context.checkpoint(progress_current=progress, progress_total=4, progress_message=message,
                               checkpoint_data=_checkpoint(phase, **({"plan_id": str(plan_id)} if plan_id else {})))

        def verify_writer(phase: str, status: str):
            def verify(session: Session, plan: BatchPlan) -> None:
                get_parent(session, phase, plan_id)
                check_plan(session, plan)
                if plan.status != status:
                    raise QuickWorkflowRunError("执行计划状态已变化，请重新核对", code="WORKFLOW_RUN_PLAN_CONFLICT", status_code=409)
            return verify

        last_heartbeat = 0.0

        def heartbeat(*_progress: int) -> None:
            nonlocal last_heartbeat
            now = monotonic()
            if now - last_heartbeat >= 2:
                context.checkpoint()
                last_heartbeat = now

        binding = {
            "job_id": str(job.id),
            "requested_by_user_id": str(actor_id),
            "request_id": payload.request_id,
        }

        def bind_draft(session: Session, plan: BatchPlan) -> None:
            parent = get_parent(session, "generate_plan", None)
            metadata = _json_object(plan.metadata_json)
            metadata["workflow_quick_run"] = binding
            plan.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
            check_plan(session, plan)
            # A loss of acknowledgement can only leave both records committed, or neither.
            parent.checkpoint_json = json.dumps(_checkpoint("freeze", plan_id=str(plan.id)))

        def enqueue_receipt(session: Session, plan: BatchPlan, child: WorkJob) -> None:
            parent = get_parent(session, "enqueue", plan_id)
            check_plan(session, plan)
            if plan.status != "ready":
                raise QuickWorkflowRunError("校验未通过，执行任务未提交", code="WORKFLOW_RUN_VALIDATION_FAILED", status_code=409)
            child_state = _json_object(child.state_json)
            child_state["workflow_quick_run_job_id"] = str(parent.id)
            child.state_json = json.dumps(child_state, ensure_ascii=False)
            parent.checkpoint_json = json.dumps(_checkpoint("queued", plan_id=str(plan.id), execution_job_id=str(child.id)))
            parent.progress_current, parent.progress_message = _PHASES["queued"]
            parent.heartbeat_at = utcnow()
            log_task_event(session, job_id=parent.id, event_type="execution_queued", message="工作流执行任务已加入队列")

        with context.SessionLocal() as session:
            authorize(session, check_lease=True)

        if plan_id is None:
            snapshot("generate_plan")
            generated = service.workflow_service.generate_plan(
                actor_id, workflow_id,
                WorkflowGeneratePlanRequest(
                    revision=payload.revision,
                    runtime_inputs={"directory": payload.directory},
                    expected_compile_digest=payload.expected_compile_digest,
                ),
                before_commit=bind_draft,
            )
            plan_id = generated["plan_id"]

        with context.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None:
                raise QuickWorkflowRunError("已生成的执行计划不存在", code="WORKFLOW_RUN_PLAN_CONFLICT", status_code=409)
            check_plan(session, plan)
            plan_status = plan.status

        if plan_status == "draft":
            snapshot("freeze")
            plan_status = service.freeze_plan(
                plan_id, progress_callback=heartbeat, verify_writer=verify_writer("freeze", "draft"),
            ).status
        if plan_status == "frozen":
            snapshot("validate")
            plan_status = service.validate_plan(
                plan_id, progress_callback=heartbeat, verify_writer=verify_writer("validate", "frozen"),
            )["status"]
        if plan_status != "ready":
            with context.SessionLocal() as session:
                conflict = session.scalar(select(BatchPlanItem).where(
                    BatchPlanItem.plan_id == plan_id, BatchPlanItem.state.in_(("stale", "skipped")),
                ).order_by(BatchPlanItem.sequence).limit(1))
            detail = (f"\n{conflict.source_path} · {conflict.reason or '文件状态已变化'}") if conflict else ""
            raise QuickWorkflowRunError("校验未通过，执行任务未提交" + detail,
                                        code="WORKFLOW_RUN_VALIDATION_FAILED", status_code=409)
        snapshot("enqueue")
        service.enqueue_plan_execution(
            plan_id, user_id=actor_id, verify_writer=verify_writer("enqueue", "ready"), before_commit=enqueue_receipt,
        )
