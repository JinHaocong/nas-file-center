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
from app.quarantine.purge_advisory import discover_unlink_purge_advisory
from app.quarantine.unlink_purge import SEMANTICS_VERSION, build_unlink_manifest


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
                has_transaction_identity = (
                    entry.authoritative_anchor_path is not None
                    or entry.tx_phase is not None
                    or int(entry.active_attempt_generation or 0) > 0
                )
                if not has_transaction_identity:
                    # Preserve the historical fail-closed behavior for legacy
                    # quarantine rows that do not have pathname-scoped NFC
                    # transaction ownership. Gate6-A2 does not infer authority.
                    item = {
                        "entry_id": entry_id,
                        "eligible": False,
                        "reason": "PERMANENT_PURGE_DEFERRED_UNSAFE_HARDLINK_SCOPE",
                    }
                    items.append(item)
                    digest_items.append({**identity, **item})
                    continue

                manifest = build_unlink_manifest(
                    entry,
                    service.settings.quarantine_root,
                )
                mutation_blockers = list(manifest.get("blockers") or [])
                advisory = discover_unlink_purge_advisory(session, entry, manifest)
                hardlink_paths = list(advisory.get("hardlink_survivors") or [])
                independent_paths = list(
                    advisory.get("same_content_independent_copies") or []
                )
                survivor_status = {
                    "verified_found": "found",
                    "verified_none": "none",
                    "incomplete": "incomplete",
                }.get(str(advisory.get("status") or ""), "incomplete")

                item = {
                    "entry_id": entry_id,
                    "eligible": not mutation_blockers,
                    "purge_semantics": SEMANTICS_VERSION,
                    "mutation_blockers": mutation_blockers,
                    "survivor_scope": advisory.get("scope"),
                    "survivor_status": survivor_status,
                    "hardlink_survivor_count": len(hardlink_paths),
                    "hardlink_survivor_paths": hardlink_paths,
                    "same_content_scope": advisory.get("same_content_scope"),
                    "same_content_status": advisory.get("same_content_status"),
                    "independent_copy_count": len(independent_paths),
                    "independent_copy_paths": independent_paths,
                    "advisory_diagnostics": list(advisory.get("diagnostics") or []),
                }
                if mutation_blockers:
                    item["reason"] = "UNLINK_MANIFEST_BLOCKED"
                items.append(item)

                # The mutation digest deliberately excludes advisory evidence.
                # It binds only persisted entry identity plus the exact
                # selected-entry pathname authority frozen by unlink_v1.
                digest_item = {
                    **identity,
                    "entry_id": entry_id,
                    "eligible": not mutation_blockers,
                    "purge_semantics": SEMANTICS_VERSION,
                    "mutation_blockers": mutation_blockers,
                    "unlink_manifest": manifest,
                }
                if mutation_blockers:
                    digest_item["reason"] = "UNLINK_MANIFEST_BLOCKED"
                digest_items.append(digest_item)
                continue

            original_target = validate_mutation_destination(
                entry.original_path,
                service.settings.allowed_roots,
                quarantine_root=service.settings.quarantine_root,
            )
            target_path = original_target
            skip_preexisting_target = (
                effective_conflict_policy == "skip"
                and (original_target.exists() or original_target.is_symlink())
            )
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
                "skip_preexisting_target": skip_preexisting_target,
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

    # Preview can expose Gate6-A2 unlink eligibility before Draft generation is
    # enabled. Keep purge Draft fail-closed until Task 6.3 persists the exact
    # unlink manifest under the new operation identity; never fall through to
    # the historical quarantine_purge draft shape.
    if payload.action == "purge":
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "BULK_SELECTION_BLOCKED",
                    "message": "Gate6-A2 bulk purge Draft is not enabled yet",
                    "details": {},
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
