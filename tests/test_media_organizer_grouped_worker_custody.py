"""#402 real API→Worker grouped path under explicit synthetic namespace custody.

The issuer is monkeypatched only inside tmp_path tests; production has NO
issuer. This proves end-to-end plumbing without authorizing NAS mutations.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.batch import media_organizer_custody as custody
from app.batch.media_organizer_execute_jobs import approval_token
from app.batch.media_organizer_finalize import (
    cleanup_confirmation, finish_deferred_cleanup,
)
from app.batch.media_organizer_planner import preview_semantic_unit
from tests.test_media_organizer_execute_jobs import (
    setup, preview, execute_request, worker,
)


class ScopedSyntheticCustody:
    def __init__(self, root: Path):
        self.root = root

    def assert_exclusive(self, parent: Path):
        if not Path(parent).is_relative_to(self.root):
            raise ValueError("SEC-12: outside synthetic custody boundary")


def _install_issuer(monkeypatch, tmp_path, *, allowed):
    state = {"allowed": allowed}

    def issue(_settings, unit):
        if not state["allowed"]:
            raise ValueError("SEC-12: external exclusive namespace custody absent")
        proof = ScopedSyntheticCustody(tmp_path)
        proof.assert_exclusive(unit)
        return proof

    monkeypatch.setattr(custody, "verified_namespace_custody", issue)
    return state


def test_grouped_admin_confirmed_worker_and_cleanup_reach_second_scan_zero(
    tmp_path, monkeypatch,
):
    client, settings, unit = setup(tmp_path, enabled=True)
    (unit / "movie.mp4").write_bytes(b"synthetic-video")
    old = unit / "P1"
    old.mkdir()
    (old / "legacy.jpg").write_bytes(b"synthetic-legacy-image")
    state = _install_issuer(monkeypatch, tmp_path, allowed=True)
    pid = preview(client, settings, unit)
    report = client.get(f"/api/media-organizer/previews/{pid}").json()
    record = next(row for row in report["units"] if row["unit"] == str(unit))
    assert record["groups"]
    assert report["confirmation_tokens"][str(unit)] == approval_token(pid, str(unit))

    queued = execute_request(client, pid, unit)
    assert queued.status_code == 200, queued.text
    jid = queued.json()["job_id"]
    assert worker(settings, jid, name="real-grouped-synthetic-owner")
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert status["status"] == "completed"
    assert status["manual_cleanup_required"] is True
    assert status["finalized"] is False

    folder = settings.reports_dir / "media_organizer-executions" / str(jid)
    path = folder / "manifest.json"
    frozen = json.loads(path.read_text())["manifest"]
    assert {group["kind"] for group in frozen["groups"]} == {"P", "V"}
    assert len(frozen["moves"]) == 4
    for row in frozen["moves"]:
        assert Path(row["source"]).read_bytes() == Path(row["final"]).read_bytes()
    plan = json.loads((folder / "manifest.json.cleanup-plan.json").read_text())
    stage = unit / frozen["stage_directory"]
    assert stage.is_dir()
    assert old.is_dir()

    result = finish_deferred_cleanup(
        frozen, frozen_manifest_path=path, allowed_roots=[settings.data_mount],
        confirmation=cleanup_confirmation(jid, str(unit), plan["plan_sha256"]),
        custody=ScopedSyntheticCustody(tmp_path),
        quarantine_root=settings.quarantine_root,
    )
    assert result["finalized"] is True
    assert result["groups_verified"] == 2
    assert not old.exists()
    assert not stage.exists()
    second = preview_semantic_unit(
        unit, allowed_roots=[settings.data_mount],
        quarantine_root=settings.quarantine_root,
    )
    assert second["status"] == "already_organized"
    assert second["needed_moves"] == second["renamed_count"] == 0


def test_revoked_custody_after_group_queue_blocks_worker_before_stage(
    tmp_path, monkeypatch,
):
    client, settings, unit = setup(tmp_path, enabled=True)
    (unit / "movie.mp4").write_bytes(b"synthetic-video")
    state = _install_issuer(monkeypatch, tmp_path, allowed=True)
    pid = preview(client, settings, unit)
    queued = execute_request(client, pid, unit)
    assert queued.status_code == 200, queued.text
    state["allowed"] = False
    assert worker(settings, queued.json()["job_id"], name="revoked-synthetic-owner") is False
    assert (unit / "movie.mp4").read_bytes() == b"synthetic-video"
    assert (unit / "photo.jpg").read_bytes() == b"photo-1"
    assert not any(x.name.startswith(".nfc-") for x in unit.iterdir())
    assert not any(x.name.startswith("P [") or x.name.startswith("V [")
                   for x in unit.iterdir())


def test_boolean_ack_without_custody_object_never_enables_grouped_queue(
    tmp_path, monkeypatch,
):
    client, settings, unit = setup(tmp_path, enabled=True)
    (unit / "movie.mp4").write_bytes(b"synthetic-video")
    # A plain successful checkbox/boolean is not a scoped custody proof.
    monkeypatch.setattr(custody, "verified_namespace_custody", lambda *_: True)
    pid = preview(client, settings, unit)
    read = client.get(f"/api/media-organizer/previews/{pid}").json()
    assert str(unit) not in read["confirmation_tokens"]
    refused = execute_request(client, pid, unit)
    assert refused.status_code == 409
    assert "SEC-12" in refused.text or "custody" in refused.text
    assert (unit / "movie.mp4").read_bytes() == b"synthetic-video"
    assert not any(x.name.startswith(".nfc-") for x in unit.iterdir())


def test_without_external_issuer_grouped_execution_is_still_blocked(
    tmp_path,
):
    client, settings, unit = setup(tmp_path, enabled=True)
    (unit / "movie.mp4").write_bytes(b"synthetic-video")
    pid = preview(client, settings, unit)
    result = execute_request(client, pid, unit)
    assert result.status_code == 409
    assert not any(x.name.startswith(".nfc-") for x in unit.iterdir())
