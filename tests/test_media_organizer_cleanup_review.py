"""#400: admin-only read-only audit of a deferred media organizer publication.

The review endpoint must not enqueue another destructive WorkJob, create a
report, or remove a retained original/stage/wrapper. Files are synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.test_media_organizer_execute_jobs import (
    setup, preview, execute_request, worker,
)


def _completed(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    wrapper = work / "P1"
    wrapper.mkdir()
    (wrapper / "third.jpg").write_bytes(b"third-original")
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    assert worker(settings, job_id, name="synthetic-audit-worker")
    return client, settings, work, job_id


def _witness_files(root: Path) -> dict[str, tuple[int, int]]:
    # Any read-only audit must not alter, delete, or publish media.
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def test_cleanup_review_exposes_verified_frozen_page_without_mutation(tmp_path):
    client, settings, work, job_id = _completed(tmp_path)
    before = _witness_files(work)
    folder = settings.reports_dir / "media_organizer-executions" / str(job_id)
    manifest = folder / "manifest.json"
    journal = folder / "manifest.json.manual-cleanup.json"
    evidence_before = (manifest.read_bytes(), journal.read_bytes())

    first = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review",
                       params={"page": 1, "page_size": 2})
    assert first.status_code == 200, first.text
    review = first.json()
    assert review["job_id"] == job_id
    assert review["manual_cleanup_required"] is True
    assert review["finalized"] is False
    assert review["cleanup_authorized"] is False
    assert review["files_total"] == 3
    assert review["page"] == 1
    assert review["page_size"] == 2
    assert len(review["items"]) == 2
    assert review["original_sources_retained"] == 3
    assert review["staged_links_retained"] == 3
    assert review["old_wrapper_count"] == 1
    for row in review["items"]:
        assert row["source"] and row["target"] and row["stage"]
        assert row["source_present"] is True
        assert row["stage_present"] is True
        assert row["target_present"] is True
        assert row["identity_matches"] is True
    second = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review",
                        params={"page": 2, "page_size": 2})
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert {item["source"] for item in review["items"]}.isdisjoint(
        {item["source"] for item in second.json()["items"]}
    )
    assert _witness_files(work) == before
    assert (manifest.read_bytes(), journal.read_bytes()) == evidence_before
    assert all(Path(row["source"]).is_file() for row in review["items"])


def test_cleanup_review_refuses_corrupted_private_journal_without_deletion(tmp_path):
    client, settings, work, job_id = _completed(tmp_path)
    folder = settings.reports_dir / "media_organizer-executions" / str(job_id)
    journal = folder / "manifest.json.manual-cleanup.json"
    journal.write_text('{"forged": true}', encoding="utf-8")
    before = _witness_files(work)
    refused = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review")
    assert refused.status_code == 409, refused.text
    assert _witness_files(work) == before
    assert journal.read_text(encoding="utf-8") == '{"forged": true}'


def test_cleanup_review_refuses_changed_public_file_without_touching_foreign(tmp_path):
    client, settings, work, job_id = _completed(tmp_path)
    folder = settings.reports_dir / "media_organizer-executions" / str(job_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["manifest"]
    final = Path(manifest["moves"][0]["final"])
    detached = final.with_name("owned-detached-for-audit.jpg")
    final.rename(detached)
    final.write_bytes(b"foreign-dont-touch")
    before = _witness_files(work)
    result = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review")
    assert result.status_code == 409, result.text
    assert _witness_files(work) == before
    assert final.read_bytes() == b"foreign-dont-touch"
    assert detached.is_file()


def test_cleanup_review_requires_admin_and_finished_handoff(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    job_id = queued.json()["job_id"]

    not_ready = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review")
    assert not_ready.status_code == 409

    client.cookies.clear()
    unauth = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review")
    assert unauth.status_code == 401


def test_cleanup_review_rejects_invalid_pagination(tmp_path):
    client, settings, work, job_id = _completed(tmp_path)
    for query in ("page=0", "page_size=0", "page_size=101"):
        result = client.get(
            f"/api/media-organizer/executions/{job_id}/cleanup-review?{query}"
        )
        assert result.status_code == 422, (query, result.text)


def _shared_completed(tmp_path, monkeypatch):
    """A worker and API share a pre-provisioned group-owned config root."""
    import os
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    monkeypatch.setenv("NFC_SHARED_CONFIG_GID", str(os.getegid()))
    config = tmp_path / "config"
    data = tmp_path / "data"
    config.mkdir()
    config.chmod(0o2770)
    data.mkdir()
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        MEDIA_ORGANIZER_EXECUTION_ENABLED=True,
        MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=True,
        ALLOW_MUTATION=True, ALLOW_DELETE=True,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123"
    }).status_code == 200
    unit = data / "Collection" / "NO.001"
    unit.mkdir(parents=True)
    (unit / "photo.jpg").write_bytes(b"synthetic-image")
    (unit / "another.png").write_bytes(b"synthetic-image-two")
    pid = preview(client, settings, unit)
    queued = execute_request(client, pid, unit)
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    assert worker(settings, job_id, name="synthetic-shared-group-worker")
    return client, settings, unit, job_id


def test_group_shared_private_evidence_is_readable_by_api_without_world_access(
    tmp_path, monkeypatch,
):
    import os
    import stat

    client, settings, work, job_id = _shared_completed(tmp_path, monkeypatch)
    folder = settings.reports_dir / "media_organizer-executions" / str(job_id)
    evidence = [
        folder / "manifest.json",
        folder / "manifest.json.manual-cleanup.json",
    ]
    assert (folder.parent.stat().st_mode & 0o7777) == 0o2770
    assert (folder.stat().st_mode & 0o7777) == 0o2770
    for path in evidence:
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
        assert path.stat().st_gid == os.getegid()
    report = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review")
    assert report.status_code == 200, report.text
    assert report.json()["cleanup_authorized"] is False
    assert report.json()["files_total"] == 2
    assert (work / "photo.jpg").read_bytes() == b"synthetic-image"


def test_group_shared_cleanup_journal_invalid_private_mode_fails_closed(
    tmp_path, monkeypatch,
):
    import stat

    client, settings, work, job_id = _shared_completed(tmp_path, monkeypatch)
    file = (settings.reports_dir / "media_organizer-executions" / str(job_id)
            / "manifest.json.manual-cleanup.json")
    file.chmod(0o600)
    before = file.read_bytes()
    refused = client.get(f"/api/media-organizer/executions/{job_id}/cleanup-review")
    assert refused.status_code == 409, refused.text
    assert file.read_bytes() == before
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert (work / "photo.jpg").read_bytes() == b"synthetic-image"
