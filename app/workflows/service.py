from __future__ import annotations

import json
from math import ceil
from typing import Any
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, ScanJob, Workflow, WorkflowRevision, utcnow
from app.planning.dedupe_config import canonical_config_dict, validate_and_canonicalize_config
from app.planning.dedupe_preview import compute_current_dedupe_db_lineage_digest
from app.workflows.compiler import (
    MAX_WORKFLOW_CANDIDATES,
    MAX_WORKFLOW_PLAN_ITEMS,
    WorkflowCompiler,
)
from app.workflows.errors import (
    BuiltinWorkflowImmutableError,
    RecipeRevisionNotFoundError,
    WorkflowArchivedError,
    WorkflowDigestMismatchError,
    WorkflowNotFoundError,
    WorkflowRevisionConflictError,
    WorkflowValidationError,
)
from app.workflows.revisions import canonical_json_dumps, compute_definition_sha256
from app.workflows.schema import (
    DedupeStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
    WorkflowRollbackRequest,
    WorkflowUpdateRequest,
)
from app.workflows.validation import validate_raw_steps_types, validate_workflow_definition


class WorkflowService:
    def __init__(self, session_factory: sessionmaker, settings: Settings):
        self.SessionLocal = session_factory
        self.settings = settings

    def compile_workflow_definition(
        self,
        session: Session,
        definition: WorkflowDefinition,
        workflow_id: int,
        workflow_revision: int,
        definition_sha256: str,
        override_root_ids: list[int] | None = None,
        scan_job_id: int | None = None,
    ):
        protect_last_file = bool(getattr(self.settings, "protect_last_file", True))
        compiler = WorkflowCompiler(
            session=session,
            allowed_roots=self.settings.allowed_roots,
            quarantine_root=self.settings.quarantine_root,
            protect_last_file=protect_last_file,
        )
        return compiler.compile(
            definition,
            workflow_id=workflow_id,
            workflow_revision=workflow_revision,
            definition_sha256=definition_sha256,
            override_root_ids=override_root_ids,
            scan_job_id=scan_job_id,
            max_candidates=MAX_WORKFLOW_CANDIDATES,
            max_plan_items=MAX_WORKFLOW_PLAN_ITEMS,
        )

    def list_workflows(self, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.SessionLocal() as session:
            stmt = (
                select(Workflow, WorkflowRevision.definition_json)
                .join(
                    WorkflowRevision,
                    (WorkflowRevision.workflow_id == Workflow.id)
                    & (WorkflowRevision.revision == Workflow.current_revision),
                )
            )
            if not include_archived:
                stmt = stmt.where(Workflow.archived_at.is_(None))
            stmt = stmt.order_by(Workflow.is_builtin.desc(), Workflow.updated_at.desc(), Workflow.id.desc())
            rows = session.execute(stmt).all()
            res = []
            for wf, def_json in rows:
                mode = "file"
                if def_json:
                    try:
                        mode = json.loads(def_json).get("mode", "file")
                    except Exception:
                        mode = "file"
                res.append({
                    "id": wf.id,
                    "name": wf.name,
                    "description": wf.description,
                    "mode": mode,
                    "current_revision": wf.current_revision,
                    "is_builtin": wf.is_builtin,
                    "archived_at": wf.archived_at.isoformat() if wf.archived_at else None,
                    "created_at": wf.created_at.isoformat(),
                    "updated_at": wf.updated_at.isoformat(),
                })
            return res

    def get_workflow(self, workflow_id: int) -> dict[str, Any]:
        with self.SessionLocal() as session:
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

            rev = session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf.id,
                    WorkflowRevision.revision == wf.current_revision,
                )
            )
            if not rev:
                raise WorkflowNotFoundError(f"Current revision {wf.current_revision} for workflow {workflow_id} not found")

            definition_dict = json.loads(rev.definition_json)
            return {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "current_revision": wf.current_revision,
                "is_builtin": wf.is_builtin,
                "created_by_user_id": wf.created_by_user_id,
                "archived_at": wf.archived_at.isoformat() if wf.archived_at else None,
                "created_at": wf.created_at.isoformat(),
                "updated_at": wf.updated_at.isoformat(),
                "definition": definition_dict,
                "definition_sha256": rev.definition_sha256,
            }

    def create_workflow(self, user_id: int | None, payload: WorkflowCreateRequest) -> dict[str, Any]:
        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if payload.definition.mode == "dedupe":
                step = payload.definition.steps[0]
                if isinstance(step, DedupeStep):
                    step.scorer_config = canonical_config_dict(validate_and_canonicalize_config(step.scorer_config))
            # Semantic validation
            validate_workflow_definition(payload.definition, session)

            raw_def = payload.definition.model_dump()
            canon_json = canonical_json_dumps(raw_def)
            sha256_hash = compute_definition_sha256(raw_def)

            wf = Workflow(
                name=payload.name.strip(),
                description=payload.description.strip(),
                current_revision=1,
                is_builtin=False,
                created_by_user_id=user_id,
            )
            session.add(wf)
            session.flush()

            rev = WorkflowRevision(
                workflow_id=wf.id,
                revision=1,
                definition_json=canon_json,
                definition_sha256=sha256_hash,
                created_by_user_id=user_id,
            )
            session.add(rev)
            session.commit()
            session.refresh(wf)

            return {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "current_revision": wf.current_revision,
                "is_builtin": wf.is_builtin,
                "created_by_user_id": wf.created_by_user_id,
                "archived_at": None,
                "created_at": wf.created_at.isoformat(),
                "updated_at": wf.updated_at.isoformat(),
                "definition": raw_def,
                "definition_sha256": sha256_hash,
            }

    def update_workflow(
        self,
        user_id: int | None,
        workflow_id: int,
        payload: WorkflowUpdateRequest,
    ) -> dict[str, Any]:
        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            if wf.is_builtin:
                raise BuiltinWorkflowImmutableError(f"Built-in workflow {workflow_id} cannot be modified")
            if wf.archived_at is not None:
                raise WorkflowArchivedError(f"Workflow {workflow_id} is archived")

            if payload.expected_current_revision != wf.current_revision:
                raise WorkflowRevisionConflictError(
                    f"Workflow revision conflict: expected {payload.expected_current_revision}, got {wf.current_revision}",
                    details={
                        "expected_revision": payload.expected_current_revision,
                        "current_revision": wf.current_revision,
                    },
                )

            if payload.name is not None:
                wf.name = payload.name.strip()
            if payload.description is not None:
                wf.description = payload.description.strip()

            active_definition: dict[str, Any] | None = None
            active_sha256: str | None = None

            next_rev = wf.current_revision + 1

            if payload.definition is not None:
                if payload.definition.mode == "dedupe":
                    step = payload.definition.steps[0]
                    if isinstance(step, DedupeStep):
                        step.scorer_config = canonical_config_dict(validate_and_canonicalize_config(step.scorer_config))
                validate_workflow_definition(payload.definition, session)
                raw_def = payload.definition.model_dump()
                canon_json = canonical_json_dumps(raw_def)
                sha256_hash = compute_definition_sha256(raw_def)

                rev = WorkflowRevision(
                    workflow_id=wf.id,
                    revision=next_rev,
                    definition_json=canon_json,
                    definition_sha256=sha256_hash,
                    created_by_user_id=user_id,
                )
                session.add(rev)
                wf.current_revision = next_rev
                active_definition = raw_def
                active_sha256 = sha256_hash
            else:
                current_rev = session.scalar(
                    select(WorkflowRevision).where(
                        WorkflowRevision.workflow_id == wf.id,
                        WorkflowRevision.revision == wf.current_revision,
                    )
                )
                if not current_rev:
                    raise RecipeRevisionNotFoundError(f"Current revision {wf.current_revision} not found")
                rev = WorkflowRevision(
                    workflow_id=wf.id,
                    revision=next_rev,
                    definition_json=current_rev.definition_json,
                    definition_sha256=current_rev.definition_sha256,
                    created_by_user_id=user_id,
                )
                session.add(rev)
                wf.current_revision = next_rev
                active_definition = json.loads(current_rev.definition_json)
                active_sha256 = current_rev.definition_sha256

            wf.updated_at = utcnow()
            session.commit()
            session.refresh(wf)

            return {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "current_revision": wf.current_revision,
                "is_builtin": wf.is_builtin,
                "created_by_user_id": wf.created_by_user_id,
                "archived_at": None,
                "created_at": wf.created_at.isoformat(),
                "updated_at": wf.updated_at.isoformat(),
                "definition": active_definition or {},
                "definition_sha256": active_sha256 or "",
            }

    def archive_workflow(
        self,
        user_id: int | None,
        workflow_id: int,
        expected_current_revision: int,
    ) -> None:
        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            if wf.is_builtin:
                raise BuiltinWorkflowImmutableError(f"Built-in workflow {workflow_id} cannot be archived")
            if wf.archived_at is not None:
                raise WorkflowArchivedError(f"Workflow {workflow_id} is already archived")

            if expected_current_revision != wf.current_revision:
                raise WorkflowRevisionConflictError(
                    f"Workflow revision conflict: expected {expected_current_revision}, got {wf.current_revision}",
                    details={
                        "expected_revision": expected_current_revision,
                        "current_revision": wf.current_revision,
                    },
                )

            wf.archived_at = utcnow()
            wf.updated_at = utcnow()
            session.commit()

    def rollback_workflow(
        self,
        user_id: int | None,
        workflow_id: int,
        payload: WorkflowRollbackRequest,
    ) -> dict[str, Any]:
        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            if wf.is_builtin:
                raise BuiltinWorkflowImmutableError(f"Built-in workflow {workflow_id} cannot be rolled back")
            if wf.archived_at is not None:
                raise WorkflowArchivedError(f"Workflow {workflow_id} is archived")

            if payload.expected_current_revision != wf.current_revision:
                raise WorkflowRevisionConflictError(
                    f"Workflow revision conflict: expected {payload.expected_current_revision}, got {wf.current_revision}",
                    details={
                        "expected_revision": payload.expected_current_revision,
                        "current_revision": wf.current_revision,
                    },
                )

            target_rev = session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf.id,
                    WorkflowRevision.revision == payload.target_revision,
                )
            )
            if not target_rev:
                raise RecipeRevisionNotFoundError(f"Target revision {payload.target_revision} not found")

            next_rev = wf.current_revision + 1
            new_rev = WorkflowRevision(
                workflow_id=wf.id,
                revision=next_rev,
                definition_json=target_rev.definition_json,
                definition_sha256=target_rev.definition_sha256,
                created_by_user_id=user_id,
            )
            session.add(new_rev)
            wf.current_revision = next_rev
            wf.updated_at = utcnow()
            session.commit()
            session.refresh(wf)

            return {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "current_revision": wf.current_revision,
                "is_builtin": wf.is_builtin,
                "created_by_user_id": wf.created_by_user_id,
                "archived_at": None,
                "created_at": wf.created_at.isoformat(),
                "updated_at": wf.updated_at.isoformat(),
                "definition": json.loads(target_rev.definition_json),
                "definition_sha256": target_rev.definition_sha256,
            }

    def list_workflow_revisions(self, workflow_id: int) -> list[dict[str, Any]]:
        with self.SessionLocal() as session:
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

            revisions = session.scalars(
                select(WorkflowRevision)
                .where(WorkflowRevision.workflow_id == wf.id)
                .order_by(WorkflowRevision.revision.asc())
            ).all()

            return [
                {
                    "id": r.id,
                    "workflow_id": r.workflow_id,
                    "revision": r.revision,
                    "definition": json.loads(r.definition_json),
                    "definition_sha256": r.definition_sha256,
                    "created_by_user_id": r.created_by_user_id,
                    "created_at": r.created_at.isoformat(),
                }
                for r in revisions
            ]

    def get_workflow_revision(self, workflow_id: int, revision: int) -> dict[str, Any]:
        with self.SessionLocal() as session:
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

            r = session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf.id,
                    WorkflowRevision.revision == revision,
                )
            )
            if not r:
                raise RecipeRevisionNotFoundError(f"Revision {revision} not found for workflow {workflow_id}")

            return {
                "id": r.id,
                "workflow_id": r.workflow_id,
                "revision": r.revision,
                "definition": json.loads(r.definition_json),
                "definition_sha256": r.definition_sha256,
                "created_by_user_id": r.created_by_user_id,
                "created_at": r.created_at.isoformat(),
            }

    def preview_workflow(self, workflow_id: int, payload: WorkflowPreviewRequest) -> dict[str, Any]:
        with self.SessionLocal() as session:
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            if wf.archived_at is not None:
                raise WorkflowArchivedError(f"Workflow {workflow_id} is archived")

            target_revision = payload.revision if payload.revision is not None else wf.current_revision
            rev = session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf.id,
                    WorkflowRevision.revision == target_revision,
                )
            )
            if not rev:
                raise RecipeRevisionNotFoundError(f"Revision {target_revision} not found for workflow {workflow_id}")

            def_dict = json.loads(rev.definition_json)
            mode = def_dict.get("mode")
            validate_raw_steps_types(def_dict.get("steps", []), mode=mode)
            definition = WorkflowDefinition.model_validate(def_dict)

            scan_job_id: int | None = None
            effective_root_ids: list[int] | None = None

            if definition.mode == "dedupe":
                if payload.root_ids is not None or (payload.runtime_inputs is not None and payload.runtime_inputs.root_ids is not None):
                    raise WorkflowValidationError(
                        "root_ids is forbidden in dedupe workflow mode",
                        code="INVALID_RUNTIME_INPUTS",
                    )
                if payload.runtime_inputs is None or payload.runtime_inputs.scan_job_id is None:
                    raise WorkflowValidationError(
                        "runtime_inputs.scan_job_id is required for dedupe workflow",
                        code="SCAN_JOB_REQUIRED",
                    )
                scan_job_id = payload.runtime_inputs.scan_job_id
            else:
                if payload.runtime_inputs is not None and payload.runtime_inputs.scan_job_id is not None:
                    raise WorkflowValidationError(
                        "scan_job_id is forbidden in file/organizer workflow mode",
                        code="INVALID_RUNTIME_INPUTS",
                    )
                if payload.root_ids is not None and payload.runtime_inputs is not None:
                    raise WorkflowValidationError(
                        "Ambiguous root inputs: cannot provide both top-level 'root_ids' and 'runtime_inputs'",
                        code="AMBIGUOUS_RUNTIME_INPUTS",
                    )
                effective_root_ids = (
                    payload.runtime_inputs.root_ids
                    if payload.runtime_inputs and payload.runtime_inputs.root_ids is not None
                    else payload.root_ids
                )

            res = self.compile_workflow_definition(
                session=session,
                definition=definition,
                workflow_id=wf.id,
                workflow_revision=target_revision,
                definition_sha256=rev.definition_sha256,
                override_root_ids=effective_root_ids,
                scan_job_id=scan_job_id,
            )

            if definition.mode == "dedupe":
                all_rows = res.compile_context.get("all_rows", [])
                if payload.only_changed:
                    selected_rows = [r for r in all_rows if r.get("changed")]
                else:
                    selected_rows = all_rows

                total = len(selected_rows)
                page_size = payload.page_size
                total_pages = ceil(total / page_size) if total > 0 else 1
                start = (payload.page - 1) * page_size
                end = start + page_size
                page_items = selected_rows[start:end]

                preview_items = [
                    {
                        "source_path": item["source"],
                        "target_path": item.get("target"),
                        "operation": item["operation"],
                        "mtime_ns": item.get("mtime_ns"),
                        "changed": item.get("changed", False),
                        "metadata": {k: v for k, v in item.items() if k not in {"source", "target", "operation", "mtime_ns", "changed"}},
                    }
                    for item in page_items
                ]

                return {
                    "workflow_id": wf.id,
                    "revision": target_revision,
                    "workflow_revision": target_revision,
                    "definition_sha256": rev.definition_sha256,
                    "preview_source": "completed-scan-readonly-safety",
                    "live_filesystem_verified": False,
                    "compile_digest": res.compile_digest,
                    "matched_count": res.matched_count,
                    "matched_bytes": res.matched_bytes,
                    "planned_operations_count": len(res.planned_operations),
                    "page": payload.page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "items": preview_items,
                }
            else:
                all_items = res.planned_operations
                if payload.only_changed:
                    all_items = [item for item in all_items if item.get("operation") in {"rename", "move", "quarantine"}]

                total = len(all_items)
                page_size = payload.page_size
                total_pages = ceil(total / page_size) if total > 0 else 1
                start = (payload.page - 1) * page_size
                end = start + page_size
                page_items = all_items[start:end]

                preview_items = [
                    {
                        "source_path": item["source"],
                        "target_path": item.get("target"),
                        "operation": item["operation"],
                        "mtime_ns": item.get("mtime_ns"),
                        "changed": item.get("operation") in {"rename", "move", "quarantine"},
                        "metadata": {k: v for k, v in item.items() if k not in {"source", "target", "operation", "mtime_ns"}},
                    }
                    for item in page_items
                ]

                return {
                    "workflow_id": wf.id,
                    "revision": target_revision,
                    "workflow_revision": target_revision,
                    "definition_sha256": rev.definition_sha256,
                    "preview_source": "organizer-live-readonly" if definition.mode == "organizer" else "index",
                    "live_filesystem_verified": False,
                    "compile_digest": res.compile_digest,
                    "matched_count": res.matched_count,
                    "matched_bytes": res.matched_bytes,
                    "planned_operations_count": len(res.planned_operations),
                    "page": payload.page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "items": preview_items,
                }

    def generate_plan(
        self,
        user_id: int | None,
        workflow_id: int,
        payload: WorkflowGeneratePlanRequest,
    ) -> dict[str, Any]:
        with self.SessionLocal() as session:
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            if wf.archived_at is not None:
                raise WorkflowArchivedError(f"Workflow {workflow_id} is archived")

            target_revision = payload.revision if payload.revision is not None else wf.current_revision
            rev = session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf.id,
                    WorkflowRevision.revision == target_revision,
                )
            )
            if not rev:
                raise RecipeRevisionNotFoundError(f"Revision {target_revision} not found for workflow {workflow_id}")

            def_dict = json.loads(rev.definition_json)
            mode = def_dict.get("mode")
            validate_raw_steps_types(def_dict.get("steps", []), mode=mode)
            definition = WorkflowDefinition.model_validate(def_dict)

            scan_job_id: int | None = None
            effective_root_ids: list[int] | None = None

            if definition.mode == "dedupe":
                if payload.root_ids is not None or (payload.runtime_inputs is not None and payload.runtime_inputs.root_ids is not None):
                    raise WorkflowValidationError(
                        "root_ids is forbidden in dedupe workflow mode",
                        code="INVALID_RUNTIME_INPUTS",
                    )
                if payload.runtime_inputs is None or payload.runtime_inputs.scan_job_id is None:
                    raise WorkflowValidationError(
                        "runtime_inputs.scan_job_id is required for dedupe workflow",
                        code="SCAN_JOB_REQUIRED",
                    )
                scan_job_id = payload.runtime_inputs.scan_job_id
            else:
                if payload.runtime_inputs is not None and payload.runtime_inputs.scan_job_id is not None:
                    raise WorkflowValidationError(
                        "scan_job_id is forbidden in file/organizer workflow mode",
                        code="INVALID_RUNTIME_INPUTS",
                    )
                if payload.root_ids is not None and payload.runtime_inputs is not None:
                    raise WorkflowValidationError(
                        "Ambiguous root inputs: cannot provide both top-level 'root_ids' and 'runtime_inputs'",
                        code="AMBIGUOUS_RUNTIME_INPUTS",
                    )
                effective_root_ids = (
                    payload.runtime_inputs.root_ids
                    if payload.runtime_inputs and payload.runtime_inputs.root_ids is not None
                    else payload.root_ids
                )

            # Phase A: Read-only recompile
            res = self.compile_workflow_definition(
                session=session,
                definition=definition,
                workflow_id=wf.id,
                workflow_revision=target_revision,
                definition_sha256=rev.definition_sha256,
                override_root_ids=effective_root_ids,
                scan_job_id=scan_job_id,
            )

            if not payload.expected_compile_digest or payload.expected_compile_digest != res.compile_digest:
                raise WorkflowDigestMismatchError(
                    f"Workflow compile digest mismatch: expected '{payload.expected_compile_digest}', got '{res.compile_digest}'",
                    details={
                        "expected_compile_digest": payload.expected_compile_digest,
                        "actual_compile_digest": res.compile_digest,
                    },
                )

            if not res.planned_operations:
                raise WorkflowValidationError("No operations planned in this workflow", code="EMPTY_PLAN")

        # Phase B: BEGIN IMMEDIATE short transaction
        with self.SessionLocal() as write_session:
            write_session.execute(text("BEGIN IMMEDIATE"))
            wf_b = write_session.get(Workflow, workflow_id)
            if not wf_b:
                write_session.rollback()
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            if wf_b.archived_at is not None:
                write_session.rollback()
                raise WorkflowArchivedError(f"Workflow {workflow_id} is archived")

            rev_b = write_session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf_b.id,
                    WorkflowRevision.revision == target_revision,
                )
            )
            if not rev_b:
                write_session.rollback()
                raise RecipeRevisionNotFoundError(f"Revision {target_revision} not found for workflow {workflow_id}")

            if rev_b.definition_sha256 != rev.definition_sha256:
                write_session.rollback()
                raise WorkflowDigestMismatchError(
                    "Workflow definition changed during transaction",
                    details={"expected": rev.definition_sha256, "actual": rev_b.definition_sha256},
                )

            if definition.mode == "dedupe":
                compilation = res.compile_context["compilation"]
                intents = res.compile_context["intents"]
                current_lineage = compute_current_dedupe_db_lineage_digest(write_session, scan_job_id)
                if current_lineage != compilation.db_lineage_digest:
                    write_session.rollback()
                    raise WorkflowDigestMismatchError(
                        "ScanJob duplicate lineage changed during transaction",
                        details={
                            "reason": "db_lineage_changed",
                            "expected_db_lineage_digest": compilation.db_lineage_digest,
                            "actual_db_lineage_digest": current_lineage,
                        },
                    )

                plan_name = payload.plan_name or f"工作流去重计划 - {wf_b.name} (r{target_revision})"
                plan_metadata = {
                    "source": "workflow",
                    "workflow_mode": "dedupe",
                    "workflow_id": wf_b.id,
                    "workflow_name": wf_b.name,
                    "workflow_revision": target_revision,
                    "definition_sha256": rev.definition_sha256,
                    "compile_digest": res.compile_digest,
                    "scan_job_id": scan_job_id,
                    "runtime_inputs": {
                        "scan_job_id": scan_job_id,
                    },
                    "dedupe_engine_version": 1,
                    "scorer_config": canonical_config_dict(compilation.scorer_config),
                    "scorer_config_digest": compilation.scorer_config_digest,
                    "source_snapshot_digest": compilation.source_snapshot_digest,
                    "decision_digest": compilation.decision_digest,
                    "preview_digest": res.compile_context["preview_digest"],
                    "db_lineage_digest": compilation.db_lineage_digest,
                    "selection_mode": compilation.summary.get("selection_mode"),
                    "effective_safety_policy": res.compile_context["effective_safety_policy"],
                    "summary": {
                        "actionable_group_count": compilation.actionable_group_count,
                        "skipped_group_count": compilation.skipped_group_count,
                        "planned_quarantine_count": compilation.planned_quarantine_count,
                        "expected_reclaim_bytes": compilation.expected_reclaim_bytes,
                        "released_bytes_by_scan_root": {
                            str(key): value
                            for key, value in sorted(compilation.released_bytes_by_scan_root.items())
                        },
                    },
                }

                plan = BatchPlan(
                    name=plan_name,
                    kind=f"workflow-{wf_b.id}",
                    status="draft",
                    expected_changes=len(intents),
                    expected_reclaim_bytes=compilation.expected_reclaim_bytes,
                    metadata_json=json.dumps(plan_metadata, ensure_ascii=False, sort_keys=True),
                )
                write_session.add(plan)
                write_session.flush()

                for intent in intents:
                    write_session.add(BatchPlanItem(
                        plan_id=plan.id,
                        sequence=intent.sequence,
                        operation=intent.operation,
                        source_path=intent.source_path,
                        target_path=None,
                        keep_path=intent.keep_path,
                        expected_size=intent.expected_size,
                        expected_mtime_ns=0,
                        expected_device=0,
                        expected_inode=0,
                        expected_hash=None,
                        state="planned",
                        metadata_json=intent.metadata_json,
                    ))

                write_session.commit()
                write_session.refresh(plan)

                return {
                    "plan_id": plan.id,
                    "plan_name": plan.name,
                    "status": plan.status,
                    "expected_changes": plan.expected_changes,
                    "compile_digest": res.compile_digest,
                }
            else:
                plan_name = payload.plan_name or f"工作流计划 - {wf_b.name} (r{target_revision})"
                plan_metadata = {
                    "source": "workflow",
                    "workflow_id": wf_b.id,
                    "workflow_name": wf_b.name,
                    "workflow_revision": target_revision,
                    "definition_sha256": rev.definition_sha256,
                    "compile_digest": res.compile_digest,
                    "runtime_inputs": res.runtime_inputs,
                    "compile_context": res.compile_context,
                    "matched_count": res.matched_count,
                    "matched_bytes": res.matched_bytes,
                }

                plan = BatchPlan(
                    name=plan_name,
                    kind=f"workflow-{wf_b.id}",
                    status="draft",
                    expected_changes=len(res.planned_operations),
                    expected_reclaim_bytes=0,
                    metadata_json=json.dumps(plan_metadata, ensure_ascii=False),
                )
                write_session.add(plan)
                write_session.flush()

                for op in res.planned_operations:
                    item_metadata = {k: v for k, v in op.items() if k not in {"source", "target", "operation", "sequence"}}
                    item = BatchPlanItem(
                        plan_id=plan.id,
                        sequence=op.get("sequence", 0),
                        operation=op["operation"],
                        source_path=op["source"],
                        target_path=op.get("target"),
                        expected_inode=0,
                        expected_device=0,
                        expected_mtime_ns=0,
                        state="pending",
                        metadata_json=json.dumps(item_metadata, ensure_ascii=False) if item_metadata else "{}",
                    )
                    write_session.add(item)

                write_session.commit()
                write_session.refresh(plan)

                return {
                    "plan_id": plan.id,
                    "plan_name": plan.name,
                    "status": plan.status,
                    "expected_changes": plan.expected_changes,
                    "compile_digest": res.compile_digest,
                }
