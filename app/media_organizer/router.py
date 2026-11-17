"""Authenticated read-only preview routes for the semantic media organizer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import require_admin_user

router = APIRouter(prefix="/api/media-organizer", tags=["media-organizer"])


class MediaOrganizerPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selection: str = Field(min_length=1, max_length=4096)


@router.post('/previews')
def start_media_organizer_preview(request: Request, payload: MediaOrganizerPreviewRequest,
                                  _admin=Depends(require_admin_user)):
    from app.batch.media_organizer_jobs import enqueue_media_organizer_preview
    try:
        return enqueue_media_organizer_preview(
            request.app.state.service.SessionLocal, request.app.state.settings,
            selection=payload.selection,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/previews/{job_id}')
def read_media_organizer_preview(request: Request, job_id: int,
                                 page: int = Query(default=1, ge=1),
                                 page_size: int = Query(default=25, ge=1, le=100),
                                 status_filter: str = Query(default='all'),
                                 _admin=Depends(require_admin_user)):
    from app.batch.media_organizer_jobs import get_media_organizer_preview
    try:
        return get_media_organizer_preview(
            request.app.state.service.SessionLocal, request.app.state.settings,
            job_id, page=page, page_size=page_size, status_filter=status_filter,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='Preview task not found') from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
