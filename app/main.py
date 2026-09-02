from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from app.ui import router as ui_router

from app.batch.rename import RenameRule
from app.config import Settings, get_settings
from app.service import FileCenterService


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


class OrganizerPreviewRequest(BaseModel):
    root: str


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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    service = FileCenterService(settings)
    app = FastAPI(title="NAS File Center", version="0.2.0")
    app.state.service = service
    app.state.settings = settings

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "allow_mutation": settings.allow_mutation,
            "allow_delete": settings.allow_delete,
            "allowed_roots": [str(p) for p in settings.allowed_roots],
        }

    app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
    app.include_router(ui_router)

    @app.post("/api/indexes")
    def create_index(request: IndexCreateRequest):
        try:
            return service.enqueue_index(request.root)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/work-jobs/{work_job_id}")
    def work_job_detail(work_job_id: int):
        try:
            return service.work_job_detail(work_job_id)
        except KeyError as exc:
            raise HTTPException(404, "work job not found") from exc

    @app.post("/api/index-match/preview")
    def index_match(request: IndexMatchRequest):
        try:
            groups = service.index_match_preview(
                request.root_keys,
                mode=request.mode,
                normalize_pattern=request.normalize_pattern,
                normalize_replacement=request.normalize_replacement,
            )
            return {"groups": groups, "count": len(groups)}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/scans")
    def create_scan(request: ScanCreateRequest):
        try:
            return service.enqueue_scan(
                name=request.name,
                roots=request.roots,
                isolate=request.isolate,
                min_size=request.min_size,
                name_patterns=request.name_patterns,
                exclude_patterns=request.exclude_patterns,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/scans/{scan_job_id}")
    def scan_detail(scan_job_id: int):
        try:
            return service.scan_detail(scan_job_id)
        except KeyError as exc:
            raise HTTPException(404, "scan not found") from exc

    @app.post("/api/scans/{scan_job_id}/dedupe-plan")
    def create_dedupe_plan(scan_job_id: int, request: DedupePlanRequest):
        try:
            return service.create_dedupe_plan(
                scan_job_id,
                policy=request.policy,
                path_priority_patterns=request.path_priority_patterns,
                relative_path_priority_patterns=request.relative_path_priority_patterns,
            )
        except KeyError as exc:
            raise HTTPException(404, "scan not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/organizers/shaonv/preview")
    def shaonv_preview(request: OrganizerPreviewRequest):
        try:
            return {"items": service.shaonv_preview(request.root)}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/path-match/preview")
    def path_match(request: PathMatchRequest):
        try:
            groups = service.path_match_preview(request.roots, mode=request.mode, normalize_pattern=request.normalize_pattern, normalize_replacement=request.normalize_replacement)
            return {"groups": groups, "count": len(groups)}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/rename/preview")
    def rename_preview(request: RenamePreviewRequest):
        try:
            rule = RenameRule(
                regex_pattern=request.regex_pattern,
                regex_replacement=request.regex_replacement,
                prefix=request.prefix,
                suffix=request.suffix,
                number_start=request.number_start,
                number_width=request.number_width,
                include_parent=request.include_parent,
            )
            return {"items": service.rename_preview(request.paths, rule)}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/plans")
    def create_plan(request: PlanCreateRequest):
        try:
            plan = service.create_plan(name=request.name, kind=request.kind, items=[item.model_dump() for item in request.items])
            return {"id": plan.id, "status": plan.status, "expected_changes": plan.expected_changes}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/plans/{plan_id}")
    def plan_detail(plan_id: int):
        try:
            return service.plan_detail(plan_id)
        except KeyError as exc:
            raise HTTPException(404, "plan not found") from exc

    @app.post("/api/plans/{plan_id}/freeze")
    def freeze(plan_id: int):
        try:
            plan = service.freeze_plan(plan_id)
            return {"id": plan.id, "status": plan.status}
        except KeyError as exc:
            raise HTTPException(404, "plan not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


    @app.post("/api/plans/{plan_id}/validate")
    def validate(plan_id: int):
        try:
            return service.validate_plan(plan_id)
        except KeyError as exc:
            raise HTTPException(404, "plan not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/plans/{plan_id}/execute")
    def execute(plan_id: int):
        try:
            return service.execute_plan(plan_id)
        except KeyError as exc:
            raise HTTPException(404, "plan not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return app


app = create_app()
