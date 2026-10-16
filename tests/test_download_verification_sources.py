"""Configurable AList/OpenList sources: API browsing, security and quick comparison."""
from __future__ import annotations

import io
import json
import os
import stat

import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.download_verification.sources import AListAPIClient, validate_source_url
from app.download_verification.webdav import WebDAVError
from app.download_verification.handler import DownloadVerificationHandler
from app.download_verification.models import DownloadVerificationRun
from app.models import WorkJob
from app.tasks.context import JobContext


class Response:
    status = 200
    headers = {"Content-Encoding": "identity"}

    def __init__(self, payload):
        self._body = io.BytesIO(json.dumps(payload).encode())

    def read(self, amount=-1):
        return self._body.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._body.close()


class FakeOpener:
    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def open(self, request, timeout=None):
        body = json.loads(request.data)
        self.calls.append((request.full_url, body))
        if request.full_url.endswith("/api/auth/login"):
            return Response({"code": 200, "data": {"token": "private-token"}})
        page = body["page"]
        items = self.entries.get(body["path"], [])
        start = (page - 1) * 200
        return Response({"code": 200, "data": {
            "total": len(items), "content": items[start:start + 200]}})


def entry(name, size=0, is_dir=False):
    return {"name": name, "size": size, "is_dir": is_dir}


def test_metadata_api_manifest_recursive_empty_and_pagination():
    opener = FakeOpener({"/": [entry("Movie", is_dir=True), entry("empty", is_dir=True)]
                         + [entry("x%03d.mp4" % i, size=i + 1) for i in range(201)],
                         "/Movie": [entry("01.mkv", 4096)],
                         "/empty": []})
    client = AListAPIClient(base_url="http://openlist:5244", opener=opener)
    manifest = client.manifest(())
    assert len(manifest) == 204
    assert manifest["Movie/01.mkv"]["size"] == 4096
    assert manifest["empty"]["kind"] == "directory"
    assert set(url for url, _ in opener.calls) == {"http://openlist:5244/api/fs/list"}
    assert [body["page"] for _, body in opener.calls if body["path"] == "/"] == [1, 2]


def test_metadata_api_rejects_duplicate_and_unproven_file_size():
    opener = FakeOpener({"/": [entry("a", 1), entry("a", 1)]})
    with pytest.raises(WebDAVError, match="DUPLICATE"):
        AListAPIClient(base_url="http://alist:5244", opener=opener).manifest(())
    opener = FakeOpener({"/": [{"name": "a", "is_dir": False}]})
    with pytest.raises(WebDAVError, match="SIZE_UNKNOWN"):
        AListAPIClient(base_url="http://alist:5244", opener=opener).manifest(())


@pytest.mark.parametrize("url", [
    "http://localhost:5244", "http://127.0.0.1:5244", "http://169.254.169.254",
    "http://external.example", "https://evil.example/path",
    "http://user:secret@openlist:5244", "ftp://openlist",
])
def test_source_url_restrictions(url):
    with pytest.raises(ValueError):
        validate_source_url(url)
    assert validate_source_url("http://alist:5244") == "http://alist:5244"
    assert validate_source_url("http://192.168.1.12:5244") == "http://192.168.1.12:5244"
    assert validate_source_url("https://cloud.example") == "https://cloud.example"


@pytest.fixture
def app_client(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    movies = data / "Movies"
    movies.mkdir()
    (movies / "movie.mkv").write_bytes(b"abcd")
    settings = Settings(_env_file=None, CONFIG_DIR=str(tmp_path / "config"),
        DATA_MOUNT=str(data), ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123")
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123"}).status_code == 200
        yield client, settings, movies


def test_source_crud_secret_redacted_and_metadata_job_queue(app_client):
    client, settings, movies = app_client
    forbidden = client.post("/api/download-verifications/sources",
        json={"name": "unsafe", "provider": "openlist", "base_url": "http://localhost:5244"})
    assert forbidden.status_code == 422
    response = client.post("/api/download-verifications/sources", json={
        "name": "家里的 OpenList", "provider": "openlist",
        "base_url": "http://openlist:5244", "username": "readonly",
        "password": "highly-secret",
    })
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["base_url"] == "http://openlist:5244"
    assert source["has_password"] is True
    assert "highly-secret" not in str(source)
    secret_dir = settings.config_dir / "download-verification-secrets"
    secret_files = list(secret_dir.glob("source-*.secret"))
    assert len(secret_files) == 1
    assert stat.S_IMODE(secret_files[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o700
    browse_list = client.get("/api/download-verifications/sources").json()["items"]
    assert len(browse_list) == 1
    assert "password" not in str(browse_list)

    response = client.post("/api/download-verifications", json={
        "source_id": source["id"], "mode": "metadata",
        "remote_root": "PikPak/Movies", "local_root": str(movies),
    })
    assert response.status_code == 202, response.text
    detail = client.get("/api/download-verifications/" + str(response.json()["id"])).json()
    assert detail["mode"] == "metadata"
    assert detail["source_id"] == source["id"]
    with client.app.state.service.SessionLocal() as session:
        job = session.get(WorkJob, response.json()["work_job_id"])
        assert "highly-secret" not in job.state_json
        run = session.get(DownloadVerificationRun, detail["id"])
        assert run.source_revision == 1
    updated = client.put("/api/download-verifications/sources/" + str(source["id"]),
        json={"name": "家里的 OpenList v2"})
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert client.delete("/api/download-verifications/sources/" + str(source["id"])).status_code == 200
    assert client.get("/api/download-verifications/sources").json()["items"] == []


def test_metadata_worker_does_not_read_payloads(app_client, monkeypatch):
    client, settings, movies = app_client
    source = client.post("/api/download-verifications/sources", json={
        "name": "AList", "provider": "alist", "base_url": "http://alist:5244",
    }).json()
    queued = client.post("/api/download-verifications", json={
        "source_id": source["id"], "mode": "metadata",
        "remote_root": "", "local_root": str(movies),
    }).json()
    with client.app.state.service.SessionLocal() as session:
        job = session.get(WorkJob, queued["work_job_id"])
        job.status = "running"
        session.commit()

    class Remote:
        def manifest(self, parts, checkpoint=lambda: None):
            checkpoint()
            return {"movie.mkv": {"kind": "file", "size": 4, "etag": None, "mtime": None}}

        def sha256(self, *args, **kwargs):
            raise AssertionError("metadata mode must never hash")

    monkeypatch.setattr("app.download_verification.handler.source_client",
                        lambda source, settings, mode: Remote())
    ctx = JobContext(client.app.state.service.engine, client.app.state.service.SessionLocal,
                     job.id, worker_id=None)
    DownloadVerificationHandler().run(job, ctx, settings)
    with client.app.state.service.SessionLocal() as session:
        session.get(WorkJob, job.id).status = "completed"
        session.commit()
    detail = client.get("/api/download-verifications/" + str(queued["id"])).json()
    assert detail["result"] == "METADATA_IDENTICAL"
    items = client.get(f"/api/download-verifications/{queued['id']}/items").json()["items"]
    assert items[0]["status"] == "METADATA_MATCH"
    assert items[0]["remote_sha256"] is None
    assert (movies / "movie.mkv").read_bytes() == b"abcd"
