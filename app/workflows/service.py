from __future__ import annotations

import json
from math import ceil
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, Workflow, WorkflowRevision, utcnow
from app.workflows.compiler import WorkflowCompiler, MAX_PREVIEW_CANDIDATES, MAX_GENERATE_CANDIDATES
from app.workflows.errors import (
    WorkflowArchivedError,
    WorkflowDigestMismatchError,
    WorkflowNotFoundError,
    WorkflowRevisionConflictError,
    WorkflowValidationError,
)
from app.workflows.revisions import canonical_json_dumps, compute_definition_sha256
from app.workflows.schema import (
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

    def list_workflows(self, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.SessionLocal() as session:
            stmt = select(Workflow)
            if not include_archived:
                stmt = stmt.where(Workflow.archived_at.is_(None))
            stmt = stmt.order_by(Workflow.is_builtin.desc(), Workflow.updated_at.desc(), Workflow.id.desc())
            workflows = session.scalars(stmt).all()
            return [
                {
                    "id": wf.id,
                    "name": wf.name,
                    "description": wf.description,
                    "current_revision": wf.current_revision,
                    "is_builtin": wf.is_builtin,
                    "archived_at": wf.archived_at.isoformat() if wf.archived_at else None,
                    "created_at": wf.created_at.isoformat(),
                    "updated_at": wf.updated_at.isoformat(),
                }
                for wf in workflows
            ]

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
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
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

            if payload.definition is not None:
                validate_workflow_definition(payload.definition, session)
                raw_def = payload.definition.model_dump()
                canon_json = canonical_json_dumps(raw_def)
                sha256_hash = compute_definition_sha256(raw_def)

                next_rev = wf.current_revision + 1
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
                if current_rev:
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

    def archive_workflow(self, user_id: int | None, workflow_id: int) -> None:
        with self.SessionLocal() as session:
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            if wf.archived_at is not None:
                return  # Idempotent
            wf.archived_at = utcnow()
            session.commit()

    def rollback_workflow(
        self,
        user_id: int | None,
        workflow_id: int,
        payload: WorkflowRollbackRequest,
    ) -> dict[str, Any]:
        with self.SessionLocal() as session:
            wf = session.get(Workflow, workflow_id)
            if not wf:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
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
                raise WorkflowNotFoundError(f"Target revision {payload.target_revision} not found")

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
                raise WorkflowNotFoundError(f"Revision {revision} not found for workflow {workflow_id}")

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

            rev = session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf.id,
                    WorkflowRevision.revision == wf.current_revision,
                )
            )
            if not rev:
                raise WorkflowNotFoundError(f"Current revision {wf.current_revision} not found")

            def_dict = json.loads(rev.definition_json)
            validate_raw_steps_types(def_dict.get("steps", []))
            definition = WorkflowDefinition.model_validate(def_dict)

            compiler = WorkflowCompiler(
                session=session,
                allowed_roots=self.settings.allowed_roots,
                quarantine_root=self.settings.quarantine_root,
            )
            res = compiler.compile(
                definition,
                override_root_ids=payload.root_ids,
                max_candidates=MAX_PREVIEW_CANDIDATES,
            )

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
                "revision": wf.current_revision,
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

            rev = session.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf.id,
                    WorkflowRevision.revision == wf.current_revision,
                )
            )
            if not rev:
                raise WorkflowNotFoundError(f"Current revision {wf.current_revision} not found")

            def_dict = json.loads(rev.definition_json)
            validate_raw_steps_types(def_dict.get("steps", []))
            definition = WorkflowDefinition.model_validate(def_dict)

            compiler = WorkflowCompiler(
                session=session,
                allowed_roots=self.settings.allowed_roots,
                quarantine_root=self.settings.quarantine_root,
            )
            res = compiler.compile(
                definition,
                override_root_ids=payload.root_ids,
                max_candidates=MAX_GENERATE_CANDIDATES,
            )

            if payload.expected_compile_digest:
                if payload.expected_compile_digest != res.compile_digest:
                    raise WorkflowDigestMismatchError(
                        f"Workflow compile digest mismatch: expected '{payload.expected_compile_digest}', got '{res.compile_digest}'",
                        details={
                            "expected_compile_digest": payload.expected_compile_digest,
                            "actual_compile_digest": res.compile_digest,
                        },
                    )

            if not res.planned_operations:
                raise WorkflowValidationError("No operations planned in this workflow", code="EMPTY_PLAN")

            plan_name = payload.plan_name or f"工作流计划 - {wf.name} (r{wf.current_revision})"
            plan_metadata = {
                "source": "workflow",
                "workflow_id": wf.id,
                "workflow_name": wf.name,
                "workflow_revision": wf.current_revision,
                "definition_sha256": rev.definition_sha256,
                "compile_digest": res.compile_digest,
                "matched_count": res.matched_count,
                "matched_bytes": res.matched_bytes,
            }

            plan = BatchPlan(
                name=plan_name,
                kind=f"workflow-{wf.id}",
                status="draft",
                expected_changes=len(res.planned_operations),
                expected_reclaim_bytes=0,
                metadata_json=json.dumps(plan_metadata, ensure_ascii=False),
            )
            session.add(plan)
            session.flush()

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
                session.add(item)

            session.commit()
            session.refresh(plan)

            return {
                "plan_id": plan.id,
                "plan_name": plan.name,
                "status": plan.status,
                "expected_changes": plan.expected_changes,
                "compile_digest": res.compile_digest,
            }
