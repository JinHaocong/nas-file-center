from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.media_organizer.router import router


def test_admin_only_preview_and_guarded_execution_routes_are_registered():
    routes={(x.path,tuple(sorted(x.methods or []))) for x in router.routes}
    assert ('/api/media-organizer/previews',('POST',)) in routes
    assert ('/api/media-organizer/previews/{job_id}',('GET',)) in routes
    assert ('/api/media-organizer/previews/{job_id}/mappings/{mapping_id}',('GET',)) in routes
    assert ('/api/media-organizer/previews/{job_id}/execute', ('POST',)) in routes
    assert ('/api/media-organizer/executions/{job_id}/recover', ('POST',)) in routes


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
    # Exercise the actual HTTP boundary rather than inspecting internal
    # FastAPI router wrappers, which need not have a .path attribute.
    with TestClient(app) as client:
        resp = client.post("/api/media-organizer/previews",
                           json={"selection": str(data)})
        assert resp.status_code == 401
        query = client.get("/api/media-organizer/previews/17")
        assert query.status_code == 401


def test_full_mapping_route_is_admin_only_and_pages_the_requested_unit_map(monkeypatch):
    from app.batch import media_organizer_jobs as jobs

    calls = []

    def fake_mapping(session_factory, settings, job_id, mapping_id, *, page, page_size):
        calls.append((job_id, mapping_id, page, page_size))
        return {
            "job_id": job_id, "mapping_id": mapping_id,
            "page": page, "page_size": page_size, "total_moves": 51,
            "moves": [{"source": "/a.jpg", "target": "/001.jpg",
                       "target_name": "001.jpg", "kind": "P", "bytes": 1}],
            "read_only": True,
        }

    monkeypatch.setattr(jobs, "get_media_organizer_mapping", fake_mapping)
    app = FastAPI()
    app.include_router(router)
    app.state.service = type("Service", (), {"SessionLocal": object()})()
    app.state.settings = object()
    from app.auth.dependencies import require_admin_user
    app.dependency_overrides[require_admin_user] = lambda: None
    mapping_id = "a" * 64
    with TestClient(app) as client:
        response = client.get(
            f"/api/media-organizer/previews/9/mappings/{mapping_id}?page=2&page_size=25",
            headers={"origin": "http://testserver"},
        )
    assert response.status_code == 200
    assert response.json()["total_moves"] == 51
    assert calls == [(9, mapping_id, 2, 25)]
