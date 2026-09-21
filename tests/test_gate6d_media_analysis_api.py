from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.worker import process_work_job


def _client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="AdminPassword123!",
    )
    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login.status_code == 200
    return client, data, settings


def test_media_analysis_is_separate_from_generic_index_and_surfaces_corruption(tmp_path: Path):
    client, data, settings = _client(tmp_path)
    root = data / "photos"
    root.mkdir()

    healthy = root / "healthy.jpg"
    Image.new("RGB", (20, 10), (1, 2, 3)).save(healthy, format="JPEG")

    corrupt = root / "corrupt.jpg"
    Image.new("RGB", (30, 15), (4, 5, 6)).save(corrupt, format="JPEG")
    raw = corrupt.read_bytes()
    corrupt.write_bytes(raw[: max(32, len(raw) // 3)])

    index_response = client.post("/api/indexes", json={"root": str(root)})
    assert index_response.status_code == 200
    index_job = index_response.json()["work_job_id"]

    # A corrupt media payload is still a normal regular file for generic indexing.
    assert process_work_job(settings, index_job) is True
    index_job_detail = client.get(f"/api/work-jobs/{index_job}").json()
    assert index_job_detail["status"] == "completed"

    queued = client.post("/api/media/analyze", json={"root_keys": [str(root)]})
    assert queued.status_code == 200
    media_job = queued.json()["work_job_id"]
    assert client.get(f"/api/work-jobs/{media_job}").json()["kind"] == "media-analysis"

    assert process_work_job(settings, media_job) is True

    summary = client.get("/api/media/summary")
    assert summary.status_code == 200
    assert summary.json()["total"] == 2
    assert summary.json()["healthy"] == 1
    assert summary.json()["corrupt"] == 1

    corrupt_rows = client.get("/api/media?integrity_status=corrupt")
    assert corrupt_rows.status_code == 200
    body = corrupt_rows.json()
    assert body["total"] == 1
    assert body["items"][0]["basename"] == "corrupt.jpg"
    assert body["items"][0]["integrity_reason_code"] == "IMAGE_DECODE_FAILED"
    assert body["items"][0]["can_direct_delete"] is True


def test_media_analyze_rejects_nonindexed_root(tmp_path: Path):
    client, data, _settings = _client(tmp_path)
    root = data / "not-indexed"
    root.mkdir()

    response = client.post("/api/media/analyze", json={"root_keys": [str(root)]})
    assert response.status_code == 422
