"""TDD: admin-confirmed, fail-closed, single-unit execution integration."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.batch.media_organizer_execute_jobs import (
    approval_token, recovery_token,
)
from app.config import Settings
from app.db import create_engine_and_session
from app.main import create_app
from app.tasks.recovery import acquire_worker_ownership
from app.worker import process_work_job


def setup(tmp_path, *, enabled=False, mutation=True, deletion=True):
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        MEDIA_ORGANIZER_EXECUTION_ENABLED=enabled,
        ALLOW_MUTATION=mutation, ALLOW_DELETE=deletion,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    work = data / "archive" / "Collection" / "NO.001"
    work.mkdir(parents=True)
    (work / "photo.jpg").write_bytes(b"photo-1")
    (work / "clip.mp4").write_bytes(b"video-1")
    return client, settings, work


def preview(client, settings, work):
    selection = work.parent
    created = client.post("/api/media-organizer/previews", json={
        "selection": str(selection),
    })
    assert created.status_code == 200, created.text
    pid = created.json()["job_id"]
    assert process_work_job(settings, pid)
    report = client.get(f"/api/media-organizer/previews/{pid}")
    assert report.status_code == 200
    assert report.json()["summary"]["ready_count"] >= 1
    assert any(row["unit"] == str(work) and row["status"] == "ready"
               for row in report.json()["units"])
    return pid


def execute_request(client, pid, work, confirmation=None):
    return client.post(f"/api/media-organizer/previews/{pid}/execute", json={
        "unit": str(work),
        "confirmation": confirmation if confirmation is not None
        else approval_token(pid, str(work)),
    })


def worker(settings, job_id, *, name="test-execution-owner"):
    engine, factory = create_engine_and_session(settings.database_path)
    assert acquire_worker_ownership(engine, factory, worker_id=name)
    return process_work_job(settings, job_id, session_factory=factory,
                            engine=engine, worker_id=name)


def test_mode_has_a_second_default_off_mutation_switch(tmp_path):
    client, settings, work = setup(tmp_path)
    assert settings.media_organizer_execution_enabled is False
    pid = preview(client, settings, work)
    response = execute_request(client, pid, work)
    assert response.status_code == 409
    assert (work / "photo.jpg").read_bytes() == b"photo-1"


@pytest.mark.parametrize("mutation,deletion", [(False, True), (True, False)])
def test_both_existing_mutation_gates_remain_mandatory(tmp_path, mutation, deletion):
    client, settings, work = setup(tmp_path, enabled=True, mutation=mutation, deletion=deletion)
    pid = preview(client, settings, work)
    assert execute_request(client, pid, work).status_code == 409
    assert (work / "photo.jpg").exists()


def test_exact_unit_bound_token_required_and_duplicate_request_is_idempotent(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    assert execute_request(client, pid, work, "invalid").status_code == 409
    assert execute_request(client, pid, work,
                           approval_token(pid, str(work.parent))).status_code == 409
    first = execute_request(client, pid, work)
    assert first.status_code == 200, first.text
    second = execute_request(client, pid, work)
    assert second.status_code == 200, second.text
    assert second.json()["job_id"] == first.json()["job_id"]


def test_execute_is_never_queued_for_unit_not_in_original_preview(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    other = work.parent / "NO.002"
    other.mkdir()
    (other / "photo.jpg").write_bytes(b"other")
    response = execute_request(client, pid, other)
    assert response.status_code == 409
    assert (other / "photo.jpg").exists()


def test_admin_authentication_and_request_schema_cannot_be_bypassed(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    path = f"/api/media-organizer/previews/{pid}/execute"
    assert client.post(path, json={
        "unit": str(work),
        "confirmation": approval_token(pid, str(work)),
        "skip_conflicts": True,
    }).status_code == 422
    client.cookies.clear()
    assert execute_request(client, pid, work).status_code == 401


def test_without_worker_lease_no_file_is_touched(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    assert process_work_job(settings, queued.json()["job_id"]) is False
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.mp4").read_bytes() == b"video-1"


def test_confirmed_worker_executes_only_selected_unit_then_second_scan_is_noop(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    sibling = work.parent / "NO.002"
    sibling.mkdir()
    (sibling / "untouched.jpg").write_bytes(b"untouched")
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    assert worker(settings, job_id)
    result = client.get(f"/api/media-organizer/executions/{job_id}")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    images = [p for folder in work.iterdir() if folder.is_dir()
              and folder.name.startswith("P [") for p in folder.glob("*.jpg")]
    videos = [p for folder in work.iterdir() if folder.is_dir()
              and folder.name.startswith("V [") for p in folder.glob("*.mp4")]
    assert [f.read_bytes() for f in images] == [b"photo-1"]
    assert [f.read_bytes() for f in videos] == [b"video-1"]
    assert (sibling / "untouched.jpg").read_bytes() == b"untouched"
    again = client.post("/api/media-organizer/previews", json={
        "selection": str(work.parent),
    })
    assert again.status_code == 200
    new_pid = again.json()["job_id"]
    assert process_work_job(settings, new_pid)
    rows = client.get(f"/api/media-organizer/previews/{new_pid}").json()["units"]
    selected = next(x for x in rows if x["unit"] == str(work))
    assert selected["status"] == "already_organized"
    assert selected["needed_moves"] == 0


def test_stale_file_after_preview_fails_before_any_move(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    (work / "photo.jpg").write_bytes(b"changed")
    assert worker(settings, queued.json()["job_id"]) is False
    assert (work / "photo.jpg").read_bytes() == b"changed"
    assert not any(x.name.startswith(".nfc-") for x in work.iterdir())


def test_explicit_recovery_reuses_frozen_manifest_after_stage_interruption(tmp_path, monkeypatch):
    from app.batch import media_organizer_execute_jobs as jobs
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    response = execute_request(client, pid, work)
    assert response.status_code == 200
    original_id = response.json()["job_id"]
    original = jobs.stage_frozen_sources

    def stop_after_staging(*args, **kwargs):
        result = original(*args, **kwargs)
        raise RuntimeError("synthetic stop after staging")

    monkeypatch.setattr(jobs, "stage_frozen_sources", stop_after_staging)
    assert worker(settings, original_id, name="first-owner") is False
    monkeypatch.setattr(jobs, "stage_frozen_sources", original)
    assert any(x.name.startswith(".nfc-media-organizer-stage-") for x in work.iterdir())
    path = f"/api/media-organizer/executions/{original_id}/recover"
    assert client.post(path, json={"confirmation": "invalid"}).status_code == 409
    approved = client.post(path, json={"confirmation": recovery_token(original_id)})
    assert approved.status_code == 200, approved.text
    recovered_id = approved.json()["job_id"]
    assert recovered_id != original_id
    # The original exclusive lease is still fresh; the same worker identity
    # can renew it, but an unrelated owner must never take over early.
    assert worker(settings, recovered_id, name="first-owner")
    assert client.get(f"/api/media-organizer/executions/{recovered_id}").json()["status"] == "completed"
    assert any(folder.name.startswith("P [") and list(folder.glob("*.jpg"))
               for folder in work.iterdir() if folder.is_dir())
    assert any(folder.name.startswith("V [") and list(folder.glob("*.mp4"))
               for folder in work.iterdir() if folder.is_dir())
