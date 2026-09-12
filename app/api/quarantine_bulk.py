from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user


router = APIRouter(
    prefix="/api/quarantine",
    tags=["file-center"],
    dependencies=[Depends(get_current_user)],
)


class QuarantineBulkPreviewRequest(BaseModel):
    action: str
    entry_ids: list[int] = Field(min_length=1)
    conflict_policy: str | None = None


@router.post("/bulk-preview")
def preview_quarantine_bulk(payload: QuarantineBulkPreviewRequest):
    raise HTTPException(status_code=501, detail="Gate6-A bulk preview not implemented")
