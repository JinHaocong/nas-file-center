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


def test_recovery_after_partial_retirement_never_restarts_staging(tmp_path, monkeypatch):
    """A published job must only continue its frozen retirement journal."""
    from app.batch import media_organizer_retire as retirement
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    response = execute_request(client, pid, work)
    assert response.status_code == 200
    original_id = response.json()["job_id"]
    original_unlink = retirement._retire_stage_link
    calls = 0

    def stop_during_retirement(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic crash after one staged link retired")
        return original_unlink(*args, **kwargs)

    monkeypatch.setattr(retirement, "_retire_stage_link", stop_during_retirement)
    assert worker(settings, original_id, name="lease-owner") is False
    monkeypatch.setattr(retirement, "_retire_stage_link", original_unlink)
    current = client.get(f"/api/media-organizer/executions/{original_id}").json()
    assert current["status"] == "failed"
    assert current["progress"]["phase"] == "published"
    confirmed = client.post(
        f"/api/media-organizer/executions/{original_id}/recover",
        json={"confirmation": recovery_token(original_id)},
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery_id = confirmed.json()["job_id"]
    assert worker(settings, recovery_id, name="lease-owner")
    assert client.get(f"/api/media-organizer/executions/{recovery_id}").json()["status"] == "completed"
    assert not any(p.name.startswith(".nfc-") for p in work.iterdir())
    second = client.post("/api/media-organizer/previews", json={
        "selection": str(work.parent),
    })
    assert second.status_code == 200
    assert process_work_job(settings, second.json()["job_id"])
    rows = client.get(f"/api/media-organizer/previews/{second.json()['job_id']}").json()["units"]
    assert any(x["unit"] == str(work) and x["status"] == "already_organized" for x in rows)


def test_preview_exposes_confirmation_only_to_enabled_admin_and_ready_unit(tmp_path):
    off_base = tmp_path / "disabled"
    off_base.mkdir()
    disabled, off_settings, off_work = setup(off_base, enabled=False)
    off_pid = preview(disabled, off_settings, off_work)
    off_body = disabled.get(f"/api/media-organizer/previews/{off_pid}").json()
    assert off_body["execution_enabled"] is False
    assert off_body["confirmation_tokens"] == {}

    on_base = tmp_path / "enabled"
    on_base.mkdir()
    enabled, on_settings, on_work = setup(on_base, enabled=True)
    on_pid = preview(enabled, on_settings, on_work)
    on_body = enabled.get(f"/api/media-organizer/previews/{on_pid}").json()
    assert on_body["execution_enabled"] is True
    assert on_body["confirmation_tokens"] == {
        str(on_work): approval_token(on_pid, str(on_work)),
    }
    enabled.cookies.clear()
    assert enabled.get(f"/api/media-organizer/previews/{on_pid}").status_code == 401


def test_execution_worker_rechecks_independent_permission_switch(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    settings.media_organizer_execution_enabled = False
    assert worker(settings, queued.json()["job_id"], name="guarded-worker") is False
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.mp4").read_bytes() == b"video-1"
    assert not any(path.name.startswith(".nfc-") for path in work.iterdir())


def test_recovery_request_rejects_tampered_stage_ownership_witness(tmp_path, monkeypatch):
    from app.batch import media_organizer_execute_jobs as jobs
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    original_job_id = queued.json()["job_id"]
    real_stage = jobs.stage_frozen_sources

    def interrupted_after_stage(*args, **kwargs):
        real_stage(*args, **kwargs)
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(jobs, "stage_frozen_sources", interrupted_after_stage)
    assert worker(settings, original_job_id, name="trusted-worker") is False
    monkeypatch.setattr(jobs, "stage_frozen_sources", real_stage)
    private = next(path for path in work.iterdir()
                   if path.name.startswith(".nfc-media-organizer-stage-"))
    (private / ".nfc-stage-authority").write_bytes(b"foreign-witness")
    response = client.post(
        f"/api/media-organizer/executions/{original_job_id}/recover",
        json={"confirmation": recovery_token(original_job_id)},
    )
    assert response.status_code == 409
    assert (private / ".nfc-stage-authority").read_bytes() == b"foreign-witness"


def test_assisted_recovery_confirmation_is_idempotent_after_success(tmp_path, monkeypatch):
    from app.batch import media_organizer_execute_jobs as jobs
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    first = execute_request(client, pid, work)
    assert first.status_code == 200
    original_job_id = first.json()["job_id"]
    real_stage = jobs.stage_frozen_sources

    def interrupted(*args, **kwargs):
        real_stage(*args, **kwargs)
        raise RuntimeError("synthetic stop")

    monkeypatch.setattr(jobs, "stage_frozen_sources", interrupted)
    assert worker(settings, original_job_id, name="same-owner") is False
    monkeypatch.setattr(jobs, "stage_frozen_sources", real_stage)
    path = f"/api/media-organizer/executions/{original_job_id}/recover"
    request = {"confirmation": recovery_token(original_job_id)}
    enqueued = client.post(path, json=request)
    assert enqueued.status_code == 200
    second_id = enqueued.json()["job_id"]
    assert worker(settings, second_id, name="same-owner")
    repeated = client.post(path, json=request)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["job_id"] == second_id
    assert repeated.json()["status"] == "completed"
