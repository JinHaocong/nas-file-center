"""Shared-GID API reads Worker snapshots without private-media traversal.

These local tests guard prohibited reads explicitly. Actual distinct kernel
UIDs are exercised by the separate CI lifecycle script, not mocked here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess

from fastapi.testclient import TestClient
import pytest

from app.batch import media_organizer_execute_jobs as execution
from app.config import Settings
from app.main import create_app
from app.models import WorkJob
from tests.test_media_organizer_execute_jobs import preview, execute_request, worker
from tests.test_media_organizer_grouped_worker_custody import _install_issuer


def _prepared_shared(tmp_path, monkeypatch, kind="flat", *, original_group_mode=0o750):
    monkeypatch.setenv("NFC_SHARED_CONFIG_GID", str(os.getegid()))
    data, config = tmp_path / "data", tmp_path / "config"
    data.mkdir()
    config.mkdir(mode=0o2770)
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
    files = {"a.jpg": b"a", "b.jpg": b"b"}
    if kind == "grouped":
        files = {"photo.jpg": b"photo", "movie.mp4": b"video"}
    elif kind == "reused":
        files = {"P [2 2B]/000.jpg": b"a", "P [2 2B]/001.jpg": b"b",
                 "movie.mp4": b"v"}
    for name, contents in files.items():
        path = unit / name
        path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        path.write_bytes(contents)
    if kind == "reused":
        (unit / "P [2 2B]").chmod(original_group_mode)
    _install_issuer(monkeypatch, tmp_path, allowed=True)
    preview_id = preview(client, settings, unit)
    queued = execute_request(client, preview_id, unit)
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    assert worker(settings, job_id, name="shared-handoff-worker")
    frozen = settings.reports_dir / "media_organizer-executions" / str(job_id) / "manifest.json"
    manifest = json.loads(frozen.read_text())["manifest"]
    return client, settings, unit, job_id, frozen, manifest


def _forbid_api_private_reads(monkeypatch, unit):
    def private_reader(*_args, **_kwargs):
        raise AssertionError("API attempted Worker-private live inventory")

    for name in ("read_deferred_cleanup_review", "audit_deferred_cleanup_inventory",
                 "read_cleanup_plan"):
        monkeypatch.setattr(execution, name, private_reader)
    original_open = os.open

    def guarded_open(path, *args, **kwargs):
        literal = Path(os.fsdecode(path))
        if not literal.is_absolute() and kwargs.get("dir_fd") is not None:
            literal = Path(os.readlink(f"/proc/self/fd/{kwargs['dir_fd']}")) / literal
        if (literal == unit or literal.is_relative_to(unit)
                or ".group-" in literal.name
                or literal.name.endswith(".cleanup-progress.jsonl")):
            raise AssertionError("API attempted private evidence or media open")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)


def _snapshot(unit):
    return {str(path.relative_to(unit)): path.read_bytes()
            for path in unit.rglob("*") if path.is_file()}


@pytest.mark.parametrize("kind", ["flat", "grouped", "reused"])
def test_shared_api_reviews_and_queues_from_snapshot_without_private_reads(
    tmp_path, monkeypatch, kind,
):
    client, settings, unit, job_id, frozen, manifest = _prepared_shared(tmp_path, monkeypatch, kind)
    before = _snapshot(unit)
    with monkeypatch.context() as api:
        _forbid_api_private_reads(api, unit)
        for suffix in ("cleanup-review", "cleanup-audit", "cleanup-plan"):
            response = client.get(f"/api/media-organizer/executions/{job_id}/{suffix}")
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["verification_scope"] == "worker_handoff_snapshot"
            assert result["live_inventory_verified"] is False
            assert result["read_only"] is True
            for item in result.get("items", []):
                assert "source_present" not in item
                assert "stage_present" not in item
                assert "target_present" not in item
                assert item["snapshot_source_present"] is True
        plan = response.json()
        queued = client.post(f"/api/media-organizer/executions/{job_id}/cleanup", json={
            "confirmation": plan["confirmation"],
        })
        assert queued.status_code == 200, queued.text
    assert _snapshot(unit) == before
    assert stat.S_IMODE((unit / manifest["stage_directory"]).stat().st_mode) & 0o777 == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600
               for path in frozen.parent.glob("*.group-*.json"))
    assert worker(settings, queued.json()["job_id"], name="shared-handoff-worker")
    assert client.get(f"/api/media-organizer/executions/{job_id}").json()["finalized"] is True


def test_shared_snapshot_does_not_replace_worker_live_revalidation(tmp_path, monkeypatch):
    client, settings, unit, job_id, _frozen, manifest = _prepared_shared(tmp_path, monkeypatch)
    original = Path(manifest["moves"][0]["source"])
    original.unlink()
    original.write_bytes(b"foreign-after-worker-snapshot")
    with monkeypatch.context() as api:
        _forbid_api_private_reads(api, unit)
        plan = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-plan")
        assert plan.status_code == 200, plan.text
        queued = client.post(f"/api/media-organizer/executions/{job_id}/cleanup", json={
            "confirmation": plan.json()["confirmation"],
        })
        assert queued.status_code == 200, queued.text
    before = _snapshot(unit)
    assert worker(settings, queued.json()["job_id"], name="shared-handoff-worker") is False
    assert _snapshot(unit) == before
    assert client.get(f"/api/media-organizer/executions/{job_id}").json()["finalized"] is False


@pytest.mark.parametrize("damage", ["manifest-mode", "report-mode", "report-content", "plan-content",
                                   "checkpoint-digest", "checkpoint-unit", "job-not-completed"])
def test_shared_handoff_refuses_changed_artifacts_or_checkpoint_without_fallback(
    tmp_path, monkeypatch, damage,
):
    client, _settings, unit, job_id, frozen, _manifest = _prepared_shared(tmp_path, monkeypatch)
    if damage == "manifest-mode":
        frozen.chmod(0o600)
    elif damage == "report-mode":
        frozen.with_name(frozen.name + ".manual-cleanup.json").chmod(0o600)
    elif damage in ("report-content", "plan-content"):
        suffix = ".manual-cleanup.json" if damage == "report-content" else ".cleanup-plan.json"
        path = frozen.with_name(frozen.name + suffix)
        document = json.loads(path.read_text())
        document["unit"] = str(unit.parent)
        path.write_text(json.dumps(document))
    else:
        with client.app.state.service.SessionLocal() as session:
            job = session.get(WorkJob, job_id)
            checkpoint = json.loads(job.checkpoint_json)
            if damage == "checkpoint-digest":
                checkpoint["cleanup_plan_sha256"] = "0" * 64
            elif damage == "checkpoint-unit":
                checkpoint["unit"] = str(unit.parent)
            else:
                job.status = "running"
            job.checkpoint_json = json.dumps(checkpoint)
            session.commit()
    before = _snapshot(unit)
    with monkeypatch.context() as api:
        _forbid_api_private_reads(api, unit)
        response = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-plan")
        assert response.status_code == 409, response.text
    assert _snapshot(unit) == before


def test_shared_new_groups_are_readable_but_private_stage_and_witnesses_stay_private(
    tmp_path, monkeypatch,
):
    client, settings, unit, job_id, frozen, manifest = _prepared_shared(tmp_path, monkeypatch, "grouped")
    for group in manifest["groups"]:
        directory = Path(group["destination"])
        info = directory.stat()
        assert stat.S_IMODE(info.st_mode) == 0o750
        assert info.st_uid == os.geteuid()
        assert info.st_gid == os.getegid()
        for marker in (".nfc-publish-owner", ".nfc-publish-complete"):
            assert stat.S_IMODE((directory / marker).stat().st_mode) == 0o600
    stage = unit / manifest["stage_directory"]
    assert stat.S_IMODE(stage.stat().st_mode) & 0o777 == 0o700
    plan = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-plan")
    assert plan.status_code == 200, plan.text
    queued = client.post(f"/api/media-organizer/executions/{job_id}/cleanup", json={
        "confirmation": plan.json()["confirmation"],
    })
    assert queued.status_code == 200, queued.text
    assert worker(settings, queued.json()["job_id"], name="shared-handoff-worker")
    for group in manifest["groups"]:
        assert stat.S_IMODE(Path(group["destination"]).stat().st_mode) == 0o750
    assert stat.S_IMODE(frozen.with_name(frozen.name + ".cleanup-progress.jsonl").stat().st_mode) == 0o600


def test_no_shared_gid_retains_live_reader_and_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("NFC_SHARED_CONFIG_GID", raising=False)
    from tests.test_media_organizer_cleanup_jobs import _published
    client, _settings, unit, job_id, _token, _state = _published(tmp_path, monkeypatch)
    response = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-plan")
    assert response.status_code == 200, response.text
    assert response.json()["verification_scope"] == "live_frozen_inventory"
    assert response.json()["live_inventory_verified"] is True
    (unit / "photo.jpg").unlink()
    (unit / "photo.jpg").write_bytes(b"foreign")
    assert client.get(f"/api/media-organizer/executions/{job_id}/cleanup-plan").status_code == 409


def test_shared_mode_never_repairs_existing_group_permissions(tmp_path, monkeypatch):
    _client, _settings, unit, _job_id, _frozen, _manifest = _prepared_shared(
        tmp_path, monkeypatch, "reused", original_group_mode=0o710,
    )
    assert stat.S_IMODE((unit / "P [2 2B]").stat().st_mode) == 0o710
    assert stat.S_IMODE((unit / "V [1 1B]").stat().st_mode) == 0o750


def test_distinct_uid_lifecycle_runner_refuses_outside_ci_before_any_setup(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "test_v16_cleanup_cross_uid.sh"
    environment = {**os.environ, "GITHUB_ACTIONS": "false", "PATH": "/nonexistent"}
    result = subprocess.run(["/bin/bash", str(script)], cwd=tmp_path,
                            env=environment, capture_output=True, text=True)
    assert result.returncode == 2
    assert "CI-only" in result.stderr
    assert list(tmp_path.iterdir()) == []
