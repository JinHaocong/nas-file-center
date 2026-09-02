from __future__ import annotations

from pathlib import Path
import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.batch.rename import RenameRule


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "draft": "草稿",
    "frozen": "已冻结",
    "validating": "校验中",
    "ready": "可执行",
    "partial": "部分完成",
    "executing": "执行中",
    "planned": "计划中",
    "validated": "已校验",
    "skipped": "已跳过",
}

STATUS_CLASSES = {
    "queued": "bg-secondary",
    "running": "bg-primary",
    "completed": "bg-success",
    "ready": "bg-success",
    "failed": "bg-danger",
    "partial": "bg-warning text-dark",
    "draft": "bg-secondary",
    "frozen": "bg-info text-dark",
    "validating": "bg-primary",
    "executing": "bg-primary",
    "planned": "bg-secondary",
    "validated": "bg-success",
    "skipped": "bg-warning text-dark",
}

POLICY_LABELS = {
    "balanced-roots": "多根目录均衡保留",
    "keep-newest": "保留最新文件",
    "keep-oldest": "保留最旧文件",
    "keep-first-root": "优先保留第一个根目录",
    "path-priority": "按完整路径优先级",
    "relative-path-preference": "按相对路径优先级",
}


def _status_zh(value: str | None) -> str:
    return STATUS_LABELS.get(value or "", value or "-")


def _status_class(value: str | None) -> str:
    return STATUS_CLASSES.get(value or "", "bg-secondary")


def _format_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size):,} {unit}"
            return f"{size:,.2f} {unit}"
        size /= 1024
    return f"{int(value or 0):,} B"


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _render(request: Request, template: str, **context):
    settings = request.app.state.settings
    base = {
        "request": request,
        "settings": settings,
        "safe_mode": not settings.allow_mutation,
        "status_zh": _status_zh,
        "status_class": _status_class,
        "format_bytes": _format_bytes,
        "policy_labels": POLICY_LABELS,
    }
    base.update(context)
    return templates.TemplateResponse(request=request, name=template, context=base)


def _redirect(url: str, message: str | None = None) -> RedirectResponse:
    if message:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}message={message}"
    return RedirectResponse(url=url, status_code=303)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    service = request.app.state.service
    return _render(
        request,
        "dashboard.html",
        active="dashboard",
        summary=service.dashboard_summary(),
        scans=service.list_scans(limit=6),
        jobs=service.list_work_jobs(limit=6),
    )


@router.get("/ui/scans", response_class=HTMLResponse)
def scans_page(request: Request):
    return _render(
        request,
        "scans.html",
        active="scans",
        scans=request.app.state.service.list_scans(limit=100),
    )


@router.post("/ui/scans")
def create_scan_ui(
    request: Request,
    name: str = Form(...),
    roots_text: str = Form(...),
    isolate: str | None = Form(None),
    min_size: str = Form(""),
    name_patterns_text: str = Form(""),
    exclude_patterns_text: str = Form(""),
):
    roots = _split_lines(roots_text)
    try:
        result = request.app.state.service.enqueue_scan(
            name=name.strip(),
            roots=roots,
            isolate=isolate is not None,
            min_size=min_size.strip() or None,
            name_patterns=_split_lines(name_patterns_text) or None,
            exclude_patterns=_split_lines(exclude_patterns_text) or None,
        )
    except (ValueError, OSError) as exc:
        return _render(
            request,
            "scans.html",
            active="scans",
            scans=request.app.state.service.list_scans(limit=100),
            error=str(exc),
            form={"name": name, "roots_text": roots_text},
        )
    return _redirect(f"/ui/scans/{result['scan_job_id']}")


@router.get("/ui/scans/{scan_job_id}", response_class=HTMLResponse)
def scan_detail_ui(request: Request, scan_job_id: int):
    service = request.app.state.service
    try:
        scan = service.scan_detail(scan_job_id)
        groups = service.scan_groups(scan_job_id, limit=200) if scan["status"] == "completed" else []
    except KeyError as exc:
        raise HTTPException(404, "扫描任务不存在") from exc
    return _render(
        request,
        "scan_detail.html",
        active="scans",
        scan=scan,
        groups=groups,
        auto_refresh=scan["status"] in {"queued", "running"},
    )


@router.post("/ui/scans/{scan_job_id}/dedupe-plan")
def create_dedupe_plan_ui(
    request: Request,
    scan_job_id: int,
    policy: str = Form("balanced-roots"),
    path_priority_text: str = Form(""),
    relative_path_priority_text: str = Form(""),
):
    try:
        plan = request.app.state.service.create_dedupe_plan(
            scan_job_id,
            policy=policy,
            path_priority_patterns=_split_lines(path_priority_text) or None,
            relative_path_priority_patterns=_split_lines(relative_path_priority_text) or None,
        )
    except KeyError as exc:
        raise HTTPException(404, "扫描任务不存在") from exc
    except ValueError as exc:
        return _redirect(f"/ui/scans/{scan_job_id}", f"无法生成计划：{exc}")
    return _redirect(f"/ui/plans/{plan['id']}")


@router.get("/ui/indexes", response_class=HTMLResponse)
def indexes_page(request: Request):
    return _render(
        request,
        "indexes.html",
        active="indexes",
        roots=request.app.state.service.list_index_roots(limit=200),
    )


@router.post("/ui/indexes")
def create_index_ui(request: Request, root: str = Form(...)):
    try:
        result = request.app.state.service.enqueue_index(root.strip())
    except (ValueError, OSError) as exc:
        return _render(
            request,
            "indexes.html",
            active="indexes",
            roots=request.app.state.service.list_index_roots(limit=200),
            error=str(exc),
        )
    return _redirect("/ui/jobs", f"索引任务 #{result['work_job_id']} 已加入队列")


@router.get("/ui/path-match", response_class=HTMLResponse)
def path_match_page(request: Request):
    return _render(request, "path_match.html", active="path-match", groups=None)


@router.post("/ui/path-match", response_class=HTMLResponse)
def path_match_preview_ui(
    request: Request,
    roots_text: str = Form(...),
    mode: str = Form("relative-path"),
    normalize_pattern: str = Form(""),
    normalize_replacement: str = Form(""),
):
    roots = _split_lines(roots_text)
    try:
        groups = request.app.state.service.path_match_preview(
            roots,
            mode=mode,
            normalize_pattern=normalize_pattern or None,
            normalize_replacement=normalize_replacement,
        )
    except (ValueError, OSError) as exc:
        return _render(request, "path_match.html", active="path-match", groups=None, error=str(exc))
    return _render(
        request,
        "path_match.html",
        active="path-match",
        groups=groups,
        roots_text=roots_text,
        mode=mode,
        normalize_pattern=normalize_pattern,
        normalize_replacement=normalize_replacement,
    )


@router.get("/ui/rename", response_class=HTMLResponse)
def rename_page(request: Request):
    return _render(request, "rename.html", active="rename", items=None)


@router.post("/ui/rename", response_class=HTMLResponse)
def rename_preview_ui(
    request: Request,
    paths_text: str = Form(...),
    regex_pattern: str = Form(""),
    regex_replacement: str = Form(""),
    prefix: str = Form(""),
    suffix: str = Form(""),
    number_start: str = Form(""),
    number_width: int = Form(3),
    include_parent: str | None = Form(None),
):
    paths = _split_lines(paths_text)
    rule = RenameRule(
        regex_pattern=regex_pattern or None,
        regex_replacement=regex_replacement,
        prefix=prefix,
        suffix=suffix,
        number_start=int(number_start) if number_start.strip() else None,
        number_width=number_width,
        include_parent=include_parent is not None,
    )
    try:
        items = request.app.state.service.rename_preview(paths, rule)
    except (ValueError, OSError) as exc:
        return _render(request, "rename.html", active="rename", items=None, error=str(exc))
    return _render(
        request,
        "rename.html",
        active="rename",
        items=items,
        form={
            "paths_text": paths_text,
            "regex_pattern": regex_pattern,
            "regex_replacement": regex_replacement,
            "prefix": prefix,
            "suffix": suffix,
            "number_start": number_start,
            "number_width": number_width,
            "include_parent": include_parent is not None,
        },
    )


@router.post("/ui/rename/plan")
def rename_plan_ui(
    request: Request,
    paths_text: str = Form(...),
    regex_pattern: str = Form(""),
    regex_replacement: str = Form(""),
    prefix: str = Form(""),
    suffix: str = Form(""),
    number_start: str = Form(""),
    number_width: int = Form(3),
    include_parent: str | None = Form(None),
):
    rule = RenameRule(
        regex_pattern=regex_pattern or None,
        regex_replacement=regex_replacement,
        prefix=prefix,
        suffix=suffix,
        number_start=int(number_start) if number_start.strip() else None,
        number_width=number_width,
        include_parent=include_parent is not None,
    )
    try:
        proposals = request.app.state.service.rename_preview(_split_lines(paths_text), rule)
        plan = request.app.state.service.create_plan(
            name="批量重命名",
            kind="rename",
            items=[{"operation": "rename", "source": item["source"], "target": item["target"]} for item in proposals],
        )
    except (ValueError, OSError) as exc:
        return _redirect("/ui/rename", f"无法生成重命名计划：{exc}")
    return _redirect(f"/ui/plans/{plan.id}")


@router.get("/ui/organizer", response_class=HTMLResponse)
def organizer_page(request: Request):
    return _render(request, "organizer.html", active="organizer", items=None)


@router.post("/ui/organizer", response_class=HTMLResponse)
def organizer_preview_ui(request: Request, root: str = Form(...)):
    try:
        items = request.app.state.service.shaonv_preview(root.strip())
    except (ValueError, OSError) as exc:
        return _render(request, "organizer.html", active="organizer", items=None, error=str(exc), root=root)
    return _render(request, "organizer.html", active="organizer", items=items, root=root)


@router.post("/ui/organizer/plan")
def organizer_plan_ui(request: Request, root: str = Form(...)):
    try:
        proposals = request.app.state.service.shaonv_preview(root.strip())
        plan = request.app.state.service.create_plan(
            name="少女映画目录统计重命名",
            kind="organizer-shaonv",
            items=[{"operation": "rename", "source": item["source"], "target": item["target"]} for item in proposals],
        )
    except (ValueError, OSError) as exc:
        return _redirect("/ui/organizer", f"无法生成整理计划：{exc}")
    return _redirect(f"/ui/plans/{plan.id}")


@router.get("/ui/batch", response_class=HTMLResponse)
def batch_page(request: Request):
    return _render(request, "batch.html", active="batch")


@router.post("/ui/batch/plan")
def batch_plan_ui(
    request: Request,
    name: str = Form("批量处理"),
    operation: str = Form(...),
    paths_text: str = Form(""),
    mappings_text: str = Form(""),
):
    items: list[dict] = []
    try:
        if operation in {"touch", "quarantine"}:
            items = [{"operation": operation, "source": path} for path in _split_lines(paths_text)]
        elif operation in {"move", "rename"}:
            for line in _split_lines(mappings_text):
                if "->" not in line:
                    raise ValueError(f"映射缺少 ->：{line}")
                source, target = [part.strip() for part in line.split("->", 1)]
                if not source or not target:
                    raise ValueError(f"无效映射：{line}")
                items.append({"operation": operation, "source": source, "target": target})
        else:
            raise ValueError("不支持的批处理操作")
        if not items:
            raise ValueError("至少需要一个文件或目录")
        plan = request.app.state.service.create_plan(name=name.strip() or "批量处理", kind=f"batch-{operation}", items=items)
    except (ValueError, OSError) as exc:
        return _render(request, "batch.html", active="batch", error=str(exc))
    return _redirect(f"/ui/plans/{plan.id}")


@router.get("/ui/plans", response_class=HTMLResponse)
def plans_page(request: Request):
    return _render(
        request,
        "plans.html",
        active="plans",
        plans=request.app.state.service.list_plans(limit=200),
    )


@router.get("/ui/plans/{plan_id}", response_class=HTMLResponse)
def plan_detail_ui(request: Request, plan_id: int):
    try:
        plan = request.app.state.service.plan_detail(plan_id)
    except KeyError as exc:
        raise HTTPException(404, "计划不存在") from exc
    return _render(request, "plan_detail.html", active="plans", plan=plan)


@router.post("/ui/plans/{plan_id}/freeze")
def freeze_plan_ui(request: Request, plan_id: int):
    try:
        request.app.state.service.freeze_plan(plan_id)
        return _redirect(f"/ui/plans/{plan_id}", "计划已冻结")
    except (KeyError, ValueError) as exc:
        return _redirect(f"/ui/plans/{plan_id}", str(exc))


@router.post("/ui/plans/{plan_id}/validate")
def validate_plan_ui(request: Request, plan_id: int):
    try:
        request.app.state.service.validate_plan(plan_id)
        return _redirect(f"/ui/plans/{plan_id}", "SHA256/元数据校验完成")
    except (KeyError, ValueError) as exc:
        return _redirect(f"/ui/plans/{plan_id}", str(exc))


@router.post("/ui/plans/{plan_id}/execute")
def execute_plan_ui(request: Request, plan_id: int):
    if not request.app.state.settings.allow_mutation:
        return _redirect(f"/ui/plans/{plan_id}", "当前是只读安全模式，已阻止执行")
    try:
        request.app.state.service.execute_plan(plan_id)
        return _redirect(f"/ui/plans/{plan_id}", "执行完成，请检查结果")
    except (KeyError, ValueError) as exc:
        return _redirect(f"/ui/plans/{plan_id}", str(exc))


@router.get("/ui/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    jobs = request.app.state.service.list_work_jobs(limit=200)
    return _render(
        request,
        "jobs.html",
        active="jobs",
        jobs=jobs,
        auto_refresh=any(job["status"] in {"queued", "running"} for job in jobs),
    )


@router.get("/ui/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    return _render(
        request,
        "audit.html",
        active="audit",
        events=request.app.state.service.list_audit_events(limit=300),
    )


@router.get("/ui/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return _render(request, "settings.html", active="settings")
