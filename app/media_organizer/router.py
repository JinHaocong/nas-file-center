"""Authenticated read-only preview routes for the semantic media organizer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.auth.dependencies import require_admin_user

router = APIRouter(prefix="/api/media-organizer", tags=["media-organizer"])


class MediaOrganizerPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selection: str = Field(min_length=1, max_length=4096)


class MediaOrganizerExecuteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    unit: str = Field(min_length=1, max_length=4096)
    confirmation: str = Field(min_length=1, max_length=256)
    maintenance_window_confirmed: StrictBool = False


class MediaOrganizerRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation: str = Field(min_length=1, max_length=256)
    maintenance_window_confirmed: StrictBool = False


class MediaOrganizerCleanupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation: str = Field(min_length=1, max_length=256)
    maintenance_window_confirmed: StrictBool = False


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


@router.get('/previews/{job_id}/mappings/{mapping_id}')
def read_media_organizer_full_mapping(
    request: Request, job_id: int, mapping_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _admin=Depends(require_admin_user),
):
    """Read the complete source→target mapping in bounded pages."""
    from app.batch.media_organizer_jobs import get_media_organizer_mapping
    try:
        return get_media_organizer_mapping(
            request.app.state.service.SessionLocal, request.app.state.settings,
            job_id, mapping_id, page=page, page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='Preview mapping not found') from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/previews/{job_id}/execute')
def start_media_organizer_execution(request: Request, job_id: int,
                                   payload: MediaOrganizerExecuteRequest,
                                   _admin=Depends(require_admin_user)):
    """Only queues an explicitly confirmed, unit-scoped execution Worker."""
    from app.batch.media_organizer_execute_jobs import enqueue_media_organizer_execution
    try:
        return enqueue_media_organizer_execution(
            request.app.state.service.SessionLocal, request.app.state.settings,
            preview_job_id=job_id, unit=payload.unit,
            confirmation=payload.confirmation,
            maintenance_window_confirmed=payload.maintenance_window_confirmed,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Preview not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/executions/{job_id}')
def read_media_organizer_execution(request: Request, job_id: int,
                                   _admin=Depends(require_admin_user)):
    from app.batch.media_organizer_execute_jobs import get_media_organizer_execution
    try:
        return get_media_organizer_execution(
            request.app.state.service.SessionLocal, job_id,
            settings=request.app.state.settings,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Execution not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/executions/{job_id}/cleanup-review')
def read_media_organizer_cleanup_review(
    request: Request, job_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _admin=Depends(require_admin_user),
):
    """Review retained original/stage/public evidence without authorizing unlink."""
    from app.batch.media_organizer_execute_jobs import get_media_organizer_cleanup_review
    try:
        return get_media_organizer_cleanup_review(
            request.app.state.service.SessionLocal, request.app.state.settings,
            job_id, page=page, page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Execution not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        # Inaccessible private worker evidence is a hold, never an invitation
        # to loosen NAS permissions or manufacture a positive cleanup receipt.
        raise HTTPException(409, str(exc)) from exc


@router.get('/executions/{job_id}/cleanup-audit')
def read_media_organizer_cleanup_audit(
    request: Request, job_id: int, _admin=Depends(require_admin_user),
):
    """Verify every frozen source/staged/final link without mutating media."""
    from app.batch.media_organizer_execute_jobs import get_media_organizer_cleanup_audit
    try:
        return get_media_organizer_cleanup_audit(
            request.app.state.service.SessionLocal,
            request.app.state.settings, job_id,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Execution not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/executions/{job_id}/cleanup-plan')
def read_media_organizer_cleanup_plan(
    request: Request, job_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _admin=Depends(require_admin_user),
):
    """Read immutable cleanup proposal. This endpoint cannot delete media."""
    from app.batch.media_organizer_execute_jobs import get_media_organizer_cleanup_plan
    try:
        return get_media_organizer_cleanup_plan(
            request.app.state.service.SessionLocal, request.app.state.settings,
            job_id, page=page, page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Execution not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/executions/{job_id}/cleanup')
def start_media_organizer_cleanup(
    request: Request, job_id: int, payload: MediaOrganizerCleanupRequest,
    _admin=Depends(require_admin_user),
):
    """Queue an independently confirmed WorkJob; NEVER delete in HTTP."""
    from app.batch.media_organizer_cleanup_jobs import enqueue_media_organizer_cleanup
    try:
        return enqueue_media_organizer_cleanup(
            request.app.state.service.SessionLocal, request.app.state.settings,
            execution_job_id=job_id, confirmation=payload.confirmation,
            maintenance_window_confirmed=payload.maintenance_window_confirmed,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Original execution not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/executions/{job_id}/recover')
def recover_media_organizer_execution(request: Request, job_id: int,
                                      payload: MediaOrganizerRecoveryRequest,
                                      _admin=Depends(require_admin_user)):
    from app.batch.media_organizer_execute_jobs import enqueue_media_organizer_recovery
    try:
        return enqueue_media_organizer_recovery(
            request.app.state.service.SessionLocal, request.app.state.settings,
            failed_job_id=job_id, confirmation=payload.confirmation,
            maintenance_window_confirmed=payload.maintenance_window_confirmed,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Original failed execution not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/executions/{job_id}/abandon')
def abandon_media_organizer_execution(
    request: Request, job_id: int,
    _admin=Depends(require_admin_user),
):
    """End a failed frozen task before publication; the Worker verifies no stage remains."""
    from app.batch.media_organizer_execute_jobs import enqueue_media_organizer_abandon
    try:
        return enqueue_media_organizer_abandon(
            request.app.state.service.SessionLocal,
            request.app.state.settings,
            failed_job_id=job_id,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Original execution not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/cleanups/{job_id}/recover')
def recover_media_organizer_cleanup(
    request: Request, job_id: int, payload: MediaOrganizerCleanupRequest,
    _admin=Depends(require_admin_user),
):
    """Approve one failed cleanup attempt; journal replay runs only in Worker."""
    from app.batch.media_organizer_cleanup_jobs import enqueue_media_organizer_cleanup_recovery
    try:
        return enqueue_media_organizer_cleanup_recovery(
            request.app.state.service.SessionLocal, request.app.state.settings,
            failed_job_id=job_id, confirmation=payload.confirmation,
            maintenance_window_confirmed=payload.maintenance_window_confirmed,
        )
    except KeyError as exc:
        raise HTTPException(404, 'Failed cleanup not found') from exc
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
