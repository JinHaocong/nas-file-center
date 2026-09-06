import pytest
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import IndexRoot, IndexedPath, User
from app.auth.password import hash_password
from app.config import Settings
from fastapi.testclient import TestClient
from app.main import create_app
from app.service import FileCenterService

@pytest.fixture
def test_setup(tmp_path: Path):
    data = tmp_path / "data"
    media = data / "media"
    media.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=f"{data},{media}",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    # Seed IndexRoot and IndexedPaths
    with service.SessionLocal() as session:
        idx_root = IndexRoot(root=str(media), last_indexed_at=None)
        session.add(idx_root)

        paths = [
            IndexedPath(
                root_key=str(media),
                absolute_path=f"{media}/movie1.mkv",
                relative_path="movies/movie1.mkv",
                basename="movie1.mkv",
                stem="movie1",
                suffix=".mkv",
                size=4 * 1024 * 1024 * 1024,
                mtime_ns=1780000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key=str(media),
                absolute_path=f"{media}/photo.jpg",
                relative_path="photos/photo.jpg",
                basename="photo.jpg",
                stem="photo",
                suffix=".jpg",
                size=2 * 1024 * 1024,
                mtime_ns=1781000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key=str(media),
                absolute_path=f"{media}/.git/config",
                relative_path=".git/config",
                basename="config",
                stem="config",
                suffix="",
                size=100,
                mtime_ns=1782000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key=str(media),
                absolute_path=f"{media}/small.txt",
                relative_path="small.txt",
                basename="small.txt",
                stem="small",
                suffix=".txt",
                size=50,
                mtime_ns=1783000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
        ]
        session.add_all(paths)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    login_res = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_res.status_code == 200

    return client, str(media)

def test_preview_basic_filter_and_counts(test_setup):
    client, media_root = test_setup

    payload = {
        "roots": [media_root],
        "filter": {
            "op": "and",
            "children": [
                {"field": "size", "operator": "gte", "value": 1000}
            ]
        },
        "page": 1,
        "page_size": 50,
        "sort_by": "size",
        "sort_order": "desc"
    }
    resp = client.post("/api/filters/preview", json=payload, headers={"Origin": "http://testserver"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["preview_source"] == "index"
    assert data["live_filesystem_verified"] is False
    # .git/config is excluded by global exclude rules!
    # small.txt has size 50 < 1000, so excluded by filter!
    # Expected: movie1.mkv and photo.jpg
    assert data["matched_count"] == 2
    assert data["matched_bytes"] == (4 * 1024 * 1024 * 1024) + (2 * 1024 * 1024)
    assert len(data["items"]) == 2
    assert data["items"][0]["name"] == "movie1.mkv"
    assert data["items"][0]["media_type"] == "video"
    assert data["items"][1]["name"] == "photo.jpg"
    assert data["items"][1]["media_type"] == "image"

def test_preview_unindexed_root(test_setup):
    client, media_root = test_setup
    payload = {
        "roots": ["/data/nonexistent_root"],
        "page": 1,
        "page_size": 50,
    }
    resp = client.post("/api/filters/preview", json=payload, headers={"Origin": "http://testserver"})
    assert resp.status_code in {400, 404, 422}
    assert "not indexed" in resp.json()["detail"].lower() or "outside" in resp.json()["detail"].lower()

def test_preview_pagination(test_setup):
    client, media_root = test_setup
    payload = {
        "roots": [media_root],
        "page": 1,
        "page_size": 1,
        "sort_by": "size",
        "sort_order": "desc"
    }
    resp = client.post("/api/filters/preview", json=payload, headers={"Origin": "http://testserver"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["page_size"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "movie1.mkv"

    # Page 2
    payload["page"] = 2
    resp2 = client.post("/api/filters/preview", json=payload, headers={"Origin": "http://testserver"})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["items"]) == 1
    assert data2["items"][0]["name"] == "photo.jpg"
