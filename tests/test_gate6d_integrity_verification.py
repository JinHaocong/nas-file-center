import os
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import MediaAsset
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
    return client, data, settings, app


def _index_and_analyze(client: TestClient, settings: Settings, root: Path) -> None:
    response = client.post("/api/indexes", json={"root": str(root)})
    assert response.status_code == 200
    assert process_work_job(settings, response.json()["work_job_id"]) is True

    response = client.post("/api/media/analyze", json={"root_keys": [str(root)]})
    assert response.status_code == 200
    assert process_work_job(settings, response.json()["work_job_id"]) is True


def _run_integrity(client: TestClient, settings: Settings, root: Path) -> int:
    queued = client.post("/api/media/integrity/verify", json={"root_keys": [str(root)]})
    assert queued.status_code == 200
    body = queued.json()
    assert body["status"] == "queued"
    assert body["root_keys"] == [str(root)]
    job_id = body["work_job_id"]
    assert client.get(f"/api/work-jobs/{job_id}").json()["kind"] == "media-integrity-verify"
    assert process_work_job(settings, job_id) is True
    return job_id


def test_integrity_verification_establishes_baseline_then_detects_same_metadata_hash_change(tmp_path: Path):
    client, data, settings, app = _client(tmp_path)
    root = data / "photos"
    root.mkdir()
    path = root / "photo.bmp"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(path, format="BMP")

    _index_and_analyze(client, settings, root)
    _run_integrity(client, settings, root)

    first = client.get("/api/media")
    assert first.status_code == 200
    item = first.json()["items"][0]
    assert item["verification_status"] == "baseline"
    assert item["verification_reason_code"] == "BASELINE_ESTABLISHED"
    assert item["verification_checked_at"] is not None

    with app.state.service.SessionLocal() as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        baseline = asset.verification_sha256
        assert isinstance(baseline, str) and len(baseline) == 64

    before = path.stat()
    payload = bytearray(path.read_bytes())
    offset = max(64, len(payload) // 2)
    payload[offset] ^= 0x01
    path.write_bytes(payload)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    after = path.stat()
    assert after.st_ino == before.st_ino
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns

    _run_integrity(client, settings, root)

    second = client.get("/api/media")
    item = second.json()["items"][0]
    assert item["verification_status"] == "changed"
    assert item["verification_reason_code"] == "SHA256_MISMATCH"

    with app.state.service.SessionLocal() as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert asset.verification_sha256 == baseline
        assert asset.verification_observed_sha256 != baseline

    summary = client.get("/api/media/summary")
    assert summary.status_code == 200
    assert summary.json()["verification_changed"] == 1


def test_integrity_verification_does_not_mint_baseline_for_index_identity_drift(tmp_path: Path):
    client, data, settings, app = _client(tmp_path)
    root = data / "photos"
    root.mkdir()
    path = root / "photo.png"
    Image.new("RGB", (10, 10), (1, 2, 3)).save(path, format="PNG")

    _index_and_analyze(client, settings, root)

    before = path.stat()
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    _run_integrity(client, settings, root)

    item = client.get("/api/media").json()["items"][0]
    assert item["verification_status"] == "unknown"
    assert item["verification_reason_code"] == "INDEX_IDENTITY_CHANGED"

    with app.state.service.SessionLocal() as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert asset.verification_sha256 is None


def test_integrity_verification_preserves_baseline_when_source_becomes_unavailable(tmp_path: Path):
    client, data, settings, app = _client(tmp_path)
    root = data / "photos"
    root.mkdir()
    path = root / "photo.bmp"
    Image.new("RGB", (12, 12), (7, 8, 9)).save(path, format="BMP")

    _index_and_analyze(client, settings, root)
    _run_integrity(client, settings, root)

    with app.state.service.SessionLocal() as session:
        baseline = session.scalar(select(MediaAsset.verification_sha256))
    assert baseline is not None

    path.unlink()
    _run_integrity(client, settings, root)

    item = client.get("/api/media").json()["items"][0]
    assert item["verification_status"] == "unknown"
    assert item["verification_reason_code"] == "SOURCE_UNAVAILABLE"

    with app.state.service.SessionLocal() as session:
        assert session.scalar(select(MediaAsset.verification_sha256)) == baseline


def test_integrity_verification_rejects_nonindexed_root(tmp_path: Path):
    client, data, _settings, _app = _client(tmp_path)
    root = data / "not-indexed"
    root.mkdir()

    response = client.post("/api/media/integrity/verify", json={"root_keys": [str(root)]})
    assert response.status_code == 422
