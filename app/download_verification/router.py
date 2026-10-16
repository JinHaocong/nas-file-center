"""Admin-only, read-only WebDAV verification runs and paginated reports."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from app.auth.dependencies import require_admin_user
from app.models import WorkJob
from app.download_verification.engine import qualified_local_root
from app.download_verification.webdav import relative_parts, WebDAVError
from app.download_verification.models import DownloadVerificationRun, DownloadVerificationItem


router = APIRouter(prefix="/api/download-verifications", tags=["download-verification"],
                   dependencies=[Depends(require_admin_user)])


class NewVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    remote_root: str = Field(default="", max_length=4096)
    local_root: str = Field(min_length=1, max_length=4096)


def _summary(run: DownloadVerificationRun, job: WorkJob | None) -> dict:
    status = job.status if job else "unknown"
    # Never surface an identical verdict while the WorkJob is unfinished.
    result = run.result if run.finished_at and (status == "completed" or job is None) else "INCOMPLETE"
    return {
        "id": run.id, "work_job_id": run.work_job_id, "remote_root": run.remote_root,
        "local_root": run.local_root, "result": result, "job_status": status,
        "checked": run.checked, "total": run.total, "bytes_checked": run.bytes_checked,
        "error_code": run.error_code, "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.get("/configuration")
def configuration(request: Request):
    s = request.app.state.settings
    return {
        "configured": bool(s.download_verify_webdav_base_url and s.download_verify_webdav_user
                           and s.download_verify_webdav_password_file
                           ),
        "endpoint": s.download_verify_webdav_base_url,  # operator-provided, no secret
        "mode": "strict_sha256", "read_only": True,
    }


@router.post("", status_code=202)
def start_verification(request: Request, payload: NewVerification):
    settings = request.app.state.settings
    if not (settings.download_verify_webdav_base_url and settings.download_verify_webdav_user
            and settings.download_verify_webdav_password_file):
        raise HTTPException(503, "WEBDAV_NOT_CONFIGURED")
    try:
        remote = "/".join(relative_parts(payload.remote_root))
        local = str(qualified_local_root(payload.local_root, settings))
    except (ValueError, OSError) as exc:
        raise HTTPException(422, "INVALID_VERIFICATION_ROOT") from exc
    with request.app.state.service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        job = WorkJob(kind="download-verify-webdav", status="queued", state_json="{}")
        session.add(job)
        session.flush()
        run = DownloadVerificationRun(work_job_id=job.id, remote_root=remote, local_root=local,
                                      result="INCOMPLETE")
        session.add(run)
        session.flush()
        job.state_json = json.dumps({"run_id": run.id})
        data = {"id": run.id, "work_job_id": job.id, "job_status": "queued"}
        session.commit()
    return data


@router.get("")
def list_verifications(request: Request, page: int = 1, page_size: int = 50):
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    with request.app.state.service.SessionLocal() as session:
        total = session.scalar(select(func.count(DownloadVerificationRun.id))) or 0
        rows = session.scalars(select(DownloadVerificationRun).order_by(
            DownloadVerificationRun.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
        return {"total": total, "page": page, "page_size": page_size,
                "items": [_summary(row, session.get(WorkJob, row.work_job_id)) for row in rows]}


@router.get("/{run_id}")
def get_verification(request: Request, run_id: int):
    with request.app.state.service.SessionLocal() as session:
        run = session.get(DownloadVerificationRun, run_id)
        if run is None:
            raise HTTPException(404, "VERIFICATION_NOT_FOUND")
        return _summary(run, session.get(WorkJob, run.work_job_id))


@router.get("/{run_id}/items")
def list_verification_items(request: Request, run_id: int, page: int = 1,
                            page_size: int = 50, status: str | None = None):
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    with request.app.state.service.SessionLocal() as session:
        if session.get(DownloadVerificationRun, run_id) is None:
            raise HTTPException(404, "VERIFICATION_NOT_FOUND")
        condition = [DownloadVerificationItem.run_id == run_id]
        if status:
            condition.append(DownloadVerificationItem.status == status)
        total = session.scalar(select(func.count(DownloadVerificationItem.id)).where(*condition)) or 0
        rows = session.scalars(select(DownloadVerificationItem).where(*condition).order_by(
            DownloadVerificationItem.relative_path).limit(page_size).offset((page - 1) * page_size)).all()
        return {
            "total": total, "page": page, "page_size": page_size,
            "items": [{
                "relative_path": row.relative_path, "kind": row.kind, "status": row.status,
                "remote_size": row.remote_size, "local_size": row.local_size,
                "remote_sha256": row.remote_sha256, "local_sha256": row.local_sha256,
                "reason_code": row.reason_code,
            } for row in rows],
        }
