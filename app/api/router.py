from __future__ import annotations

import re
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.auth.dependencies import get_current_user, require_admin_user
from app.batch.rename import RenameRule
from app.exceptions import PlanStaleError
from app.filters.schema import FilterPreviewRequest, FilterPreviewResponse
from app.filters.validation import FilterValidationError
from app.batch_utilities.schema import (
    BatchUtilityPreviewRequest,
    BatchUtilityGenerateRequest,
)
from app.batch_utilities.errors import (
    BatchUtilityError,
    BatchUtilityInvalidConfigError,
)
from app.models import User
from app.path_safety import UnsafePathError
from app.service import StateConflictError
from app.planning.dedupe_preview import (
    DedupeEmptyPlanError,
    DedupeError,
    DedupeFactorUnavailableError,
    DedupeInvalidConfigError,
    DedupeLimitExceededError,
    DedupePreviewChangedError,
    DedupeScanNotCompletedError,
    DedupeScanNotFoundError,
)
from app.workflows.schema import (
    PlanRebuildPreviewRequest,
    PlanRebuildRequest,
    WorkflowCreateRequest,
    WorkflowGeneratePlanRequest,
    WorkflowGeneratePlanResponse,
    WorkflowListItem,
    WorkflowPreviewRequest,
    WorkflowPreviewResponse,
    WorkflowResponse,
    WorkflowRevisionResponse,
    WorkflowRollbackRequest,
    WorkflowUpdateRequest,
)


router = APIRouter(prefix="/api", tags=["file-center"], dependencies=[Depends(get_current_user)])


class QuarantineRestoreRequest(BaseModel):
    conflict_policy: str = "skip"
    custom_target: str | None = None


class QuarantinePurgeRequest(BaseModel):
    confirmation: str


class QuarantineRetentionPolicyUpdateRequest(BaseModel):
    quarantine_retention_days: int

    @field_validator("quarantine_retention_days", mode="before")
    @classmethod
    def validate_strict_days(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("quarantine_retention_days must be an integer")
        if v not in (0, 7, 30, 90):
            raise ValueError("quarantine_retention_days must be one of 0, 7, 30, 90")
        return v


class IndexCreateRequest(BaseModel):
    root: str


class IndexMatchRequest(BaseModel):
    root_keys: list[str] = Field(min_length=1)
    mode: str = "relative-path"
    normalize_pattern: str | None = None
    normalize_replacement: str = ""


class ScanCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    roots: list[str] = Field(min_length=1)
    isolate: bool = False
    min_size: str | None = None
    name_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None


class DedupePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scorer_config: dict[str, Any] | None = None
    page: int = 1
    page_size: int = 50

    @field_validator("scorer_config", mode="before")
    @classmethod
    def validate_scorer_config(cls, v: Any) -> Any:
        if v is not None and not isinstance(v, dict):
            raise DedupeInvalidConfigError("scorer_config must be a dict or null", details={"field": "scorer_config"})
        return v

    @field_validator("page", mode="before")
    @classmethod
    def validate_page(cls, v: Any) -> int:
        if type(v) is not int or isinstance(v, bool):
            raise DedupeInvalidConfigError("page must be an integer", details={"field": "page"})
        if v < 1:
            raise DedupeInvalidConfigError("page must be >= 1", details={"field": "page"})
        return v

    @field_validator("page_size", mode="before")
    @classmethod
    def validate_page_size(cls, v: Any) -> int:
        if type(v) is not int or isinstance(v, bool):
            raise DedupeInvalidConfigError("page_size must be an integer", details={"field": "page_size"})
        if v < 1:
            raise DedupeInvalidConfigError("page_size must be >= 1", details={"field": "page_size"})
        if v > 500:
            raise DedupeInvalidConfigError("page_size cannot exceed 500", details={"field": "page_size"})
        return v


class DedupePlanRequest(BaseModel):
    policy: str = "balanced-roots"
    path_priority_patterns: list[str] | None = None
    relative_path_priority_patterns: list[str] | None = None
    scorer_config: dict[str, Any] | None = None
    expected_preview_digest: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_request_shape(cls, raw: Any) -> Any:
        if type(raw) is not dict:
            return raw

        has_scorer = "scorer_config" in raw
        has_expected = "expected_preview_digest" in raw

        if has_scorer:
            scorer = raw.get("scorer_config")
            if type(scorer) is not dict:
                raise DedupeInvalidConfigError(
                    "scorer_config must be an object for advanced Generate",
                    details={"field": "scorer_config"},
                )

            allowed_advanced_keys = {"scorer_config", "expected_preview_digest"}
            extra_or_mixed = [k for k in raw.keys() if k not in allowed_advanced_keys]
            if extra_or_mixed:
                legacy_fields = {
                    "policy",
                    "path_priority_patterns",
                    "relative_path_priority_patterns",
                }
                mixed = [k for k in extra_or_mixed if k in legacy_fields]
                if mixed:
                    raise DedupeInvalidConfigError(
                        "Advanced and legacy dedupe request fields cannot be mixed",
                        details={"mixed_fields": mixed},
                    )
                raise DedupeInvalidConfigError(
                    "Unexpected fields in advanced dedupe generate request",
                    details={"unexpected_fields": extra_or_mixed},
                )

            digest = raw.get("expected_preview_digest")
            if type(digest) is not str or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
                raise DedupeInvalidConfigError(
                    "expected_preview_digest must be exactly 64 hexadecimal characters",
                    details={"field": "expected_preview_digest"},
                )
            return raw

        if has_expected:
            raise DedupeInvalidConfigError(
                "expected_preview_digest requires scorer_config",
                details={"field": "expected_preview_digest"},
            )

        return raw

    @property
    def is_advanced(self) -> bool:
        return self.scorer_config is not None


class OrganizerProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    root: str | None = None
    recursive: bool = False
    image_extensions: list[str] | None = None
    video_extensions: list[str] | None = None
    rename_template: str = "{name}"
    statistics_template: str = "[{images}P {videos}V {size}]"
    preserve_tags: list[str] | None = None
    cleanup_patterns: list[str] | None = None
    numbering_mode: str = "none"
    numbering_start: int = 1
    numbering_padding: int = 3
    mtime_mode: str = "none"
    mtime_delay_seconds: float = Field(default=2.0, ge=0.0, le=60.0)


class OrganizerProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    root: str | None = None
    recursive: bool = False
    image_extensions: list[str] | None = None
    video_extensions: list[str] | None = None
    rename_template: str = "{name}"
    statistics_template: str = "[{images}P {videos}V {size}]"
    preserve_tags: list[str] | None = None
    cleanup_patterns: list[str] | None = None
    numbering_mode: str = "none"
    numbering_start: int = 1
    numbering_padding: int = 3
    mtime_mode: str = "none"
    mtime_delay_seconds: float = Field(default=2.0, ge=0.0, le=60.0)


class OrganizerProfilePreviewRequest(BaseModel):
    root: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=1000)
    only_changed: bool = False
    only_conflicts: bool = False
    snapshot_id: str | None = None


class OrganizerProfilePlanRequest(BaseModel):
    root: str | None = None
    include_touch: bool = True


class OrganizerProfileImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    profile: dict[str, Any]


class PathMatchRequest(BaseModel):
    roots: list[str]
    mode: str = "relative-path"
    normalize_pattern: str | None = None
    normalize_replacement: str = ""


class RenamePreviewRequest(BaseModel):
    paths: list[str]
    regex_pattern: str | None = None
    regex_replacement: str = ""
    prefix: str = ""
    suffix: str = ""
    number_start: int | None = None
    number_width: int = 3
    include_parent: bool = False


class PlanItemInput(BaseModel):
    operation: str
    source: str
    target: str | None = None
    keep: str | None = None
    expected_size: int = 0
    expected_hash: str | None = None
    protected_dir: str | None = None


class PlanCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=64)
    items: list[PlanItemInput] = Field(min_length=1)


class FavoriteCreateRequest(BaseModel):
    path: str = Field(min_length=1)
    label: str | None = None


class RecentRecordRequest(BaseModel):
    paths: list[str] = Field(min_length=1)


class DataLifecyclePolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_retention_days: int = Field(strict=True, ge=0, le=3650)

    @field_validator("audit_retention_days")
    @classmethod
    def validate_audit_retention_days(cls, v: Any) -> int:
        if isinstance(v, bool):
            raise ValueError("audit_retention_days cannot be a boolean")
        if not isinstance(v, int):
            raise ValueError("audit_retention_days must be an integer")
        if v < 0 or v > 3650:
            raise ValueError("audit_retention_days must be between 0 and 3650")
        return v


class FilterPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exclude_dir_names: list[str]


# Filesystem Browser & Path Management
@router.get("/filesystem/list")
def list_filesystem(
    request: Request,
    path: str | None = None,
    directories_only: bool = True,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    search: str | None = None,
):
    try:
        return request.app.state.service.list_directory(
            path=path,
            directories_only=directories_only,
            page=page,
            page_size=page_size,
            search=search,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.get("/filesystem/favorites")
def list_favorites(request: Request, current_user: User = Depends(get_current_user)):
    return {"items": request.app.state.service.list_favorites(current_user.id)}


@router.post("/filesystem/favorites")
def add_favorite(
    request: Request,
    payload: FavoriteCreateRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        fav = request.app.state.service.add_favorite(
            current_user.id,
            path=payload.path,
            label=payload.label,
        )
        return fav
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/filesystem/favorites/{favorite_id}")
def delete_favorite(
    request: Request,
    favorite_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        request.app.state.service.delete_favorite(current_user.id, favorite_id)
        return {"status": "ok", "deleted_id": favorite_id}
    except KeyError as exc:
        raise HTTPException(404, "favorite not found") from exc


@router.get("/filesystem/recent")
def list_recent(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    return {"items": request.app.state.service.list_recent_paths(current_user.id, limit=limit)}


@router.post("/filesystem/recent")
def record_recent(
    request: Request,
    payload: RecentRecordRequest,
    current_user: User = Depends(get_current_user),
):
    return {"items": request.app.state.service.record_recent_paths(current_user.id, payload.paths)}


# Dashboard
@router.get("/dashboard/summary")
def get_dashboard_summary(request: Request):
    return request.app.state.service.dashboard_summary()


# Settings status
@router.get("/settings")
def get_system_settings(request: Request):
    s = request.app.state.settings
    return {
        "allow_mutation": s.allow_mutation,
        "allow_delete": s.allow_delete,
        "protect_last_file": s.protect_last_file,
        "allowed_roots": [str(p) for p in s.allowed_roots],
        "quarantine_root": str(s.quarantine_root),
        "fclones_binary": s.fclones_binary,
        "verification_hash": s.verification_hash,
    }


# Indexes
@router.get("/indexes")
def list_indexes(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
):
    return request.app.state.service.list_index_roots(page=page, page_size=page_size)


@router.post("/indexes")
def create_index(request: Request, payload: IndexCreateRequest):
    try:
        return request.app.state.service.enqueue_index(payload.root)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/indexes/{index_root_id}")
def delete_index(request: Request, index_root_id: int):
    try:
        return request.app.state.service.delete_index_root(index_root_id)
    except KeyError as exc:
        raise HTTPException(404, f"Index root #{index_root_id} not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/index-match/preview")
def index_match(request: Request, payload: IndexMatchRequest):
    try:
        groups = request.app.state.service.index_match_preview(
            payload.root_keys,
            mode=payload.mode,
            normalize_pattern=payload.normalize_pattern,
            normalize_replacement=payload.normalize_replacement,
        )
        return {"groups": groups, "count": len(groups)}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


# Scans
@router.get("/scans")
def list_scans(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
):
    return request.app.state.service.list_scans(page=page, page_size=page_size)


@router.post("/scans")
def create_scan(request: Request, payload: ScanCreateRequest):
    try:
        return request.app.state.service.enqueue_scan(
            name=payload.name,
            roots=payload.roots,
            isolate=payload.isolate,
            min_size=payload.min_size,
            name_patterns=payload.name_patterns,
            exclude_patterns=payload.exclude_patterns,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/scans/{scan_job_id}")
def scan_detail(request: Request, scan_job_id: int):
    try:
        return request.app.state.service.scan_detail(scan_job_id)
    except KeyError as exc:
        raise HTTPException(404, "scan not found") from exc


@router.get("/scans/{scan_job_id}/groups")
def scan_groups(
    request: Request,
    scan_job_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
):
    try:
        return request.app.state.service.scan_groups(scan_job_id, page=page, page_size=page_size)
    except KeyError as exc:
        raise HTTPException(404, "scan not found") from exc


@router.post("/scans/{scan_job_id}/dedupe-preview")
def dedupe_preview(
    request: Request,
    scan_job_id: int,
    payload: DedupePreviewRequest = Body(...),
):
    service = request.app.state.service
    try:
        return service.get_dedupe_preview(
            scan_job_id=scan_job_id,
            scorer_config=payload.scorer_config,
            page=payload.page,
            page_size=payload.page_size,
        )
    except DedupeError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
    except ValueError as exc:
        msg = str(exc)
        if "DEDUPE_FACTOR_UNAVAILABLE" in msg:
            err = DedupeFactorUnavailableError(msg)
        elif "DEDUPE_LIMIT_EXCEEDED" in msg:
            err = DedupeLimitExceededError(msg)
        else:
            err = DedupeInvalidConfigError(msg)
        return JSONResponse(status_code=err.status_code, content=err.to_dict())


@router.post("/scans/{scan_job_id}/dedupe-plan")
def create_dedupe_plan(request: Request, scan_job_id: int, payload: DedupePlanRequest):
    service = request.app.state.service
    try:
        if payload.is_advanced:
            assert payload.scorer_config is not None
            assert payload.expected_preview_digest is not None
            try:
                return service.create_advanced_dedupe_plan(
                    scan_job_id,
                    scorer_config=payload.scorer_config,
                    expected_preview_digest=payload.expected_preview_digest,
                )
            except ValueError as exc:
                msg = str(exc)
                if "DEDUPE_FACTOR_UNAVAILABLE" in msg:
                    err = DedupeFactorUnavailableError(msg)
                elif "DEDUPE_LIMIT_EXCEEDED" in msg:
                    err = DedupeLimitExceededError(msg)
                else:
                    err = DedupeInvalidConfigError(msg)
                return JSONResponse(status_code=err.status_code, content=err.to_dict())

        return service.create_dedupe_plan(
            scan_job_id,
            policy=payload.policy,
            path_priority_patterns=payload.path_priority_patterns,
            relative_path_priority_patterns=payload.relative_path_priority_patterns,
        )
    except DedupeError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
    except KeyError as exc:
        raise HTTPException(404, "scan not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/scans/{scan_job_id}")
def delete_scan(request: Request, scan_job_id: int):
    try:
        return request.app.state.service.delete_scan(scan_job_id)
    except KeyError as exc:
        raise HTTPException(404, "Scan not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc



# =========================================================================
# Task Engine Endpoints (TASK-033)
# =========================================================================

class ClearTaskHistoryRequest(BaseModel):
    statuses: list[str] | None = None


@router.get("/tasks")
def list_tasks(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    status: str | None = None,
    job_type: str | None = None,
):
    return request.app.state.service.list_tasks(
        page=page, page_size=page_size, status=status, job_type=job_type
    )


@router.get("/tasks/worker")
def get_worker_status(request: Request):
    return request.app.state.service.get_worker_status()


@router.post("/tasks/clear-history")
def clear_task_history(request: Request, body: ClearTaskHistoryRequest | None = None):
    try:
        statuses = body.statuses if body else None
        return request.app.state.service.clear_task_history(statuses=statuses)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/tasks/{task_id}")
def get_task_detail(request: Request, task_id: int):
    try:
        return request.app.state.service.get_task_detail(task_id)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc


@router.post("/tasks/{task_id}/pause")
def pause_task(request: Request, task_id: int):
    try:
        return request.app.state.service.pause_task(task_id)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/tasks/{task_id}/resume")
def resume_task(request: Request, task_id: int):
    try:
        return request.app.state.service.resume_task(task_id)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/tasks/{task_id}/cancel")
def cancel_task(request: Request, task_id: int):
    try:
        return request.app.state.service.cancel_task(task_id)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/tasks/{task_id}/retry")
def retry_task(
    request: Request,
    task_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.retry_task(task_id, user_id=current_user.id)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/tasks/{task_id}")
def delete_task(request: Request, task_id: int):
    try:
        return request.app.state.service.delete_task(task_id)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/tasks/{task_id}/logs")
def get_task_logs(
    request: Request,
    task_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    level: str | None = None,
):
    try:
        return request.app.state.service.get_task_logs(
            task_id, page=page, page_size=page_size, level=level
        )
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc


# Legacy compatibility routes for v0.3.1 / v0.3.2 UI
@router.get("/work-jobs")
def list_work_jobs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
):
    return request.app.state.service.list_work_jobs(page=page, page_size=page_size)


@router.get("/work-jobs/{work_job_id}")
def work_job_detail(request: Request, work_job_id: int):
    try:
        return request.app.state.service.work_job_detail(work_job_id)
    except KeyError as exc:
        raise HTTPException(404, "work job not found") from exc


# =========================================================================
# Organizer Profiles Endpoints
# =========================================================================

@router.get("/organizer-profiles")
def list_organizer_profiles(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    current_user: User = Depends(get_current_user),
):
    items, total = request.app.state.service.list_organizer_profiles(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        search=search,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/organizer-profiles")
def create_organizer_profile(
    request: Request,
    payload: OrganizerProfileCreateRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        profile = request.app.state.service.create_organizer_profile(
            user_id=current_user.id,
            payload=payload.model_dump(),
        )
        return profile
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/organizer-profiles/{profile_id}")
def get_organizer_profile(
    request: Request,
    profile_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        profile = request.app.state.service.get_organizer_profile(profile_id, current_user.id)
        if not profile:
            raise HTTPException(404, "方案不存在")
        return profile
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.put("/organizer-profiles/{profile_id}")
def update_organizer_profile(
    request: Request,
    profile_id: int,
    payload: OrganizerProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        profile = request.app.state.service.update_organizer_profile(
            profile_id=profile_id,
            user_id=current_user.id,
            payload=payload.model_dump(),
        )
        return profile
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/organizer-profiles/{profile_id}")
def delete_organizer_profile(
    request: Request,
    profile_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        request.app.state.service.delete_organizer_profile(profile_id, current_user.id)
        return {"success": True}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/organizer-profiles/{profile_id}/clone")
def clone_organizer_profile(
    request: Request,
    profile_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        cloned = request.app.state.service.clone_organizer_profile(profile_id, current_user.id)
        return cloned
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/organizer-profiles/{profile_id}/export")
def export_organizer_profile(
    request: Request,
    profile_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.export_organizer_profile(profile_id, current_user.id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/organizer-profiles/import")
def import_organizer_profile(
    request: Request,
    payload: OrganizerProfileImportRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        imported = request.app.state.service.import_organizer_profile(
            user_id=current_user.id,
            payload=payload.model_dump(),
        )
        return imported
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/organizer-profiles/{profile_id}/preview")
def preview_organizer_profile(
    request: Request,
    profile_id: int,
    payload: OrganizerProfilePreviewRequest = Body(default_factory=OrganizerProfilePreviewRequest),
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.preview_organizer_profile(
            profile_id=profile_id,
            user_id=current_user.id,
            root_override=payload.root,
            page=payload.page,
            page_size=payload.page_size,
            only_changed=payload.only_changed,
            only_conflicts=payload.only_conflicts,
            snapshot_id=payload.snapshot_id,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/organizer-profiles/{profile_id}/plan")
def create_organizer_plan(
    request: Request,
    profile_id: int,
    payload: OrganizerProfilePlanRequest = Body(default_factory=OrganizerProfilePlanRequest),
    current_user: User = Depends(get_current_user),
):
    try:
        plan = request.app.state.service.create_organizer_plan(
            profile_id=profile_id,
            user_id=current_user.id,
            root_override=payload.root,
            include_touch=payload.include_touch,
        )
        return {"id": plan.id, "name": plan.name, "kind": plan.kind, "status": plan.status}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/path-match/preview")
def path_match(request: Request, payload: PathMatchRequest):
    try:
        groups = request.app.state.service.path_match_preview(
            payload.roots,
            mode=payload.mode,
            normalize_pattern=payload.normalize_pattern,
            normalize_replacement=payload.normalize_replacement,
        )
        return {"groups": groups, "count": len(groups)}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/rename/preview")
def rename_preview(request: Request, payload: RenamePreviewRequest):
    try:
        rule = RenameRule(
            regex_pattern=payload.regex_pattern,
            regex_replacement=payload.regex_replacement,
            prefix=payload.prefix,
            suffix=payload.suffix,
            number_start=payload.number_start,
            number_width=payload.number_width,
            include_parent=payload.include_parent,
        )
        return {"items": request.app.state.service.rename_preview(payload.paths, rule)}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


# Plans
class PlanClearHistoryRequest(BaseModel):
    statuses: list[str] | None = None


@router.post("/plans/clear-history")
def clear_plan_history(request: Request, body: PlanClearHistoryRequest | None = None):
    try:
        statuses = body.statuses if body else None
        return request.app.state.service.clear_plan_history(statuses=statuses)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/plans/legacy/summary")
def legacy_plan_summary(request: Request):
    return request.app.state.service.legacy_plan_summary()


@router.post("/plans/legacy/clear")
def clear_legacy_plans(request: Request):
    return request.app.state.service.clear_legacy_plans()


@router.get("/plans")
def list_plans(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
):
    return request.app.state.service.list_plans(page=page, page_size=page_size)


@router.post("/plans")
def create_plan(request: Request, payload: PlanCreateRequest):
    try:
        plan = request.app.state.service.create_plan(
            name=payload.name,
            kind=payload.kind,
            items=[item.model_dump() for item in payload.items],
        )
        return {"id": plan.id, "status": plan.status, "expected_changes": plan.expected_changes}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/plans/{plan_id}")
def plan_detail(
    request: Request,
    plan_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    try:
        return request.app.state.service.plan_detail(plan_id, page=page, page_size=page_size)
    except KeyError as exc:
        raise HTTPException(404, "plan not found") from exc


@router.get("/plans/{plan_id}/items")
def plan_items(
    request: Request,
    plan_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    try:
        return request.app.state.service.plan_items(plan_id, page=page, page_size=page_size)
    except KeyError as exc:
        raise HTTPException(404, "plan not found") from exc


@router.post("/plans/{plan_id}/freeze")
def freeze(request: Request, plan_id: int):
    try:
        plan = request.app.state.service.freeze_plan(plan_id)
        return {"id": plan.id, "status": plan.status}
    except KeyError as exc:
        raise HTTPException(404, "plan not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/plans/{plan_id}/validate")
def validate(request: Request, plan_id: int):
    try:
        return request.app.state.service.validate_plan(plan_id)
    except KeyError as exc:
        raise HTTPException(404, "plan not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/plans/{plan_id}/execute")
def execute(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.enqueue_plan_execution(plan_id, user_id=current_user.id)
    except PlanStaleError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "PLAN_STALE",
                    "message": exc.message,
                    "details": {
                        "plan_id": exc.plan_id,
                        "stale_count": len(exc.stale_items),
                        "stale_items": exc.stale_items,
                    },
                }
            },
        )
    except KeyError as exc:
        raise HTTPException(404, "plan not found") from exc
    except StateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc



@router.delete("/plans/{plan_id}")
def delete_plan(request: Request, plan_id: int):
    try:
        return request.app.state.service.delete_plan(plan_id)
    except KeyError as exc:
        raise HTTPException(404, "Plan not found") from exc
    except StateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/plans/{plan_id}/undo-plan")
def undo_plan(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.create_undo_plan(plan_id, user_id=current_user.id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except StateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/plans/{plan_id}/rebuild-preview")
def rebuild_plan_preview(
    request: Request,
    plan_id: int,
    payload: PlanRebuildPreviewRequest | None = None,
    current_user: User = Depends(get_current_user),
):
    body = payload or PlanRebuildPreviewRequest()
    try:
        return request.app.state.service.rebuild_plan_preview(
            plan_id=plan_id,
            page=body.page,
            page_size=body.page_size,
            only_changed=body.only_changed,
            user_id=current_user.id,
        )
    except KeyError as exc:
        raise HTTPException(404, "Plan not found") from exc


@router.post("/plans/{plan_id}/rebuild", status_code=201)
def rebuild_plan(
    request: Request,
    plan_id: int,
    payload: PlanRebuildRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.rebuild_plan(
            plan_id=plan_id,
            expected_compile_digest=payload.expected_compile_digest,
            plan_name=payload.plan_name,
            user_id=current_user.id,
        )
    except KeyError as exc:
        raise HTTPException(404, "Plan not found") from exc


@router.get("/plans/{plan_id}/operation-journal")
def list_plan_operation_journal(
    request: Request,
    plan_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    return request.app.state.service.list_operation_journal(
        page=page,
        page_size=page_size,
        plan_id=plan_id,
    )


@router.get("/operation-journal")
def list_operation_journal(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    operation: str | None = Query(default=None),
    plan_id: int | None = Query(default=None),
    task_id: int | None = Query(default=None),
):
    return request.app.state.service.list_operation_journal(
        page=page,
        page_size=page_size,
        operation=operation,
        plan_id=plan_id,
        task_id=task_id,
    )



# Audit
@router.get("/audit")
def list_audit_events(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    query: str | None = Query(default=None),
    operation: str | None = Query(default=None),
):
    return request.app.state.service.list_audit_events(
        page=page,
        page_size=page_size,
        query=query,
        operation=operation,
    )


@router.get("/audit/retention-preview")
def preview_audit_retention(request: Request):
    return request.app.state.service.preview_audit_retention()


@router.post("/audit/apply-retention")
def apply_audit_retention(
    request: Request,
    admin_user: User = Depends(require_admin_user),
):
    try:
        return request.app.state.service.apply_audit_retention()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# Data Lifecycle Policy
@router.get("/data-lifecycle")
def get_data_lifecycle_policy(request: Request):
    return request.app.state.service.get_data_lifecycle_policy()


@router.put("/data-lifecycle")
def update_data_lifecycle_policy(
    request: Request,
    body: DataLifecyclePolicyUpdateRequest,
    admin_user: User = Depends(require_admin_user),
):
    try:
        return request.app.state.service.update_data_lifecycle_policy(body.audit_retention_days)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# Filter Policy
@router.get("/filter-policy")
def get_filter_policy(request: Request, current_user: User = Depends(get_current_user)):
    return request.app.state.service.get_filter_policy()


@router.put("/filter-policy")
def update_filter_policy(
    request: Request,
    body: FilterPolicyUpdateRequest,
    admin_user: User = Depends(require_admin_user),
):
    try:
        return request.app.state.service.update_filter_policy(body.exclude_dir_names)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/filters/preview", response_model=FilterPreviewResponse)
def preview_filter(
    request: Request,
    payload: FilterPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.preview_filter(
            roots=payload.roots,
            filter_node=payload.filter,
            page=payload.page,
            page_size=payload.page_size,
            sort_by=payload.sort_by,
            sort_order=payload.sort_order,
        )
    except UnsafePathError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (FilterValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


# Quarantine Core
@router.get("/quarantine")
def list_quarantine(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    state: str | None = Query(default=None),
    query: str | None = Query(default=None),
    search: str | None = Query(default=None),
):
    effective_query = query if query is not None else search
    return request.app.state.service.list_quarantine_entries(
        page=page,
        page_size=page_size,
        state=state,
        search=effective_query,
    )


@router.get("/quarantine/retention-policy")
def get_quarantine_retention_policy(request: Request):
    return request.app.state.service.get_quarantine_retention_policy()


@router.put("/quarantine/retention-policy")
def update_quarantine_retention_policy(
    request: Request,
    payload: QuarantineRetentionPolicyUpdateRequest,
    admin_user: User = Depends(require_admin_user),
):
    try:
        return request.app.state.service.update_quarantine_retention_policy(
            payload.quarantine_retention_days
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/quarantine/{id}")
def get_quarantine_entry(request: Request, id: int):
    try:
        return request.app.state.service.get_quarantine_entry(id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/quarantine/{id}/restore")
def restore_quarantine_entry(
    request: Request,
    id: int,
    payload: QuarantineRestoreRequest = QuarantineRestoreRequest(),
    current_user: User = Depends(get_current_user),
):
    try:
        return request.app.state.service.restore_quarantine_entry(
            id,
            conflict_policy=payload.conflict_policy,
            custom_target=payload.custom_target,
            user_id=current_user.id,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except StateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/quarantine/{id}/purge")
def purge_quarantine_entry(
    request: Request,
    id: int,
    payload: QuarantinePurgeRequest,
    admin_user: User = Depends(require_admin_user),
):
    try:
        return request.app.state.service.purge_quarantine_entry(
            id,
            confirmation=payload.confirmation,
            is_admin=True,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except StateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# Workflow Routes
@router.get("/workflows", response_model=list[WorkflowListItem])
def list_workflows(
    request: Request,
    include_archived: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
):
    return request.app.state.service.workflow_service.list_workflows(include_archived=include_archived)


@router.post("/workflows", response_model=WorkflowResponse, status_code=201)
def create_workflow(
    request: Request,
    payload: WorkflowCreateRequest,
    admin_user: User = Depends(require_admin_user),
):
    return request.app.state.service.workflow_service.create_workflow(admin_user.id, payload)


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    request: Request,
    workflow_id: int,
    current_user: User = Depends(get_current_user),
):
    return request.app.state.service.workflow_service.get_workflow(workflow_id)


@router.put("/workflows/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    request: Request,
    workflow_id: int,
    payload: WorkflowUpdateRequest,
    admin_user: User = Depends(require_admin_user),
):
    return request.app.state.service.workflow_service.update_workflow(admin_user.id, workflow_id, payload)


@router.delete("/workflows/{workflow_id}")
def archive_workflow(
    request: Request,
    workflow_id: int,
    expected_current_revision: int = Query(...),
    admin_user: User = Depends(require_admin_user),
):
    request.app.state.service.workflow_service.archive_workflow(
        admin_user.id,
        workflow_id,
        expected_current_revision=expected_current_revision,
    )
    return {"status": "ok", "archived": True}


@router.post("/workflows/{workflow_id}/rollback", response_model=WorkflowResponse)
def rollback_workflow(
    request: Request,
    workflow_id: int,
    payload: WorkflowRollbackRequest,
    admin_user: User = Depends(require_admin_user),
):
    return request.app.state.service.workflow_service.rollback_workflow(admin_user.id, workflow_id, payload)


@router.get("/workflows/{workflow_id}/revisions", response_model=list[WorkflowRevisionResponse])
def list_workflow_revisions(
    request: Request,
    workflow_id: int,
    current_user: User = Depends(get_current_user),
):
    return request.app.state.service.workflow_service.list_workflow_revisions(workflow_id)


@router.get("/workflows/{workflow_id}/revisions/{revision}", response_model=WorkflowRevisionResponse)
def get_workflow_revision(
    request: Request,
    workflow_id: int,
    revision: int,
    current_user: User = Depends(get_current_user),
):
    return request.app.state.service.workflow_service.get_workflow_revision(workflow_id, revision)


@router.post("/workflows/{workflow_id}/preview", response_model=WorkflowPreviewResponse)
def preview_workflow(
    request: Request,
    workflow_id: int,
    payload: WorkflowPreviewRequest = Body(default_factory=WorkflowPreviewRequest),
    current_user: User = Depends(get_current_user),
):
    return request.app.state.service.workflow_service.preview_workflow(workflow_id, payload)


@router.post("/workflows/{workflow_id}/generate-plan", response_model=WorkflowGeneratePlanResponse, status_code=201)
def generate_workflow_plan(
    request: Request,
    workflow_id: int,
    payload: WorkflowGeneratePlanRequest,
    current_user: User = Depends(get_current_user),
):
    return request.app.state.service.workflow_service.generate_plan(current_user.id, workflow_id, payload)


@router.post("/batch-utilities/preview")
def preview_batch_utility(
    request: Request,
    payload: Any = Body(...),
    current_user: User = Depends(get_current_user),
):
    try:
        req = BatchUtilityPreviewRequest.model_validate(payload)
    except ValidationError as ve:
        err = BatchUtilityInvalidConfigError(f"Validation error: {ve}", details={"errors": ve.errors()})
        return JSONResponse(status_code=err.status_code, content=err.to_dict())
    except Exception as e:
        err = BatchUtilityInvalidConfigError(f"Malformed request payload: {e}")
        return JSONResponse(status_code=err.status_code, content=err.to_dict())

    service = request.app.state.service
    try:
        preview_data = service.get_batch_utility_preview(
            action=req.action,
            page=req.page,
            page_size=req.page_size,
        )
        return preview_data
    except BatchUtilityError as bu_err:
        return JSONResponse(status_code=bu_err.status_code, content=bu_err.to_dict())
    except Exception as e:
        err = BatchUtilityInvalidConfigError(str(e))
        return JSONResponse(status_code=err.status_code, content=err.to_dict())


