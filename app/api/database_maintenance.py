from __future__ import annotations

import logging
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.auth.dependencies import require_admin_user
from app.maintenance.database import MaintenanceConflict
from app.maintenance.history import ArchiveKind, archive_history_batch, preview_maintenance


router = APIRouter(prefix="/api/database-maintenance", dependencies=[Depends(require_admin_user)])
logger = logging.getLogger(__name__)


class ArchiveRequest(BaseModel):
    kind: ArchiveKind


@router.get("")
def get_database_maintenance(request: Request) -> dict:
    """Preview database usage and archive candidates for an administrator."""
    try:
        return preview_maintenance(request.app.state.settings, request.app.state.service.SessionLocal)
    except (OSError, sqlite3.OperationalError, OperationalError) as error:
        logger.warning("Unable to preview database maintenance", exc_info=True)
        raise HTTPException(503, "暂时无法读取数据库维护预览，请稍后重试") from error


@router.post("/archive")
def archive_database_history(request: Request, body: ArchiveRequest) -> dict:
    """Archive one batch without waiting for the next maintenance cycle."""
    try:
        result = archive_history_batch(
            request.app.state.settings, request.app.state.service.SessionLocal, body.kind,
        )
        return {"rows": result["rows"], "files": [Path(path).name for path in result["files"]]}
    except MaintenanceConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, OSError, OperationalError) as error:
        logger.warning("Unable to archive database history of kind %s", body.kind, exc_info=True)
        raise HTTPException(409, "本批归档未提交，请检查存储空间或稍后重试") from error
