"""Real issuer denial at API/Worker boundaries, including maintenance mode.

Synthetic issuers are used only to prepare historical pending job fixtures.
The operation under test always uses the unchanged production issuer unless
the test explicitly verifies revocation of an already acquired scoped proof.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.batch import media_organizer_authority as authority
from app.batch import media_organizer_cleanup_jobs as cleanup
from app.batch import media_organizer_custody as custody
from app.batch import media_organizer_execute_jobs as execution
from app.config import Settings
from app.main import create_app
from app.models import WorkJob
from tests.test_media_organizer_execute_jobs import preview, worker
from tests.test_media_organizer_grouped_worker_custody import _install_issuer


def _site(tmp_path, mode, *, grouped=True):
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir(mode=0o700)
    unit = data / "collection" / "unit"
    unit.mkdir(parents=True, mode=0o700)
    (unit / "photo.jpg").write_bytes(b"original photo")
    if grouped:
        (unit / "video.mp4").write_bytes(b"original video")
    settings = Settings(
        _env_file=None, CONFIG_DIR=config, DATA_MOUNT=data,
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=data / ".trash",
        ALLOW_MUTATION=True, ALLOW_DELETE=True,
        MEDIA_ORGANIZER_EXECUTION_ENABLED=True,
        MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=True,
        MEDIA_ORGANIZER_EXECUTION_MODE=mode,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    return client, settings, unit


def _snapshot(root):
    return {
        str(path.relative_to(root)): (
            path.stat().st_ino, path.read_bytes() if path.is_file() else None,
        )
        for path in root.rglob("*")
    }


def _ack(mode):
    return {"maintenance_window_confirmed": mode == "maintenance_window"}


def _queue(client, settings, unit, pid):
    return client.post(f"/api/media-organizer/previews/{pid}/execute", json={
        "unit": str(unit), "confirmation": execution.approval_token(pid, str(unit)),
        **_ack(settings.media_organizer_execution_mode),
    })


@pytest.mark.parametrize("mode", ["strict", "maintenance_window"])
@pytest.mark.parametrize("grouped", [False, True], ids=["flat", "grouped"])
def test_all_execution_submissions_refuse_unproven_namespace(tmp_path, mode, grouped):
    client, settings, unit = _site(tmp_path, mode, grouped=grouped)
    pid = preview(client, settings, unit)
    before = _snapshot(unit)
    response = _queue(client, settings, unit, pid)
    assert response.status_code == 409, response.text
    assert "custody" in response.text.lower()
    with client.app.state.service.SessionLocal() as session:
        assert session.scalars(select(WorkJob).where(
            WorkJob.kind == "media-organizer-execute",
        )).all() == []
    assert _snapshot(unit) == before


def test_flat_preview_does_not_offer_confirmation_without_custody(tmp_path):
    client, settings, unit = _site(tmp_path, "strict", grouped=False)
    pid = preview(client, settings, unit)
    report = client.get(f"/api/media-organizer/previews/{pid}").json()
    assert str(unit) not in report["confirmation_tokens"]
    assert report["read_only"] is True
    assert (unit / "photo.jpg").read_bytes() == b"original photo"


def test_maintenance_eligibility_does_not_consume_parent_scope_before_proof(
    tmp_path, monkeypatch,
):
    _, settings, unit = _site(tmp_path, "maintenance_window")
    selected_parent = unit / "P1"
    selected_parent.mkdir()
    observed = []

    class Proof:
        def assert_exclusive(self, parent):
            observed.append(parent)
            if parent == selected_parent:
                raise custody.NamespaceCustodyUnavailable("selected parent not protected")

    monkeypatch.setattr(custody, "verified_namespace_custody", lambda *_: Proof())
    with pytest.raises(custody.NamespaceCustodyUnavailable, match="not protected"):
        authority.check_api_eligibility(settings, unit, iter((unit, selected_parent)))
    assert selected_parent in observed


@pytest.mark.parametrize("mode", ["strict", "maintenance_window"])
@pytest.mark.parametrize("grouped", [False, True], ids=["flat", "grouped"])
def test_previously_queued_execution_cannot_bypass_worker_custody(
    tmp_path, monkeypatch, mode, grouped,
):
    client, settings, unit = _site(tmp_path, mode, grouped=grouped)
    pid = preview(client, settings, unit)
    with monkeypatch.context() as admitted_fixture:
        _install_issuer(admitted_fixture, tmp_path, allowed=True)
        response = _queue(client, settings, unit, pid)
        assert response.status_code == 200, response.text
    jid = response.json()["job_id"]
    before = _snapshot(unit)
    assert worker(settings, jid) is False
    assert _snapshot(unit) == before
    assert not (settings.reports_dir / "media_organizer-executions" / str(jid)).exists()
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert status["status"] == "failed" and not status["finalized"]
    assert "custody" in status["error"].lower()


@pytest.mark.parametrize("operation", ["execution-recovery", "cleanup", "cleanup-recovery"])
@pytest.mark.parametrize("mode", ["strict", "maintenance_window"])
def test_cleanup_and_recovery_reacquire_proof_and_preserve_historical_evidence(
    tmp_path, monkeypatch, operation, mode,
):
    client, settings, unit = _site(tmp_path, mode, grouped=False)
    pid = preview(client, settings, unit)
    with monkeypatch.context() as admitted_fixture:
        _install_issuer(admitted_fixture, tmp_path, allowed=True)
        queued = _queue(client, settings, unit, pid)
        assert queued.status_code == 200, queued.text
        jid = queued.json()["job_id"]
        if operation == "execution-recovery":
            real_stage = execution.stage_frozen_sources

            def interrupt_after_staging(*args, **kwargs):
                real_stage(*args, **kwargs)
                raise RuntimeError("disposable interruption after staging")

            with monkeypatch.context() as interrupt:
                interrupt.setattr(execution, "stage_frozen_sources", interrupt_after_staging)
                assert worker(settings, jid) is False
            path = f"/api/media-organizer/executions/{jid}/recover"
            token = execution.recovery_token(jid)
        else:
            assert worker(settings, jid)
            base = f"/api/media-organizer/executions/{jid}"
            review = client.get(base + "/cleanup-plan")
            assert review.status_code == 200, review.text
            path = base + "/cleanup"
            token = review.json()["confirmation"]
            if operation == "cleanup-recovery":
                queued = client.post(path, json={"confirmation": token, **_ack(mode)})
                assert queued.status_code == 200, queued.text
                cid = queued.json()["job_id"]

                def interrupt_before_cleanup(*args, **kwargs):
                    raise RuntimeError("disposable interruption before cleanup")

                with monkeypatch.context() as interrupt:
                    interrupt.setattr(cleanup, "finish_deferred_cleanup", interrupt_before_cleanup)
                    assert worker(settings, cid) is False
                token = client.get(base).json()["cleanup"]["recovery_confirmation"]
                path = f"/api/media-organizer/cleanups/{cid}/recover"
    before_media = _snapshot(unit)
    evidence = settings.reports_dir / "media_organizer-executions"
    before_evidence = _snapshot(evidence)
    with client.app.state.service.SessionLocal() as session:
        before_ids = session.scalars(select(WorkJob.id)).all()
    rejected = client.post(path, json={"confirmation": token, **_ack(mode)})
    assert rejected.status_code == 409, rejected.text
    assert "custody" in rejected.text.lower()
    assert _snapshot(unit) == before_media
    assert _snapshot(evidence) == before_evidence
    with client.app.state.service.SessionLocal() as session:
        assert session.scalars(select(WorkJob.id)).all() == before_ids
    # An immutable review remains readable even while mutation is held.
    if operation != "execution-recovery":
        review = client.get(f"/api/media-organizer/executions/{jid}/cleanup-plan")
        assert review.status_code == 200, review.text
        assert review.json()["cleanup_authorized"] is False


def test_real_maintenance_session_cannot_be_issued_from_ack_and_lock_alone(tmp_path):
    _, settings, unit = _site(tmp_path, "maintenance_window")
    before = _snapshot(unit)
    with pytest.raises(custody.NamespaceCustodyUnavailable, match="not proven"):
        with authority.acquire_operation_authority(settings, unit, (unit,)):
            pytest.fail("operator acknowledgement issued unproven mutation authority")
    assert _snapshot(unit) == before


def test_maintenance_session_refreshes_and_releases_its_scoped_proof(tmp_path, monkeypatch):
    _, settings, unit = _site(tmp_path, "maintenance_window")

    class RevocableFixture:
        active = True
        closed = False
        checks = 0

        def assert_exclusive(self, parent):
            assert Path(parent).is_relative_to(unit)
            if not self.active or self.closed:
                raise custody.NamespaceCustodyUnavailable("fixture custody revoked")
            self.checks += 1

        def close(self):
            self.closed = True

    proof = RevocableFixture()
    monkeypatch.setattr(custody, "verified_namespace_custody", lambda *_: proof)
    with authority.acquire_operation_authority(settings, unit, (unit,)) as session:
        authority.assert_operation_authorized(session, (unit,))
        assert proof.checks > 0, "maintenance session never acquired its external proof"
        proof.active = False
        with pytest.raises(custody.NamespaceCustodyUnavailable, match="revoked"):
            authority.assert_operation_authorized(session, (unit,))
    assert proof.closed, "operation did not release its held namespace resource"
