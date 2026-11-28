"""Admin API for the recursive media organizer."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import require_admin_user
from app.batch import media_organizer_jobs as jobs
from app.maintenance.archive_files import HistoryArchiveUnavailable

router = APIRouter(
    prefix="/api/media-organizer", tags=["media-organizer"],
    dependencies=[Depends(require_admin_user)],
)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: str = Field(min_length=1, max_length=4096)
    batch_flow: Literal[True] = True


class BatchConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(min_length=1, max_length=5000)
    package_name: str = Field(min_length=1, max_length=255)
    new_package: bool


@router.post("/previews")
def start_preview(request: Request, payload: PreviewRequest):
    try:
        return jobs.enqueue_preview(request.app.state.service.SessionLocal,
                                    request.app.state.settings, payload.selection)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/previews/{job_id}")
def read_preview(request: Request, job_id: int, status_filter: str = "all",
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    try:
        return jobs.get_preview(
            request.app.state.service.SessionLocal, request.app.state.settings, job_id,
            page=page, page_size=page_size, status_filter=status_filter,
        )
    except KeyError as exc:
        raise HTTPException(404, "找不到此目录预览") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/previews/{job_id}/mappings/{mapping_id}")
def read_mapping(request: Request, job_id: int, mapping_id: str,
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
    try:
        return jobs.get_mapping(
            request.app.state.service.SessionLocal, request.app.state.settings, job_id, mapping_id,
            page=page, page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(404, "找不到此路径映射") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/previews/{job_id}/entries")
def read_current_entries(request: Request, job_id: int,
                         unit: str = Query(min_length=1, max_length=4096),
                         directory: str = Query(min_length=1, max_length=4096),
                         cursor: int = Query(ge=0, le=2**63 - 1),
                         page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    try:
        service = request.app.state.service
        return jobs.get_current_entries(service.SessionLocal, service.settings, job_id, unit=unit,
                                        cursor=cursor, directory=directory, page=page, page_size=page_size)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "当前整理单元或目录已不存在") from exc
    except OSError as exc:
        raise HTTPException(409, "无法读取该目录，请在文件空间核对") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/previews/{job_id}/loose-files/{loose_id}")
def read_loose_files(request: Request, job_id: int, loose_id: str,
                     page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
    try:
        return jobs.get_loose_files(
            request.app.state.service.SessionLocal, request.app.state.settings, job_id, loose_id,
            page=page, page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(404, "找不到此待归属清单") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/previews/{job_id}/loose-files/{loose_id}/assignments")
def create_assignment(request: Request, job_id: int, loose_id: str, payload: AssignmentRequest):
    try:
        return jobs.create_assignment_draft(
            request.app.state.service, job_id, loose_id, **payload.model_dump(),
        )
    except KeyError as exc:
        raise HTTPException(404, "找不到此待归属清单") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/previews/{job_id}/batches")
def start_batch(request: Request, job_id: int, _approval: BatchConfirmation):
    try:
        return jobs.enqueue_batch(request.app.state.service.SessionLocal, request.app.state.settings, job_id)
    except KeyError as exc:
        raise HTTPException(404, "找不到此目录预览") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/batches/{job_id}")
def read_batch(request: Request, job_id: int,
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
               status_filter: Literal["all", "success", "skipped", "conflict", "failed"] = "all"):
    try:
        service = request.app.state.service
        return jobs.get_batch(service.SessionLocal, service.settings, job_id, page=page, page_size=page_size,
                              status_filter=status_filter)
    except KeyError as exc:
        raise HTTPException(404, "找不到此整理任务") from exc
    except HistoryArchiveUnavailable as exc:
        raise HTTPException(503, "整理归档暂不可读，请检查配置目录 history-archives 中的归档文件") from exc
