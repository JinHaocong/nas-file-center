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

def test_preview_media_type_in_and_nin_api(test_setup):
    client, media_root = test_setup

    # media_type IN ["video", "image"] -> 200 OK
    payload_in = {
        "roots": [media_root],
        "filter": {"field": "media_type", "operator": "in", "value": ["video", "image"]},
    }
    resp_in = client.post("/api/filters/preview", json=payload_in, headers={"Origin": "http://testserver"})
    assert resp_in.status_code == 200, resp_in.text
    assert resp_in.json()["matched_count"] == 2

    # media_type NIN ["video", "image"] -> 200 OK
    payload_nin = {
        "roots": [media_root],
        "filter": {"field": "media_type", "operator": "nin", "value": ["video", "image"]},
    }
    resp_nin = client.post("/api/filters/preview", json=payload_nin, headers={"Origin": "http://testserver"})
    assert resp_nin.status_code == 200, resp_nin.text
    # small.txt is document, so matches nin video/image
    assert resp_nin.json()["matched_count"] == 1
    assert resp_nin.json()["items"][0]["name"] == "small.txt"


def test_preview_fail_closed_validation_errors(test_setup):
    client, media_root = test_setup

    # 1. Top-level typo must return 422
    resp_typo = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filtter": {"field": "name", "operator": "eq", "value": "small.txt"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_typo.status_code == 422

    # 2. Leaf extra field must return 422
    resp_leaf_extra = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "name", "operator": "eq", "value": "small.txt", "extra_bad": 1}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_leaf_extra.status_code == 422

    # 3. mtime float must return 422
    resp_mtime_float = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": 1786795200.5}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_float.status_code == 422

    # 4. mtime naive ISO must return 422
    resp_mtime_naive = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": "2026-09-06T10:00:00"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_naive.status_code == 422

    # 5. non-string in list must return 422
    resp_non_str = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "name", "operator": "in", "value": [123]}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_non_str.status_code == 422

    # 6. P2-04: mtime integer 9223372037 exceeds SQLite INT64_MAX -> must return 422, NOT 500
    resp_mtime_overflow = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": 9223372037}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_overflow.status_code == 422, f"Expected 422, got {resp_mtime_overflow.status_code}: {resp_mtime_overflow.text}"

    # 7. P2-04: mtime ISO year 9999 exceeds INT64_MAX -> must return 422, NOT 500
    resp_mtime_9999 = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": "9999-12-31T23:59:59Z"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_9999.status_code == 422, f"Expected 422, got {resp_mtime_9999.status_code}: {resp_mtime_9999.text}"

    # 8. P2-04: mtime microsecond boundary overflow -> 2262-04-11T23:47:16.854776Z -> must return 422
    resp_mtime_us_overflow = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": "2262-04-11T23:47:16.854776Z"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_us_overflow.status_code == 422, f"Expected 422, got {resp_mtime_us_overflow.status_code}: {resp_mtime_us_overflow.text}"

    # 9. P2-04: safe mtime integer boundary 9223372036 -> must return 200
    resp_mtime_safe = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": 9223372036}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_safe.status_code == 200, f"Expected 200, got {resp_mtime_safe.status_code}: {resp_mtime_safe.text}"

    # 10. P2-04: safe mtime ISO boundary 2262-04-11T23:47:16.854775Z -> must return 200
    resp_mtime_iso_safe = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": "2262-04-11T23:47:16.854775Z"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_iso_safe.status_code == 200, f"Expected 200, got {resp_mtime_iso_safe.status_code}: {resp_mtime_iso_safe.text}"

    # 11. P2-04-hotfix3: mtime ISO timezone overflow 9999-12-31T23:59:59-12:00 -> must return 422, NOT 500
    resp_mtime_tz_overflow = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": "9999-12-31T23:59:59-12:00"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_tz_overflow.status_code == 422, f"Expected 422, got {resp_mtime_tz_overflow.status_code}: {resp_mtime_tz_overflow.text}"

    # 12. P2-04-hotfix3: mtime ISO timezone underflow 0001-01-01T00:00:00+14:00 -> must return 422, NOT 500
    resp_mtime_tz_underflow = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": "0001-01-01T00:00:00+14:00"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_tz_underflow.status_code == 422, f"Expected 422, got {resp_mtime_tz_underflow.status_code}: {resp_mtime_tz_underflow.text}"

    # 13. P2-04-hotfix3: safe mtime ISO with large positive offset 1970-01-01T14:00:00+14:00 (epoch 0) -> must return 200
    resp_mtime_tz_safe = client.post(
        "/api/filters/preview",
        json={"roots": [media_root], "filter": {"field": "mtime", "operator": "gte", "value": "1970-01-01T14:00:00+14:00"}},
        headers={"Origin": "http://testserver"},
    )
    assert resp_mtime_tz_safe.status_code == 200, f"Expected 200, got {resp_mtime_tz_safe.status_code}: {resp_mtime_tz_safe.text}"


