from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth.dependencies import get_current_user


router = APIRouter(
    prefix="/api/quarantine",
    tags=["file-center"],
    dependencies=[Depends(get_current_user)],
)


class QuarantineBulkPreviewRequest(BaseModel):
    action: Literal["restore", "purge"]
    entry_ids: list[int] = Field(min_length=1)
    conflict_policy: Literal["skip", "rename"] | None = None

    @field_validator("entry_ids")
    @classmethod
    def reject_duplicate_entry_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("entry_ids must not contain duplicates")
        return value


@router.post("/bulk-preview")
def preview_quarantine_bulk(payload: QuarantineBulkPreviewRequest):
    raise HTTPException(status_code=501, detail="Gate6-A bulk preview not implemented")
