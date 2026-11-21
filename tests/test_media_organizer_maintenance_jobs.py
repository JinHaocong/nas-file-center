"""Exercise operator-confirmed maintenance windows with disposable media and real Workers.

These tests intentionally run without a synthetic namespace-custody issuer.
They prove the maintenance-window protocol, not strict OS-level exclusion.
"""
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.batch import media_organizer_execute_jobs as execute
from app.config import Settings
from app.main import create_app
from app.models import WorkJob
from app.tasks.context import JobContext
from app.worker import process_work_job
from tests.test_media_organizer_execute_jobs import preview, worker


def make_case(tmp_path, monkeypatch, *, shared=False):
    data, config = tmp_path / "data", tmp_path / "config"
    data.mkdir()
    config.mkdir(mode=0o700)
    if shared:
        monkeypatch.setenv("NFC_SHARED_CONFIG_GID", str(os.getegid()))
        config.chmod(0o2770)
    else:
        monkeypatch.delenv("NFC_SHARED_CONFIG_GID", raising=False)
    settings = Settings(
        _env_file=None, CONFIG_DIR=config, DATA_MOUNT=data, ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=data / ".trash", ALLOW_MUTATION=True, ALLOW_DELETE=True,
        MEDIA_ORGANIZER_EXECUTION_ENABLED=True, MEDIA_ORGANIZER_EXECUTION_MODE="maintenance_window",
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    unit = data / "collection" / "NO.001"
    (unit / "P1").mkdir(parents=True)
    for name in ("P1/cover.jpg", "portrait.jpg", "trailer.mp4"):
        (unit / name).write_bytes(name.encode())
    return client, settings, unit


def hashes(unit):
    return Counter(hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in unit.rglob("*") if p.suffix in (".jpg", ".mp4"))


def approved(client, path, **body):
    for ack, code in (({}, 409), ({"maintenance_window_confirmed": False}, 409),
                      ({"maintenance_window_confirmed": "true"}, 422)):
        rejected = client.post(path, json={**body, **ack})
        assert rejected.status_code == code, rejected.text
    response = client.post(path, json={**body, "maintenance_window_confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["assurance_level"] == "maintenance_window"
    assert response.json()["namespace_exclusive_custody_proven"] is False
    return response.json()["job_id"]


def deny_stage_reads(patch):
    original_open = os.open

    def guarded(path, *args, **kwargs):
        literal = Path(os.fsdecode(path))
        if not literal.is_absolute() and kwargs.get("dir_fd") is not None:
            literal = Path(os.readlink(f"/proc/self/fd/{kwargs['dir_fd']}")) / literal
        if any(part.startswith(".nfc-media-organizer-stage-") for part in literal.parts):
            raise AssertionError("API opened private Worker stage")
        return original_open(path, *args, **kwargs)

    patch.setattr(os, "open", guarded)
    def forbidden(*args, **kwargs):
        raise AssertionError("API attempted live inspection or read a private journal")
    for name in ("_validate_private_recovery_stage", "audit_deferred_cleanup_inventory",
                 "read_deferred_cleanup_review", "read_cleanup_plan"):
        patch.setattr(execute, name, forbidden)


def test_execution_mode_is_explicit_and_validated():
    assert Settings(_env_file=None).media_organizer_execution_mode == "strict"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, MEDIA_ORGANIZER_EXECUTION_MODE="maint")


@pytest.mark.parametrize("shared,interrupt", [(False, False), (True, True)])
def test_maintenance_approvals_reports_recovery_and_zero_rescan(tmp_path, monkeypatch, shared, interrupt):
    client, settings, unit = make_case(tmp_path, monkeypatch, shared=shared)
    before = hashes(unit)
    pid = preview(client, settings, unit)
    report = client.get(f"/api/media-organizer/previews/{pid}").json()
    assert report["requires_maintenance_window"] is True
    assert report["execution_mode"] == "maintenance_window"
    row = next(row for row in report["units"] if row["unit"] == str(unit))
    mapping = client.get(f"/api/media-organizer/previews/{pid}/mappings/{row['mapping_id']}")
    assert mapping.json()["execution_mode"] == "maintenance_window"
    confirmation = report["confirmation_tokens"][str(unit)]
    jid = approved(client, f"/api/media-organizer/previews/{pid}/execute",
                   unit=str(unit), confirmation=confirmation)
    original_id = jid
    if interrupt:
        actual = execute.publish_frozen_stage
        def crash(*args, **kwargs):
            actual(*args, **kwargs)
            raise RuntimeError("interrupted after publication")
        with monkeypatch.context() as patch:
            patch.setattr(execute, "publish_frozen_stage", crash)
            assert worker(settings, jid) is False
        with monkeypatch.context() as patch:
            deny_stage_reads(patch)
            jid = approved(client, f"/api/media-organizer/executions/{jid}/recover",
                           confirmation=execute.recovery_token(jid))
    assert worker(settings, jid)
    base = f"/api/media-organizer/executions/{jid}"
    frozen = settings.reports_dir / "media_organizer-executions" / str(original_id) / "manifest.json"
    manifest = json.loads(frozen.read_text())["manifest"]
    assert manifest["execution_mode"] == "maintenance_window"
    with monkeypatch.context() as patch:
        deny_stage_reads(patch)
        for suffix in ("cleanup-review", "cleanup-audit", "cleanup-plan"):
            result = client.get(f"{base}/{suffix}")
            assert result.status_code == 200, result.text
            assert result.json()["verification_scope"] == "worker_handoff_snapshot"
        cid = approved(client, f"{base}/cleanup", confirmation=result.json()["confirmation"])
    if interrupt:
        checkpoint = JobContext.checkpoint
        def after_scan(context, **kwargs):
            checkpoint(context, **kwargs)
            if kwargs.get("checkpoint_data", {}).get("phase") == "cleanup-scanned-zero":
                raise RuntimeError("interrupted after durable cleanup")
        with monkeypatch.context() as patch:
            patch.setattr(JobContext, "checkpoint", after_scan)
            assert worker(settings, cid) is False
        token = client.get(base).json()["cleanup"]["recovery_confirmation"]
        with monkeypatch.context() as patch:
            deny_stage_reads(patch)
            cid = approved(client, f"/api/media-organizer/cleanups/{cid}/recover", confirmation=token)
    assert worker(settings, cid)
    status = client.get(base).json()
    assert status["execution_mode"] == "maintenance_window" and status["finalized"]
    assert status["namespace_exclusive_custody_proven"] is False
    assert hashes(unit) == before
    assert not (unit / manifest["stage_directory"]).exists()
    scan = client.post("/api/media-organizer/previews", json={"selection": str(unit.parent)}).json()
    assert process_work_job(settings, scan["job_id"])
    row = client.get(f"/api/media-organizer/previews/{scan['job_id']}").json()["units"][0]
    assert row["status"] == "already_organized" and row["needed_moves"] == row["renamed_count"] == 0


def test_worker_permission_denied_before_freeze_no_unbound_recovery(tmp_path, monkeypatch):
    """NAS #31: refuse unsafe replay when Worker fails before first checkpoint."""
    from app.batch import media_organizer_authority as authority
    from sqlalchemy import select

    client, settings, unit = make_case(tmp_path, monkeypatch)
    original_hashes = hashes(unit)
    pid = preview(client, settings, unit)
    jid = approved(client, f"/api/media-organizer/previews/{pid}/execute",
                   unit=str(unit), confirmation=execute.approval_token(pid, str(unit)))

    def refuse_parent(self, parents, *, manifest=None):
        raise authority.MaintenanceWindowUnavailable(
            "maintenance parent is not writable by the Worker"
        )

    with monkeypatch.context() as patch:
        patch.setattr(authority.MaintenanceWindowSession, "assert_mutation_allowed", refuse_parent)
        assert worker(settings, jid) is False

    status_resp = client.get(f"/api/media-organizer/executions/{jid}")
    assert status_resp.status_code == 200
    status = status_resp.json()
    assert status["status"] == "failed"
    assert status["execution_mode"] == "maintenance_window"
    assert status["progress"]["phase"] is None
    assert status["recovery_available"] is False
    assert "冻结检查点" in status["recovery_unavailable_reason"]

    refused = client.post(f"/api/media-organizer/executions/{jid}/recover", json={
        "confirmation": execute.recovery_token(jid),
        "maintenance_window_confirmed": True,
    })
    assert refused.status_code == 409
    assert "no verified frozen checkpoint" in refused.json()["detail"]
    assert hashes(unit) == original_hashes
    assert not (unit / f".nfc-media-organizer-stage-{jid}").exists()

    with client.app.state.service.SessionLocal() as session:
        ids = session.scalars(select(WorkJob.id).where(
            WorkJob.kind == execute.EXECUTE_KIND,
        )).all()
        assert ids == [jid], "unverifiable replay cannot queue a new job"

    # A new read-only preview is a separate operation with fresh evidence.
    fresh = client.post("/api/media-organizer/previews", json={
        "selection": str(unit.parent),
    })
    assert fresh.status_code == 200


def test_mode_switch_or_edited_approval_cannot_authorize_queued_work(tmp_path, monkeypatch):
    client, settings, unit = make_case(tmp_path, monkeypatch)
    before = hashes(unit)
    pid = preview(client, settings, unit)
    body = {"unit": str(unit), "confirmation": execute.approval_token(pid, str(unit))}
    path = f"/api/media-organizer/previews/{pid}/execute"
    settings.media_organizer_execution_mode = "strict"
    settings.media_organizer_namespace_quiescence_ack = True
    assert client.post(path, json={**body, "maintenance_window_confirmed": True}).status_code == 409
    settings.media_organizer_execution_mode = "maintenance_window"
    jid = approved(client, path, **body)
    with client.app.state.service.SessionLocal() as session:
        job = session.get(WorkJob, jid)
        state = json.loads(job.state_json)
        state["maintenance_window_confirmed"] = False
        job.state_json = json.dumps(state)
        session.commit()
    assert worker(settings, jid) is False
    assert hashes(unit) == before
    assert not (settings.reports_dir / "media_organizer-executions" / str(jid)).exists()


def test_cleanup_of_recovered_publication_requires_original_approval(tmp_path, monkeypatch):
    client, settings, unit = make_case(tmp_path, monkeypatch)
    pid = preview(client, settings, unit)
    jid = approved(client, f"/api/media-organizer/previews/{pid}/execute", unit=str(unit),
                   confirmation=execute.approval_token(pid, str(unit)))
    def crash(*args, **kwargs):
        raise RuntimeError("simulated interruption before cleanup handoff")
    with monkeypatch.context() as patch:
        patch.setattr(execute, "record_deferred_cleanup_evidence", crash)
        assert worker(settings, jid) is False
    rid = approved(client, f"/api/media-organizer/executions/{jid}/recover",
                   confirmation=execute.recovery_token(jid))
    assert worker(settings, rid)
    base = f"/api/media-organizer/executions/{rid}"
    token = client.get(base + "/cleanup-plan").json()["confirmation"]
    with client.app.state.service.SessionLocal() as session:
        original = session.get(WorkJob, jid)
        state = json.loads(original.state_json)
        state["execution_mode"] = "strict"
        original.state_json = json.dumps(state)
        session.commit()
    response = client.post(base + "/cleanup", json={
        "confirmation": token, "maintenance_window_confirmed": True,
    })
    assert response.status_code == 409, response.text
    assert (unit / "P1/cover.jpg").is_file()


def test_active_window_holds_new_units_without_starving_cleanup(tmp_path, monkeypatch):
    client, settings, unit = make_case(tmp_path, monkeypatch)
    sibling = unit.parent / "NO.002"
    sibling.mkdir()
    (sibling / "other.jpg").write_bytes(b"other")
    pid = preview(client, settings, unit)
    jid = approved(client, f"/api/media-organizer/previews/{pid}/execute", unit=str(unit),
                   confirmation=execute.approval_token(pid, str(unit)))
    assert worker(settings, jid)
    foreign = {"confirmation": execute.approval_token(pid, str(sibling)), "unit": str(sibling),
               "maintenance_window_confirmed": True}
    enqueue = f"/api/media-organizer/previews/{pid}/execute"
    assert client.post(enqueue, json=foreign).status_code == 409
    base = f"/api/media-organizer/executions/{jid}"
    token = client.get(base + "/cleanup-plan").json()["confirmation"]
    cid = approved(client, base + "/cleanup", confirmation=token)
    assert worker(settings, cid)
    assert client.post(enqueue, json=foreign).status_code == 200


@pytest.mark.parametrize("damage", ["handoff-report", "checkpoint-plan"])
def test_cleanup_recovery_requires_unchanged_handoff_and_checkpoint(tmp_path, monkeypatch, damage):
    client, settings, unit = make_case(tmp_path, monkeypatch)
    pid = preview(client, settings, unit)
    jid = approved(client, f"/api/media-organizer/previews/{pid}/execute", unit=str(unit),
                   confirmation=execute.approval_token(pid, str(unit)))
    assert worker(settings, jid)
    base = f"/api/media-organizer/executions/{jid}"
    token = client.get(base + "/cleanup-plan").json()["confirmation"]
    cid = approved(client, base + "/cleanup", confirmation=token)
    with client.app.state.service.SessionLocal() as session:
        queued = session.get(WorkJob, cid)
        assert "维护窗口" in queued.progress_message and "独占" not in queued.progress_message
    from app.batch import media_organizer_cleanup_jobs as cleanup
    def crash(*args, **kwargs):
        raise RuntimeError("simulated interruption before cleanup")
    with monkeypatch.context() as patch:
        patch.setattr(cleanup, "finish_deferred_cleanup", crash)
        assert worker(settings, cid) is False
    with client.app.state.service.SessionLocal() as session:
        job = session.get(WorkJob, cid)
        checkpoint = json.loads(job.checkpoint_json)
        assert checkpoint["cleanup_job_id"] == cid
    if damage == "handoff-report":
        report = settings.reports_dir / "media_organizer-executions" / str(jid) / "manifest.json.manual-cleanup.json"
        report.write_text("{}")
    else:
        with client.app.state.service.SessionLocal() as session:
            job = session.get(WorkJob, cid)
            checkpoint = json.loads(job.checkpoint_json)
            checkpoint["plan_sha256"] = "0" * 64
            job.checkpoint_json = json.dumps(checkpoint)
            session.commit()
    token = client.get(base).json()["cleanup"]["recovery_confirmation"]
    response = client.post(f"/api/media-organizer/cleanups/{cid}/recover", json={
        "confirmation": token, "maintenance_window_confirmed": True,
    })
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("damage", [None, "unwitnessed-stage", "changed-source", "config-residue"])
def test_recover_after_frozen_checkpoint_before_mkdir(tmp_path, monkeypatch, damage):
    client, settings, unit = make_case(tmp_path, monkeypatch)
    before = hashes(unit)
    pid = preview(client, settings, unit)
    jid = approved(client, f"/api/media-organizer/previews/{pid}/execute",
                   unit=str(unit), confirmation=execute.approval_token(pid, str(unit)))
    save = JobContext.checkpoint

    def crash_after_freeze(context, **kwargs):
        save(context, **kwargs)
        if kwargs.get("checkpoint_data", {}).get("phase") == "frozen":
            raise RuntimeError("interruption after frozen checkpoint, before stage creation")

    with monkeypatch.context() as patch:
        patch.setattr(JobContext, "checkpoint", crash_after_freeze)
        assert worker(settings, jid) is False
    folder = settings.reports_dir / "media_organizer-executions" / str(jid)
    frozen_bytes = (folder / "manifest.json").read_bytes()
    stage = unit / json.loads(frozen_bytes)["manifest"]["stage_directory"]
    assert not stage.exists() and hashes(unit) == before
    if damage is None:
        from app.db import create_engine_and_session
        from app.tasks.recovery import claim_next_job
        engine, sessions = create_engine_and_session(settings.database_path)
        with sessions.begin() as session:
            foreign = WorkJob(kind="batch-plan-execute", status="queued", state_json="{}")
            session.add(foreign)
            session.flush()
            waiting_id = foreign.id
        assert claim_next_job(engine, sessions, worker_id="test-execution-owner") is None
    if damage == "unwitnessed-stage":
        stage.mkdir(mode=0o700)
    elif damage == "changed-source":
        (unit / "portrait.jpg").write_bytes(b"changed after freeze")
    elif damage == "config-residue":
        (folder / "unrecognized.tmp").write_bytes(b"unknown config evidence")
    with monkeypatch.context() as patch:
        deny_stage_reads(patch)
        rid = approved(client, f"/api/media-organizer/executions/{jid}/recover",
                       confirmation=execute.recovery_token(jid))
    if damage is not None:
        assert worker(settings, rid) is False
        if damage == "unwitnessed-stage":
            assert list(stage.iterdir()) == []
        else:
            assert not stage.exists()
        return
    assert worker(settings, rid)
    assert (folder / "manifest.json").read_bytes() == frozen_bytes
    base = f"/api/media-organizer/executions/{rid}"
    token = client.get(base + "/cleanup-plan").json()["confirmation"]
    cid = approved(client, base + "/cleanup", confirmation=token)
    assert worker(settings, cid)
    assert hashes(unit) == before and not stage.exists()
    assert client.get(base).json()["finalized"]
    assert claim_next_job(engine, sessions, worker_id="test-execution-owner") == waiting_id
    engine.dispose()


def test_queued_job_with_alternate_predecessor_is_refused(tmp_path, monkeypatch):
    client, settings, unit = make_case(tmp_path, monkeypatch)
    before = hashes(unit)
    pid = preview(client, settings, unit)
    jid = approved(client, f"/api/media-organizer/previews/{pid}/execute",
                   unit=str(unit), confirmation=execute.approval_token(pid, str(unit)))
    with client.app.state.service.SessionLocal() as session:
        job = session.get(WorkJob, jid)
        state = json.loads(job.state_json)
        state["recover_from_job_id"] = 19
        job.state_json = json.dumps(state)
        session.commit()
    assert worker(settings, jid) is False
    assert hashes(unit) == before
    assert not (settings.reports_dir / "media_organizer-executions" / str(jid)).exists()
