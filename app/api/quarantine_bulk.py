from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth.dependencies import get_current_user
from app.api.quarantine_bulk_plan import persist_bulk_draft
from app.models import QuarantineEntry, User
from app.path_safety import validate_mutation_destination
from app.quarantine.bulk import (
    build_purge_topology_manifest,
    canonical_preview_digest,
    canonicalize_entry_ids,
    quarantine_entry_identity_material,
)
from app.quarantine.paths import build_restore_rename_path


router = APIRouter(
    prefix="/api/quarantine",
    tags=["file-center"],
    dependencies=[Depends(get_current_user)],
)


class QuarantineBulkPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["restore", "purge"]
    entry_ids: list[int] = Field(min_length=1, max_length=5000)
    conflict_policy: Literal["skip", "rename"] | None = None

    @field_validator("entry_ids")
    @classmethod
    def reject_duplicate_entry_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("entry_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def reject_restore_only_fields_for_purge(self) -> "QuarantineBulkPreviewRequest":
        if self.action == "purge" and self.conflict_policy is not None:
            raise ValueError("conflict_policy is only valid for restore")
        return self


class QuarantineBulkPlanRequest(QuarantineBulkPreviewRequest):
    expected_preview_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    confirmation: str | None = None

    @model_validator(mode="after")
    def require_purge_confirmation(self) -> "QuarantineBulkPlanRequest":
        if self.action == "purge" and self.confirmation != "DELETE":
            raise ValueError("purge bulk plan confirmation must be DELETE")
        return self


def _compute_bulk_preview(
    service,
    payload: QuarantineBulkPreviewRequest,
    *,
    include_internal: bool = False,
) -> dict[str, object]:
    entry_ids = canonicalize_entry_ids(payload.entry_ids)
    items: list[dict[str, object]] = []
    digest_items: list[dict[str, object]] = []
    db_identities: dict[int, dict[str, object]] = {}
    effective_conflict_policy = (payload.conflict_policy or "skip") if payload.action == "restore" else None

    with service.SessionLocal() as session:
        for entry_id in entry_ids:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                item = {
                    "entry_id": entry_id,
                    "eligible": False,
                    "reason": "MISSING_ENTRY",
                }
                items.append(item)
                digest_items.append(dict(item))
                continue

            identity = quarantine_entry_identity_material(entry)
            db_identities[entry_id] = identity
            if entry.state != "active":
                item = {
                    "entry_id": entry_id,
                    "eligible": False,
                    "reason": "NON_ACTIVE_ENTRY",
                    "state": entry.state,
                    "tx_phase": entry.tx_phase,
                }
                items.append(item)
                digest_items.append({**identity, **item})
                continue

            if payload.action == "purge":
                manifest = build_purge_topology_manifest(
                    entry,
                    service.settings.quarantine_root,
                    owner_lookup=lambda owner_id: session.get(QuarantineEntry, owner_id),
                )
                blockers = manifest["blockers"]
                item = {
                    "entry_id": entry_id,
                    "eligible": not blockers,
                    "reason": blockers[0] if blockers else None,
                    "purge_topology_manifest": manifest,
                }
                items.append(item)
                digest_items.append({**identity, **item})
                continue

            original_target = validate_mutation_destination(
                entry.original_path,
                service.settings.allowed_roots,
                quarantine_root=service.settings.quarantine_root,
            )
            target_path = original_target
            if effective_conflict_policy == "rename" and (
                original_target.exists() or original_target.is_symlink()
            ):
                target_path = validate_mutation_destination(
                    build_restore_rename_path(original_target, entry_id=entry.id),
                    service.settings.allowed_roots,
                    quarantine_root=service.settings.quarantine_root,
                )

            item = {
                "entry_id": entry_id,
                "eligible": True,
                "conflict_policy": effective_conflict_policy,
                "target_path": str(target_path),
            }
            items.append(item)
            digest_items.append({**identity, **item})

    material = {
        "action": payload.action,
        "entry_ids": entry_ids,
        "conflict_policy": effective_conflict_policy,
        "items": digest_items,
    }
    blocked_count = sum(1 for item in items if not item["eligible"])
    result: dict[str, object] = {
        "action": payload.action,
        "entry_ids": entry_ids,
        "eligible_count": len(items) - blocked_count,
        "blocked_count": blocked_count,
        "items": items,
        "preview_digest": canonical_preview_digest(material),
    }
    if include_internal:
        result["_db_identities"] = db_identities
    return result


@router.post("/bulk-preview")
def preview_quarantine_bulk(request: Request, payload: QuarantineBulkPreviewRequest):
    return _compute_bulk_preview(request.app.state.service, payload)


@router.post("/bulk-plan")
def generate_quarantine_bulk_plan(
    request: Request,
    payload: QuarantineBulkPlanRequest,
    current_user: User = Depends(get_current_user),
):
    service = request.app.state.service
    if not service.settings.allow_mutation:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "MUTATION_DISABLED",
                    "message": "Filesystem mutation is disabled",
                    "details": {},
                }
            },
        )
    if payload.action == "purge" and not service.settings.allow_delete:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "DELETE_DISABLED",
                    "message": "Filesystem deletion is disabled",
                    "details": {},
                }
            },
        )
    if payload.action == "purge" and current_user.role != "admin":
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "ADMIN_REQUIRED",
                    "message": "Admin privileges are required for permanent purge",
                    "details": {},
                }
            },
        )

    preview_payload = QuarantineBulkPreviewRequest(
        action=payload.action,
        entry_ids=payload.entry_ids,
        conflict_policy=payload.conflict_policy,
    )
    current_preview = _compute_bulk_preview(
        service,
        preview_payload,
        include_internal=True,
    )
    actual_digest = str(current_preview["preview_digest"])
    if actual_digest != payload.expected_preview_digest:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "PREVIEW_CHANGED",
                    "message": "Preview changed; run Preview again before generating a Draft",
                    "details": {
                        "expected_preview_digest": payload.expected_preview_digest,
                        "actual_preview_digest": actual_digest,
                    },
                }
            },
        )

    if int(current_preview["blocked_count"]) != 0:
        blocked_items = [
            item for item in current_preview["items"] if not bool(item["eligible"])
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "BULK_SELECTION_BLOCKED",
                    "message": "Selected quarantine entries are not eligible for this bulk action",
                    "details": {"blocked_items": blocked_items},
                }
            },
        )

    preview_items = {int(item["entry_id"]): item for item in current_preview["items"]}
    entry_ids = canonicalize_entry_ids(payload.entry_ids)
    conflict_policy = (payload.conflict_policy or "skip") if payload.action == "restore" else None
    expected_db_identities = current_preview["_db_identities"]

    try:
        plan_id, plan_kind = persist_bulk_draft(
            service,
            action=payload.action,
            entry_ids=entry_ids,
            preview_items=preview_items,
            preview_digest=actual_digest,
            conflict_policy=conflict_policy,
            expected_db_identities=expected_db_identities,
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "PREVIEW_CHANGED",
                    "message": "Preview changed; run Preview again before generating a Draft",
                    "details": {"reason": str(exc)},
                }
            },
        )

    return {
        "id": plan_id,
        "kind": plan_kind,
        "status": "draft",
        "expected_changes": len(entry_ids),
        "preview_digest": actual_digest,
    }
