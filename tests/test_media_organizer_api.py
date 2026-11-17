from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.media_organizer.router import router


def test_admin_only_preview_routes_present_without_execute_route():
    routes={(x.path,tuple(sorted(x.methods or []))) for x in router.routes}
    assert ('/api/media-organizer/previews',('POST',)) in routes
    assert ('/api/media-organizer/previews/{job_id}',('GET',)) in routes
    assert not any('/execute' in path for path,_ in routes)


def test_preview_endpoint_passes_scope_through_without_mutation(tmp_path, monkeypatch):
    from app.batch import media_organizer_jobs as jobs
    called=[]
    def fake_enqueue(session_factory,settings,*,selection):
        called.append(selection)
        return {'job_id':5,'status':'queued'}
    monkeypatch.setattr(jobs,'enqueue_media_organizer_preview',fake_enqueue)
    app=FastAPI()
    app.include_router(router)
    app.state.service=type('Service',(),{'SessionLocal':object()})()
    app.state.settings=object()
    from app.auth.dependencies import require_admin_user
    app.dependency_overrides[require_admin_user]=lambda: None
    with TestClient(app) as client:
        res=client.post('/api/media-organizer/previews',json={'selection':str(tmp_path)},headers={'origin':'http://testserver'})
        assert res.status_code==200
        assert res.json()['job_id']==5
        assert called==[str(tmp_path)]


def test_main_app_registers_protected_preview_routes(tmp_path):
    from app.config import Settings
    from app.main import create_app
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    app = create_app(settings)
    # App-level registrations include non-route mounts without .path/.methods.
    # Only inspect actual HTTP routes rather than assuming every entry has them.
    assert any(getattr(r, "path", None) == "/api/media-organizer/previews"
               and "POST" in (getattr(r, "methods", None) or ())
               for r in app.routes)
    assert any(getattr(r, "path", None) == "/api/media-organizer/previews/{job_id}"
               and "GET" in (getattr(r, "methods", None) or ())
               for r in app.routes)
    with TestClient(app) as client:
        resp = client.post("/api/media-organizer/previews",
                           json={"selection": str(data)})
        assert resp.status_code == 401
