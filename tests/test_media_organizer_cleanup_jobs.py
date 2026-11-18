"""#400: explicit separate cleanup WorkJob, NOT silent publication-time deletion.

No real NAS usage. A scoped, disposable test issuer is required at BOTH API
queue and Worker mutation boundaries; production issuer still fails closed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.batch.media_organizer_finalize import cleanup_confirmation
from app.batch import media_organizer_custody as custody
from app.batch.media_organizer_planner import preview_semantic_unit
from tests.test_media_organizer_execute_jobs import (
    setup, preview, execute_request, worker,
)
from tests.test_media_organizer_grouped_worker_custody import _install_issuer


def _published(tmp_path, monkeypatch, *, mixed=False, old_wrapper=True):
    client, settings, unit = setup(tmp_path, enabled=True)
    if mixed:
        (unit / "movie.mp4").write_bytes(b"synthetic-video")
    if old_wrapper:
        old = unit / "P1"
        old.mkdir()
        (old / "legacy.jpg").write_bytes(b"legacy-image")
    state = _install_issuer(monkeypatch, tmp_path, allowed=True)
    pid = preview(client, settings, unit)
    response = execute_request(client, pid, unit)
    assert response.status_code == 200, response.text
    jid = response.json()["job_id"]
    assert worker(settings, jid, name="synthetic-original-worker")
    folder = settings.reports_dir / "media_organizer-executions" / str(jid)
    plan = json.loads((folder / "manifest.json.cleanup-plan.json").read_text())
    token = cleanup_confirmation(jid, str(unit), plan["plan_sha256"])
    return client, settings, unit, jid, token, state


@pytest.mark.parametrize("mixed", [False, True])
def test_separate_cleanup_worker_performs_real_finalization_and_zero_rescan(
    tmp_path, monkeypatch, mixed,
):
    client, settings, unit, jid, token, state = _published(
        tmp_path, monkeypatch, mixed=mixed,
    )
    old = unit / "P1"
    assert old.is_dir()
    start = client.post(f"/api/media-organizer/executions/{jid}/cleanup",
                        json={"confirmation": token})
    assert start.status_code == 200, start.text
    cleanup_id = start.json()["job_id"]
    # The HTTP request must queue only; no unlink happens in API process.
    assert old.is_dir()
    assert (unit / "photo.jpg").is_file()
    assert worker(settings, cleanup_id, name="synthetic-cleanup-owner")
    result = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert result["status"] == "completed"
    assert result["finalized"] is True
    assert result["manual_cleanup_required"] is False
    assert not old.exists()
    assert not (unit / "photo.jpg").exists()
    assert not any(x.name.startswith(".nfc-") for x in unit.iterdir())
    scan = preview_semantic_unit(
        unit, allowed_roots=[settings.data_mount],
        quarantine_root=settings.quarantine_root,
    )
    assert scan["status"] == "already_organized"
    assert scan["needed_moves"] == 0
    assert scan["renamed_count"] == 0


def test_cleanup_api_requires_different_exact_plan_token_and_is_idempotent(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, token, state = _published(
        tmp_path, monkeypatch,
    )
    path = f"/api/media-organizer/executions/{jid}/cleanup"
    invalid = client.post(path, json={"confirmation": "EXECUTE_WRONG_TOKEN"})
    assert invalid.status_code == 409
    assert (unit / "photo.jpg").is_file()
    first = client.post(path, json={"confirmation": token})
    assert first.status_code == 200, first.text
    second = client.post(path, json={"confirmation": token})
    assert second.status_code == 200, second.text
    assert first.json()["job_id"] == second.json()["job_id"]
    # A malicious request cannot enqueue another implicit cleanup unit.
    assert (unit / "P1").exists()


def test_missing_real_custody_issuer_refuses_to_queue_cleanup(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, token, state = _published(
        tmp_path, monkeypatch,
    )
    state["allowed"] = False
    result = client.post(
        f"/api/media-organizer/executions/{jid}/cleanup",
        json={"confirmation": token},
    )
    assert result.status_code == 409
    assert (unit / "photo.jpg").read_bytes() == b"photo-1"
    assert (unit / "P1" / "legacy.jpg").read_bytes() == b"legacy-image"


def test_revoked_custody_after_cleanup_queue_refuses_worker_before_unlink(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, token, state = _published(
        tmp_path, monkeypatch,
    )
    queued = client.post(f"/api/media-organizer/executions/{jid}/cleanup",
                         json={"confirmation": token})
    assert queued.status_code == 200
    state["allowed"] = False
    assert worker(settings, queued.json()["job_id"], name="revoked-cleanup-owner") is False
    assert (unit / "photo.jpg").read_bytes() == b"photo-1"
    assert (unit / "P1" / "legacy.jpg").read_bytes() == b"legacy-image"
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert status["finalized"] is False
    assert status["manual_cleanup_required"] is True


def test_cleanup_endpoint_requires_admin_authentication(tmp_path, monkeypatch):
    client, settings, unit, jid, token, state = _published(
        tmp_path, monkeypatch,
    )
    client.cookies.clear()
    result = client.post(
        f"/api/media-organizer/executions/{jid}/cleanup",
        json={"confirmation": token},
    )
    assert result.status_code == 401
