from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth.dependencies import get_current_user
from app.models import QuarantineEntry
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


def _compute_bulk_preview(service, payload: QuarantineBulkPreviewRequest) -> dict[str, object]:
    entry_ids = canonicalize_entry_ids(payload.entry_ids)
    items: list[dict[str, object]] = []
    digest_items: list[dict[str, object]] = []
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
    return {
        "action": payload.action,
        "entry_ids": entry_ids,
        "eligible_count": len(items) - blocked_count,
        "blocked_count": blocked_count,
        "items": items,
        "preview_digest": canonical_preview_digest(material),
    }


@router.post("/bulk-preview")
def preview_quarantine_bulk(request: Request, payload: QuarantineBulkPreviewRequest):
    return _compute_bulk_preview(request.app.state.service, payload)


@router.post("/bulk-plan")
def generate_quarantine_bulk_plan(request: Request, payload: QuarantineBulkPlanRequest):
    raise HTTPException(status_code=501, detail="Gate6-A bulk plan generation not implemented")
