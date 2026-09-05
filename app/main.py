from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import router as api_router
from app.auth.dependencies import get_current_user
from app.auth.rate_limiter import LoginRateLimiter
from app.auth.router import router as auth_router
from app.config import Settings, get_settings
from app.service import FileCenterService


def _sanitize_validation_errors(obj: Any) -> Any:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return str(obj)
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_validation_errors(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_validation_errors(v) for v in obj]
    if isinstance(obj, (int, str, bool, type(None))):
        return obj
    return str(obj)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    service = FileCenterService(settings)
    rate_limiter = LoginRateLimiter()

    # Disable default public docs/openapi URLs
    app = FastAPI(
        title="NAS File Center",
        version="0.3.3",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        sanitized = _sanitize_validation_errors(exc.errors())
        return JSONResponse(status_code=422, content={"detail": sanitized})
    app.state.settings = settings
    app.state.rate_limiter = rate_limiter

    # Public Health Endpoint
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "allow_mutation": settings.allow_mutation,
            "allow_delete": settings.allow_delete,
            "allowed_roots": [str(p) for p in settings.allowed_roots],
        }

    # Protected OpenAPI Endpoint (zero CDN, pure authenticated OpenAPI JSON)
    @app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(get_current_user)])
    async def get_open_api_endpoint():
        return JSONResponse(get_openapi(title=app.title, version=app.version, routes=app.routes))

    # Mount static assets if present
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Include Auth and API routers
    app.include_router(auth_router)
    app.include_router(api_router)

    # React Frontend SPA Hosting (TASK-031-03)
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if not frontend_dist.exists():
        # Check inside app/static/dist or frontend/public
        frontend_dist = static_dir / "dist"

    frontend_public = Path(__file__).resolve().parent.parent / "frontend" / "public"

    # Explicit Favicon and Icon Endpoints with strict media types (Blocker 9)
    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    async def get_favicon_ico():
        for candidate in [frontend_dist / "favicon.ico", frontend_public / "favicon.ico"]:
            if candidate.is_file():
                return FileResponse(candidate, media_type="image/x-icon")
        raise HTTPException(status_code=404, detail="favicon.ico not found")

    @app.api_route("/favicon.svg", methods=["GET", "HEAD"], include_in_schema=False)
    async def get_favicon_svg():
        for candidate in [frontend_dist / "favicon.svg", frontend_public / "favicon.svg"]:
            if candidate.is_file():
                return FileResponse(candidate, media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="favicon.svg not found")

    @app.api_route("/apple-touch-icon.png", methods=["GET", "HEAD"], include_in_schema=False)
    async def get_apple_touch_icon():
        for candidate in [frontend_dist / "apple-touch-icon.png", frontend_public / "apple-touch-icon.png"]:
            if candidate.is_file():
                return FileResponse(candidate, media_type="image/png")
        raise HTTPException(status_code=404, detail="apple-touch-icon.png not found")

    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.api_route("/", methods=["GET", "HEAD"])
        async def spa_root():
            index_file = frontend_dist / "index.html"
            if index_file.is_file():
                return FileResponse(index_file)
            raise HTTPException(status_code=404, detail="SPA index.html not found")

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
        async def spa_fallback(request: Request, full_path: str):
            # Never swallow /api/, /health, /docs, /openapi.json, /redoc, /ui/
            if full_path.startswith("api/") or full_path == "api":
                return JSONResponse({"error": "Not Found", "detail": f"Endpoint /{full_path} not found"}, status_code=404)
            if full_path in ("health", "docs", "openapi.json", "redoc") or full_path == "ui" or full_path.startswith("ui/"):
                raise HTTPException(status_code=404, detail="Not Found")

            if request.method not in ("GET", "HEAD"):
                raise HTTPException(status_code=404, detail="Not Found")

            target_file = frontend_dist / full_path
            if target_file.is_file():
                return FileResponse(target_file)

            index_file = frontend_dist / "index.html"
            if index_file.is_file():
                return FileResponse(index_file)
            raise HTTPException(status_code=404, detail="Not Found")

    return app


app = create_app()
