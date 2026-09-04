from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import get_current_user
from app.batch.rename import RenameRule
from app.models import User


router = APIRouter(prefix="/api", tags=["file-center"], dependencies=[Depends(get_current_user)])


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


class DedupePlanRequest(BaseModel):
    policy: str = "balanced-roots"
    path_priority_patterns: list[str] | None = None
    relative_path_priority_patterns: list[str] | None = None


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


@router.post("/scans/{scan_job_id}/dedupe-plan")
def create_dedupe_plan(request: Request, scan_job_id: int, payload: DedupePlanRequest):
    try:
        return request.app.state.service.create_dedupe_plan(
            scan_job_id,
            policy=payload.policy,
            path_priority_patterns=payload.path_priority_patterns,
            relative_path_priority_patterns=payload.relative_path_priority_patterns,
        )
    except KeyError as exc:
        raise HTTPException(404, "scan not found") from exc
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
def retry_task(request: Request, task_id: int):
    try:
        return request.app.state.service.retry_task(task_id)
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
def execute(request: Request, plan_id: int):
    try:
        return request.app.state.service.execute_plan(plan_id)
    except KeyError as exc:
        raise HTTPException(404, "plan not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


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
