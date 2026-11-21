"""Shared API recovery authorizes frozen evidence; only the Worker opens media."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.batch import media_organizer_custody
from app.batch import media_organizer_execute_jobs as execution
from app.batch.media_organizer_manifest import _checksum
from app.config import Settings
from app.main import create_app
from app.models import WorkJob
from app.tasks.context import JobContext
from tests.test_media_organizer_execute_jobs import (
    execute_request, preview, recovery_token, setup, worker, scoped_namespace,
)
from tests.test_media_organizer_grouped_worker_custody import _install_issuer
from tests.test_media_organizer_shared_handoff import _snapshot


def _failed_shared(tmp_path, monkeypatch, *, phase="frozen", kind="grouped", shared=True):
    if shared:
        monkeypatch.setenv("NFC_SHARED_CONFIG_GID", str(os.getegid()))
    else:
        monkeypatch.delenv("NFC_SHARED_CONFIG_GID", raising=False)
    data, config = tmp_path / "data", tmp_path / "config"
    data.mkdir()
    config.mkdir(mode=0o700)
    if shared:
        config.chmod(0o2770)
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        MEDIA_ORGANIZER_EXECUTION_ENABLED=True,
        MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=True,
        ALLOW_MUTATION=True, ALLOW_DELETE=True,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    unit = data / "Collection" / "NO.001"
    unit.mkdir(mode=0o750, parents=True)
    files = {"photo.jpg": b"photo", "movie.mp4": b"video"}
    if kind == "flat":
        files = {"a.jpg": b"a", "b.jpg": b"b"}
    elif kind == "reused":
        files = {"P [2 2B]/000.jpg": b"a", "P [2 2B]/001.jpg": b"b",
                 "movie.mp4": b"v"}
    for name, contents in files.items():
        path = unit / name
        path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        path.write_bytes(contents)
    _install_issuer(monkeypatch, tmp_path, allowed=True)
    preview_id = preview(client, settings, unit)
    queued = execute_request(client, preview_id, unit)
    assert queued.status_code == 200, queued.text
    original_id = queued.json()["job_id"]
    with monkeypatch.context() as failure:
        if phase == "manual_cleanup_required":
            actual_checkpoint = JobContext.checkpoint

            def interrupted_checkpoint(context, **kwargs):
                actual_checkpoint(context, **kwargs)
                if kwargs.get("checkpoint_data", {}).get("phase") == phase:
                    raise RuntimeError("synthetic crash after durable final handoff checkpoint")

            failure.setattr(JobContext, "checkpoint", interrupted_checkpoint)
        else:
            function = {"frozen": "stage_frozen_sources", "staged": "publish_frozen_stage",
                        "published": "record_deferred_cleanup_evidence"}[phase]
            actual = getattr(execution, function)

            def interrupted(*args, **kwargs):
                if phase != "published":
                    actual(*args, **kwargs)
                raise RuntimeError("synthetic preparation/publication interruption")

            failure.setattr(execution, function, interrupted)
        assert worker(settings, original_id, name="shared-recovery-worker") is False
    status = client.get(f"/api/media-organizer/executions/{original_id}").json()
    assert status["status"] == "failed" and status["progress"]["phase"] == phase
    frozen = (settings.reports_dir / "media_organizer-executions" /
              str(original_id) / "manifest.json")
    return client, settings, unit, original_id, frozen


def _deny_api_media_open(monkeypatch, unit, *, permission_error=False):
    """Deny actual os.open attempts, including relative private-marker opens."""
    original_open = os.open
    attempts = []

    def guarded(path, *args, **kwargs):
        literal = Path(os.fsdecode(path))
        if not literal.is_absolute() and kwargs.get("dir_fd") is not None:
            literal = Path(os.readlink(f"/proc/self/fd/{kwargs['dir_fd']}")) / literal
        if (literal == unit or literal.is_relative_to(unit)
                or ".group-" in literal.name or "retirement" in literal.name
                or literal.name.endswith(".cleanup-progress.jsonl")):
            attempts.append(str(literal))
            if permission_error:
                raise PermissionError(errno.EACCES, "API cannot open Worker-private media", str(literal))
            raise AssertionError("API attempted a private/live media read")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    return attempts


def _request_recovery(client, original_id):
    return client.post(f"/api/media-organizer/executions/{original_id}/recover", json={
        "confirmation": recovery_token(original_id),
    })


@pytest.mark.parametrize("phase,kind", [("frozen", "flat"), ("staged", "grouped"),
                                       ("published", "reused"),
                                       ("manual_cleanup_required", "grouped")])
def test_shared_api_recovers_each_frozen_phase_then_cleans_up_correct_execution(
    tmp_path, monkeypatch, phase, kind,
):
    client, settings, unit, original_id, frozen = _failed_shared(
        tmp_path, monkeypatch, phase=phase, kind=kind,
    )
    manifest = json.loads(frozen.read_text())["manifest"]
    before = _snapshot(unit)
    with monkeypatch.context() as api:
        attempts = _deny_api_media_open(api, unit, permission_error=True)
        recovered = _request_recovery(client, original_id)
        assert recovered.status_code == 200, recovered.text
        assert attempts == []
    recovery_id = recovered.json()["job_id"]
    assert recovery_id != original_id
    assert _snapshot(unit) == before
    with client.app.state.service.SessionLocal() as session:
        original = session.get(WorkJob, original_id)
        recovery = session.get(WorkJob, recovery_id)
        checkpoint = json.loads(original.checkpoint_json)
        state = json.loads(recovery.state_json)
        assert checkpoint["manifest_checksum"] == _checksum(manifest)
        assert state["recovery_manifest_checksum"] == checkpoint["manifest_checksum"]
        assert state["recovery_phase"] == phase
        assert state["recovery_of_job_id"] == recovery.retry_of == original_id
    with monkeypatch.context() as recovery_worker:
        if phase in ("published", "manual_cleanup_required"):
            def no_repeat(*_args, **_kwargs):
                raise AssertionError("published recovery must not restage or republish")

            recovery_worker.setattr(execution, "stage_frozen_sources", no_repeat)
            recovery_worker.setattr(execution, "publish_frozen_stage", no_repeat)
        assert worker(settings, recovery_id, name="shared-recovery-worker")
    with monkeypatch.context() as api:
        _deny_api_media_open(api, unit)
        original_status = client.get(f"/api/media-organizer/executions/{original_id}").json()
        current = client.get(f"/api/media-organizer/executions/{recovery_id}").json()
        assert original_status["status"] == "failed" and not original_status["finalized"]
        assert current["status"] == "completed" and current["manual_cleanup_required"]
        assert not current["finalized"] and current["recovery_of_job_id"] == original_id
        plan = client.get(f"/api/media-organizer/executions/{recovery_id}/cleanup-plan")
        assert plan.status_code == 200, plan.text
        assert plan.json()["job_id"] == original_id
        assert plan.json()["reviewed_execution_job_id"] == recovery_id
        assert plan.json()["live_inventory_verified"] is False
        cleanup = client.post(f"/api/media-organizer/executions/{recovery_id}/cleanup", json={
            "confirmation": plan.json()["confirmation"],
        })
        assert cleanup.status_code == 200, cleanup.text
    with client.app.state.service.SessionLocal() as session:
        cleanup_state = json.loads(session.get(WorkJob, cleanup.json()["job_id"]).state_json)
        assert cleanup_state["execution_job_id"] == recovery_id
        assert cleanup_state["frozen_job_id"] == original_id
    assert worker(settings, cleanup.json()["job_id"], name="shared-recovery-worker")
    assert not (unit / manifest["stage_directory"]).exists()
    with monkeypatch.context() as api:
        _deny_api_media_open(api, unit)
        repeated = _request_recovery(client, original_id)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["job_id"] == recovery_id
        current = client.get(f"/api/media-organizer/executions/{recovery_id}").json()
        assert current["finalized"] and not current["manual_cleanup_required"]
        assert current["cleanup"]["job_id"] == cleanup.json()["job_id"]
        assert current["cleanup"]["status"] == "completed"
        assert not client.get(f"/api/media-organizer/executions/{original_id}").json()["finalized"]


@pytest.mark.parametrize("damage", ["missing-digest", "digest", "unit", "preview", "frozen-id",
                                   "schema", "manifest-content", "manifest-mode"])
def test_shared_recovery_refuses_unbound_artifacts_without_private_read_fallback(
    tmp_path, monkeypatch, damage,
):
    client, _settings, unit, original_id, frozen = _failed_shared(tmp_path, monkeypatch)
    if damage == "manifest-content":
        body = json.loads(frozen.read_text())
        body["manifest"]["input_fingerprint"] = "0" * 64
        body["checksum"] = _checksum(body["manifest"])
        frozen.write_text(json.dumps(body))
    elif damage == "manifest-mode":
        frozen.chmod(0o600)
    else:
        with client.app.state.service.SessionLocal() as session:
            job = session.get(WorkJob, original_id)
            checkpoint = json.loads(job.checkpoint_json)
            if damage == "missing-digest":
                checkpoint.pop("manifest_checksum", None)
            else:
                field, value = {
                    "digest": ("manifest_checksum", "0" * 64),
                    "unit": ("unit", str(unit.parent)),
                    "preview": ("preview_job_id", -1),
                    "frozen-id": ("frozen_job_id", original_id + 1),
                    "schema": ("schema_version", True),
                }[damage]
                checkpoint[field] = value
            job.checkpoint_json = json.dumps(checkpoint)
            session.commit()
    before = _snapshot(unit)
    with monkeypatch.context() as api:
        _deny_api_media_open(api, unit)
        refused = _request_recovery(client, original_id)
        assert refused.status_code == 409, refused.text
    assert _snapshot(unit) == before


@pytest.mark.parametrize("damage", ["queued-digest", "queued-phase", "retry-of", "selection",
                                   "original-digest", "original-unit", "nested-original"])
def test_shared_recovery_worker_rechecks_queued_and_original_authority_before_mutation(
    tmp_path, monkeypatch, damage,
):
    client, settings, unit, original_id, _frozen = _failed_shared(tmp_path, monkeypatch)
    recovered = _request_recovery(client, original_id)
    assert recovered.status_code == 200, recovered.text
    recovery_id = recovered.json()["job_id"]
    with client.app.state.service.SessionLocal() as session:
        original = session.get(WorkJob, original_id)
        recovery = session.get(WorkJob, recovery_id)
        state = json.loads(recovery.state_json)
        checkpoint = json.loads(original.checkpoint_json)
        if damage == "queued-digest":
            state["recovery_manifest_checksum"] = "0" * 64
        elif damage == "queued-phase":
            state["recovery_phase"] = "published"
        elif damage == "retry-of":
            # A real, unrelated row satisfies the FK but cannot authorize R.
            recovery.retry_of = json.loads(original.state_json)["preview_job_id"]
        elif damage == "selection":
            state["selection"] = str(unit)
        elif damage == "original-digest":
            checkpoint.pop("manifest_checksum", None)
        elif damage == "original-unit":
            checkpoint["unit"] = str(unit.parent)
        else:
            original_state = json.loads(original.state_json)
            original_state["recovery_of_job_id"] = original_id + 100
            original.state_json = json.dumps(original_state)
        recovery.state_json = json.dumps(state)
        original.checkpoint_json = json.dumps(checkpoint)
        session.commit()
    before = _snapshot(unit)
    assert worker(settings, recovery_id, name="shared-recovery-worker") is False
    assert _snapshot(unit) == before


@pytest.mark.parametrize("damage", ["stage-owner", "source-inode", "stage-permissions"])
def test_shared_api_snapshot_does_not_replace_worker_private_recovery_validation(
    tmp_path, monkeypatch, damage,
):
    client, settings, unit, original_id, frozen = _failed_shared(tmp_path, monkeypatch)
    manifest = json.loads(frozen.read_text())["manifest"]
    stage = unit / manifest["stage_directory"]
    if damage == "stage-owner":
        (stage / ".nfc-stage-authority").write_bytes(b"foreign authority")
    elif damage == "source-inode":
        source = Path(manifest["moves"][0]["source"])
        source.unlink()
        source.write_bytes(b"foreign replacement")
    else:
        stage.chmod(0o750)
    before = _snapshot(unit)
    with monkeypatch.context() as api:
        _deny_api_media_open(api, unit)
        recovered = _request_recovery(client, original_id)
        assert recovered.status_code == 200, recovered.text
    assert worker(settings, recovered.json()["job_id"], name="shared-recovery-worker") is False
    assert _snapshot(unit) == before


def test_legacy_recovery_still_requires_live_private_stage_read(tmp_path, monkeypatch, scoped_namespace):
    monkeypatch.delenv("NFC_SHARED_CONFIG_GID", raising=False)
    client, settings, unit = setup(tmp_path, enabled=True)
    preview_id = preview(client, settings, unit)
    original_id = execute_request(client, preview_id, unit).json()["job_id"]
    real_stage = execution.stage_frozen_sources

    def interrupted(*args, **kwargs):
        real_stage(*args, **kwargs)
        raise RuntimeError("synthetic legacy interruption")

    with monkeypatch.context() as failure:
        failure.setattr(execution, "stage_frozen_sources", interrupted)
        assert worker(settings, original_id, name="shared-recovery-worker") is False
    with monkeypatch.context() as api:
        attempts = _deny_api_media_open(api, unit, permission_error=True)
        refused = _request_recovery(client, original_id)
        assert refused.status_code == 409, refused.text
        assert attempts


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("failure", ["missing-issuer", "scoped-parent"])
def test_recovery_queue_requires_current_custody_without_consuming_attempt(
    tmp_path, monkeypatch, shared, failure,
):
    client, _settings, unit, original_id, frozen = _failed_shared(
        tmp_path, monkeypatch, kind="reused", shared=shared,
    )
    manifest = json.loads(frozen.read_text())["manifest"]
    revoked = Path(manifest["moves"][0]["target"]).parent
    assert revoked != unit

    class ScopedRevocation:
        def assert_exclusive(self, parent):
            if parent == revoked:
                raise ValueError("synthetic stage-parent custody revoked")

    def missing_issuer(*_args):
        raise ValueError("synthetic namespace custody issuer unavailable")

    with monkeypatch.context() as unavailable:
        unavailable.setattr(media_organizer_custody, "verified_namespace_custody",
                            missing_issuer if failure == "missing-issuer"
                            else lambda *_args: ScopedRevocation())
        if shared:
            _deny_api_media_open(unavailable, unit)
        refused = _request_recovery(client, original_id)
        assert refused.status_code == 409, refused.text
    with client.app.state.service.SessionLocal() as session:
        assert not any(json.loads(job.state_json or "{}").get("recovery_of_job_id") == original_id
                       for job in session.query(WorkJob).all())
    restored = _request_recovery(client, original_id)
    assert restored.status_code == 200, restored.text
    assert restored.json()["job_id"] != original_id
    # Returning the already authorized job consumes no new attempt or custody.
    with monkeypatch.context() as unavailable:
        unavailable.setattr(media_organizer_custody, "verified_namespace_custody", missing_issuer)
        repeated = _request_recovery(client, original_id)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["job_id"] == restored.json()["job_id"]
