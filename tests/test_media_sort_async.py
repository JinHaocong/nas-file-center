"""Large media-sort scans use durable Worker progress and paginated Preview results."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.batch import media_sort
from app.batch.media_sort import preview_media_sort
from app.config import Settings
from app.main import create_app
from app.worker import process_work_job


def _client(tmp_path: Path, *, allow_mutation: bool = False):
    root = tmp_path / "data"
    config = tmp_path / "config"
    root.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=allow_mutation, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    return client, root, settings


def test_streaming_scan_beyond_old_50k_limit_without_collecting_results(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "cover.jpg").write_bytes(b"image")
    (root / "clip.mp4").write_bytes(b"video")
    for i in range(120):
        (root / f"{i:04}.txt").touch()
    # A small synthetic stream proves the new scanner is not tied to the old
    # 50,000-entry cutoff. Production cap is 2,000,000.
    assert media_sort.MAX_RECURSIVE_ENTRIES > 50_000
    assert media_sort.MAX_IMMEDIATE_ENTRIES > 50_000
    monkeypatch.setattr(media_sort, "MAX_RECURSIVE_ENTRIES", 200)
    progress = []
    batches = []
    skipped = []
    result = preview_media_sort(
        root, recursive=True, allowed_roots=[root],
        on_rows=lambda x: batches.extend(x),
        on_skipped=lambda x: skipped.extend(x),
        on_progress=lambda x: progress.append(x),
        collect_items=False,
    )
    assert result["count"] == 2
    assert result["items"] == []  # Batches are streamed, not buffered.
    assert len(batches) == 2
    assert result["scanned_entries"] == 122
    assert progress and progress[-1]["scanned_entries"] == 122
    assert progress[-1]["pending_directories"] == 0
    assert not (root / "P").exists()


def test_worker_preview_pages_persist_across_requests_and_support_progress(tmp_path):
    client, root, settings = _client(tmp_path)
    (root / "one.jpg").write_bytes(b"one")
    (root / "two.png").write_bytes(b"two")
    (root / "clip.mp4").write_bytes(b"clip")
    already = root / "视频"
    already.mkdir()
    (already / "movie.MKV").write_bytes(b"original")
    result = client.post("/api/media-sort/previews", json={
        "parent": str(root), "recursive": True, "smart_skip": True,
    })
    assert result.status_code == 200, result.text
    job_id = result.json()["job_id"]
    initial = client.get(f"/api/media-sort/previews/{job_id}")
    assert initial.status_code == 200
    assert initial.json()["status"] == "queued"
    assert initial.json()["summary"] is None
    assert process_work_job(settings, job_id)

    first = client.get(f"/api/media-sort/previews/{job_id}",
                       params={"page": 1, "page_size": 2, "skip_page_size": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "completed"
    assert body["summary"]["count"] == 3
    assert body["summary"]["scanned_directories"] == 2
    assert body["progress"]["scanned_entries"] >= 4
    assert len(body["items"]) == 2
    second = client.get(f"/api/media-sort/previews/{job_id}",
                        params={"page": 2, "page_size": 2, "skip_page_size": 2})
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["summary"]["count"] == 3
    assert body["summary"]["skipped_directory_count"] >= 1
    assert (already / "movie.MKV").read_bytes() == b"original"
    assert not (root / "P").exists()


def test_full_worker_preview_generate_freeze_validate_execute(tmp_path):
    client, root, settings = _client(tmp_path, allow_mutation=True)
    album = root / "album"
    album.mkdir()
    (root / "cover.jpg").write_bytes(b"cover")
    (root / "clip.mp4").write_bytes(b"video")
    (album / "travel.png").write_bytes(b"travel")
    (album / "film.MP4").write_bytes(b"film")

    queued = client.post("/api/media-sort/previews", json={
        "parent": str(root), "recursive": True, "smart_skip": True,
    })
    assert queued.status_code == 200, queued.text
    preview_id = queued.json()["job_id"]
    assert process_work_job(settings, preview_id)
    result = client.get(f"/api/media-sort/previews/{preview_id}").json()
    assert result["summary"]["count"] == 4
    plan_created = client.post(f"/api/media-sort/previews/{preview_id}/plan")
    assert plan_created.status_code == 200, plan_created.text
    plan_job_id = plan_created.json()["job_id"]
    duplicate = client.post(f"/api/media-sort/previews/{preview_id}/plan")
    assert duplicate.json()["job_id"] == plan_job_id
    assert process_work_job(settings, plan_job_id)
    generated = client.get(f"/api/media-sort/plan-jobs/{plan_job_id}").json()
    assert generated["status"] == "completed"
    assert generated["progress"]["current"] == 4
    plan_id = generated["plan_id"]
    assert plan_id > 0
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "draft"

    freeze = client.post(f"/api/plans/{plan_id}/stage-tasks/freeze")
    assert freeze.status_code == 200, freeze.text
    freeze_id = freeze.json()["job_id"]
    concurrent = client.post(f"/api/plans/{plan_id}/stage-tasks/freeze")
    assert concurrent.status_code == 409
    assert process_work_job(settings, freeze_id)
    stage = client.get(f"/api/plans/{plan_id}/stage-task").json()["job"]
    assert stage["status"] == "completed"
    assert stage["stage"] == "freeze"
    assert stage["progress"]["current"] == 4
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "frozen"

    validate = client.post(f"/api/plans/{plan_id}/stage-tasks/validate")
    assert validate.status_code == 200, validate.text
    validate_id = validate.json()["job_id"]
    assert process_work_job(settings, validate_id)
    stage = client.get(f"/api/plans/{plan_id}/stage-task").json()["job"]
    assert stage["stage"] == "validate"
    assert stage["status"] == "completed"
    assert stage["progress"]["current"] == 4
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "ready"

    execute = client.post(f"/api/plans/{plan_id}/execute")
    assert execute.status_code == 200, execute.text
    exec_job_id = execute.json()["work_job_id"]
    assert process_work_job(settings, exec_job_id)
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "completed"
    task = client.get(f"/api/tasks/{exec_job_id}").json()
    assert task["progress"]["current"] >= 4
    assert (root / "P" / "cover.jpg").read_bytes() == b"cover"
    assert (root / "V" / "clip.mp4").read_bytes() == b"video"
    assert (album / "P" / "travel.png").read_bytes() == b"travel"
    assert (album / "V" / "film.MP4").read_bytes() == b"film"


def test_worker_over_limit_reports_failure_without_publishing_partial_preview(tmp_path, monkeypatch):
    client, root, settings = _client(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    (root / "one.jpg").write_bytes(b"one")
    (root / "two.mp4").write_bytes(b"two")
    (nested / "more.mp4").write_bytes(b"more")
    monkeypatch.setattr(media_sort, "MAX_RECURSIVE_ENTRIES", 2)

    res = client.post("/api/media-sort/previews", json={
        "parent": str(root), "recursive": True, "smart_skip": False,
    })
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert process_work_job(settings, job_id) is False
    status = client.get(f"/api/media-sort/previews/{job_id}").json()
    assert status["status"] == "failed"
    assert "Too many recursive entries" in status["error"]
    assert status["summary"] is None
    assert client.post(f"/api/media-sort/previews/{job_id}/plan").status_code == 409
    assert (root / "one.jpg").exists()
    assert not (root / "P").exists()


def test_preview_task_permissions_and_pagination_boundaries(tmp_path):
    client, root, settings = _client(tmp_path)
    client.cookies.clear()
    assert client.post("/api/media-sort/previews", json={
        "parent": str(root), "recursive": True, "smart_skip": True,
    }).status_code == 401
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    assert client.get("/api/media-sort/previews/999999").status_code == 404
    assert client.get("/api/media-sort/previews/1000000", params={"page_size": 1000}).status_code == 422
    assert client.post("/api/plans/999999/stage-tasks/freeze").status_code == 404
