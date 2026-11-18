"""Synthetic archive channel preflight tests: no NAS, task, or output writes."""
from __future__ import annotations

from types import SimpleNamespace
import zipfile

from fastapi import HTTPException
import pytest
from fastapi.testclient import TestClient

from app.archive_recovery import router as recovery_router
from app.config import Settings
from app.main import create_app
from app.models import WorkJob


@pytest.mark.parametrize("channel_ready", [False, True])
def test_preflight_reports_api_side_tmpfs_readiness(tmp_path, monkeypatch, channel_ready):
    archive = tmp_path / "harmless.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("example.txt", "demo")
    monkeypatch.setattr(recovery_router, "qualified_source", lambda request, raw: archive)
    monkeypatch.setattr(recovery_router, "tmpfs_available", lambda: channel_ready)
    request = SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(allow_mutation=True))
    ))
    outcome = recovery_router.check_archive(request, recovery_router.RecoveryRequest(source=str(archive)))
    assert outcome["format"] == "zip"
    assert outcome["password_channel_available"] is channel_ready
    assert outcome["mutation_enabled"] is True
    assert outcome["worker_write_check_required"] is True
    assert outcome["dependency_available"] is True


def test_password_start_blocks_before_creating_output_or_job(tmp_path, monkeypatch):
    archive = tmp_path / "protected.7z"
    archive.write_bytes(b"synthetic")
    monkeypatch.setattr(recovery_router, "qualified_source", lambda request, raw: archive)
    monkeypatch.setattr(recovery_router, "detect_format", lambda source: "7z")
    monkeypatch.setattr(recovery_router, "tmpfs_available", lambda: False)
    request = SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(allow_mutation=True))
    ))
    with pytest.raises(HTTPException) as error:
        recovery_router.start_archive(request, recovery_router.RecoveryRequest(
            source=str(archive), password="synthetic-do-not-store"))
    assert error.value.status_code == 503
    assert str(error.value.detail).startswith("PASSWORD_CHANNEL_UNAVAILABLE")
    assert "synthetic-do-not-store" not in str(error.value.detail)
    assert list(tmp_path.iterdir()) == [archive]

def test_start_enqueues_without_creating_media_directory_in_api(tmp_path):
    archive = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("example.txt", "worker-created-output")
    config = tmp_path / "config"
    config.mkdir()
    trash = tmp_path / ".trash"
    trash.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=tmp_path,
        allowed_roots_raw=str(tmp_path),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
    )
    app = create_app(settings)
    client = TestClient(app)
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200

    response = client.post(
        "/api/archive-recovery/start",
        json={"source": str(archive), "deep": False},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    output = Path(body["output"])
    assert output.parent == archive.parent
    assert not output.exists()

    with app.state.service.SessionLocal() as session:
        job = session.get(WorkJob, body["work_job_id"])
        assert job is not None
        assert job.kind == "archive-recovery"
        state = __import__("json").loads(job.state_json)
        parent_stat = archive.parent.stat()
        assert state["parent_identity"] == [str(parent_stat.st_dev), str(parent_stat.st_ino)]
        assert state["source"] == str(archive)
        assert state["output"] == str(output)
        assert "output_identity" not in state
