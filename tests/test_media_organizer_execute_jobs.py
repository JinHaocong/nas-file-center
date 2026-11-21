"""Admin-confirmed, fail-closed, single-unit execution integration.

Positive lifecycle tests explicitly request disposable synthetic custody.
They are protocol evidence, not production namespace or NAS acceptance.
"""
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


@pytest.fixture
def scoped_namespace(tmp_path, monkeypatch):
    """Grant only this test's tmp_path scope, with pytest-owned patch teardown."""
    # Import lazily: the issuer test module reuses the helpers below.
    from tests.test_media_organizer_grouped_worker_custody import _install_issuer

    return _install_issuer(monkeypatch, tmp_path, allowed=True)


def setup(tmp_path, *, enabled=False, mutation=True, deletion=True,
          namespace_quiescent=True):
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        MEDIA_ORGANIZER_EXECUTION_ENABLED=enabled,
        MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=namespace_quiescent,
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
    (work / "clip.png").write_bytes(b"image-2")
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
    result = process_work_job(settings, job_id, session_factory=factory,
                              engine=engine, worker_id=name)
    if not result:
        from app.models import WorkJob
        with factory() as session:
            job = session.get(WorkJob, job_id)
            print("WORKER_FAILURE_DIAGNOSTIC", job_id,
                  getattr(job, "error_code", None), getattr(job, "error_text", None))
    return result


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


def test_exact_unit_bound_token_required_and_duplicate_request_is_idempotent(tmp_path, scoped_namespace):
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


def test_execute_is_never_queued_for_unit_not_in_original_preview(tmp_path, scoped_namespace):
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


def test_without_worker_lease_no_file_is_touched(tmp_path, scoped_namespace):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    assert process_work_job(settings, queued.json()["job_id"]) is False
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.png").read_bytes() == b"image-2"


def test_confirmed_worker_publishes_only_one_unit_and_defers_manual_cleanup(tmp_path, scoped_namespace):
    client, settings, work = setup(tmp_path, enabled=True)
    sibling = work.parent / "NO.002"
    sibling.mkdir()
    (sibling / "untouched.jpg").write_bytes(b"untouched")
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    assert worker(settings, job_id)
    status = client.get(f"/api/media-organizer/executions/{job_id}")
    assert status.status_code == 200
    state = status.json()
    assert state["status"] == "completed"
    assert state["manual_cleanup_required"] is True
    assert state["finalized"] is False
    assert state["progress"]["phase"] == "manual_cleanup_required"
    # Only the flat pure-media path remains enabled during SEC-12 hold.
    assert sorted(p.read_bytes() for p in work.glob("00*.*")) == [
        b"image-2", b"photo-1",
    ]
    assert not any(p.name.startswith(("P [", "V ["))
                   for p in work.iterdir() if p.is_dir())
    assert (sibling / "untouched.jpg").read_bytes() == b"untouched"
    private = work / f".nfc-media-organizer-stage-{job_id}"
    assert private.is_dir()
    assert (private / ".nfc-stage-authority").is_file()
    assert any(private.glob("*.jpg"))
    record = (settings.reports_dir / "media_organizer-executions" /
              str(job_id) / "manifest.json.manual-cleanup.json")
    assert record.is_file()
    again = client.post("/api/media-organizer/previews", json={
        "selection": str(work.parent),
    })
    assert again.status_code == 200
    pid2 = again.json()["job_id"]
    assert process_work_job(settings, pid2)
    rows = client.get(f"/api/media-organizer/previews/{pid2}").json()["units"]
    selected = next(x for x in rows if x["unit"] == str(work))
    # Until a separate audited cleanup, the private stage is intentionally
    # preserved. A new preview must not falsely report zero changes.
    assert selected["status"] == "blocked"
    assert "workspace" in (selected.get("reason") or "").lower()


def test_stale_file_after_preview_fails_before_any_move(tmp_path, scoped_namespace):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    (work / "photo.jpg").write_bytes(b"changed")
    assert worker(settings, queued.json()["job_id"]) is False
    assert (work / "photo.jpg").read_bytes() == b"changed"
    assert not any(x.name.startswith(".nfc-") for x in work.iterdir())


def test_explicit_recovery_reuses_frozen_manifest_after_stage_interruption(tmp_path, monkeypatch, scoped_namespace):
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
    assert sorted(p.read_bytes() for p in work.glob("00*.*")) == [
        b"image-2", b"photo-1",
    ]


def test_recovery_after_deferred_cleanup_record_interruption_keeps_staging(
    tmp_path, monkeypatch, scoped_namespace,
):
    """Published-phase recovery only finishes its private manual-review record."""
    from app.batch import media_organizer_execute_jobs as jobs
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    submitted = execute_request(client, pid, work)
    assert submitted.status_code == 200
    original_id = submitted.json()["job_id"]
    actual = jobs.record_deferred_cleanup_evidence
    called = []

    def stop_before_record(*args, **kwargs):
        called.append(True)
        raise RuntimeError("synthetic report interruption")

    monkeypatch.setattr(jobs, "record_deferred_cleanup_evidence", stop_before_record)
    assert worker(settings, original_id, name="lease-owner") is False
    assert called
    monkeypatch.setattr(jobs, "record_deferred_cleanup_evidence", actual)
    original = client.get(f"/api/media-organizer/executions/{original_id}").json()
    assert original["status"] == "failed"
    assert original["progress"]["phase"] == "published"
    stage = work / f".nfc-media-organizer-stage-{original_id}"
    assert stage.is_dir() and (stage / ".nfc-stage-authority").is_file()
    recovery = client.post(
        f"/api/media-organizer/executions/{original_id}/recover",
        json={"confirmation": recovery_token(original_id)},
    )
    assert recovery.status_code == 200, recovery.text
    recovery_id = recovery.json()["job_id"]
    assert worker(settings, recovery_id, name="lease-owner")
    current = client.get(f"/api/media-organizer/executions/{recovery_id}").json()
    assert current["status"] == "completed"
    assert current["manual_cleanup_required"] is True
    assert stage.is_dir()
    assert sorted(p.read_bytes() for p in work.glob("00*.*")) == [
        b"image-2", b"photo-1",
    ]
    assert (settings.reports_dir / "media_organizer-executions" /
            str(original_id) / "manifest.json.manual-cleanup.json").is_file()


def test_preview_exposes_confirmation_only_to_enabled_admin_and_ready_unit(tmp_path, scoped_namespace):
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


def test_execution_worker_rechecks_independent_permission_switch(tmp_path, scoped_namespace):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    settings.media_organizer_execution_enabled = False
    assert worker(settings, queued.json()["job_id"], name="guarded-worker") is False
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.png").read_bytes() == b"image-2"
    assert not any(path.name.startswith(".nfc-") for path in work.iterdir())


def test_recovery_request_rejects_tampered_stage_ownership_witness(tmp_path, monkeypatch, scoped_namespace):
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


def test_assisted_recovery_confirmation_is_idempotent_after_success(tmp_path, monkeypatch, scoped_namespace):
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


def test_deferred_execution_never_reaches_last_marker_rmdir_gap(tmp_path, monkeypatch, scoped_namespace):
    """The production path does not call rmdir or remove stage owner markers."""
    from app.batch import media_organizer_retire as retirement
    from app.batch import media_organizer_execute_jobs as jobs
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    original_id = execute_request(client, pid, work).json()["job_id"]

    def forbidden(*args, **kwargs):
        raise AssertionError("retirement must not be invoked in deferred mode")

    monkeypatch.setattr(retirement, "_rmdir_bound_empty_stage", forbidden)
    assert worker(settings, original_id, name="safe-retain-worker")
    stage = work / f".nfc-media-organizer-stage-{original_id}"
    assert stage.is_dir()
    assert (stage / ".nfc-stage-complete").is_file()
    assert (stage / ".nfc-stage-authority").is_file()
    assert client.get(f"/api/media-organizer/executions/{original_id}").json()[
        "manual_cleanup_required"
    ] is True


def test_namespace_quiescence_ack_is_required_even_when_other_permission_gates_open(
    tmp_path,
):
    """A shared-writable namespace is never authorized for mutating cleanup."""
    client, settings, work = setup(
        tmp_path, enabled=True, mutation=True, deletion=True,
        namespace_quiescent=False,
    )
    assert settings.media_organizer_namespace_quiescence_ack is False
    pid = preview(client, settings, work)
    report = client.get(f"/api/media-organizer/previews/{pid}")
    assert report.status_code == 200
    assert report.json()["execution_enabled"] is False
    response = execute_request(client, pid, work)
    assert response.status_code == 409
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.png").read_bytes() == b"image-2"
    assert not any(x.name.startswith(".nfc-") for x in work.iterdir())


def test_worker_rechecks_quiescence_ack_after_job_was_queued(tmp_path, scoped_namespace):
    """A revoked namespace guarantee fails BEFORE staging any source."""
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    settings.media_organizer_namespace_quiescence_ack = False
    assert worker(settings, queued.json()["job_id"], name="quiescence-guard") is False
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.png").read_bytes() == b"image-2"
    assert not any(x.name.startswith(".nfc-") for x in work.iterdir())


def test_worker_requires_manual_cleanup_without_deleting_old_wrapper_or_stage(
    tmp_path, monkeypatch, scoped_namespace,
):
    """The production WorkJob must never call the legacy unsafe retirement."""
    from app.batch import media_organizer_publish as publishing
    from app.batch import media_organizer_execute_jobs as jobs
    client, settings, work = setup(tmp_path, enabled=True)
    (work / "P1").mkdir()
    (work / "P1" / "second.jpg").write_bytes(b"second-image")
    pid = preview(client, settings, work)
    planned = execute_request(client, pid, work)
    assert planned.status_code == 200, planned.text
    job_id = planned.json()["job_id"]

    def never_delete(*args, **kwargs):
        raise AssertionError("automatic directory retirement was invoked")

    monkeypatch.setattr(publishing, "_retire_wrappers", never_delete)
    assert worker(settings, job_id, name="manual-only-worker")
    result = client.get(f"/api/media-organizer/executions/{job_id}").json()
    assert result["status"] == "completed"
    assert result["manual_cleanup_required"] is True
    assert result["progress"]["phase"] == "manual_cleanup_required"
    assert result["finalized"] is False
    assert (work / "P1").is_dir()
    assert (work / "P1" / "second.jpg").read_bytes() == b"second-image"
    stage = work / f".nfc-media-organizer-stage-{job_id}"
    assert stage.is_dir()
    assert (stage / ".nfc-stage-authority").is_file()
    assert list(stage.glob("*.jpg"))
    report = settings.reports_dir / "media_organizer-executions" / str(job_id)
    assert (report / "manifest.json.manual-cleanup.json").is_file()
    assert len(list(work.glob("00*.jpg"))) >= 2
    assert (work / "photo.jpg").read_bytes() == b"photo-1"


def test_grouped_execute_request_blocks_before_queue_and_staging(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    (work / "movie.mp4").write_bytes(b"video-original")
    old = work / "P [1 7B]"
    old.mkdir()
    (old / "001.jpg").write_bytes(b"picture")
    pid = preview(client, settings, work)
    report = client.get(f"/api/media-organizer/previews/{pid}").json()
    assert str(work) not in report["confirmation_tokens"]
    refused = execute_request(client, pid, work)
    assert refused.status_code == 409
    assert "SEC-12" in refused.text
    assert (old / "001.jpg").read_bytes() == b"picture"
    assert (work / "movie.mp4").read_bytes() == b"video-original"
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.png").read_bytes() == b"image-2"
    assert not any(p.name.startswith(".nfc-") for p in work.iterdir())
