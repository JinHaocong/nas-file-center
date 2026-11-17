"""MediaPackage read-only Worker preview: admin API, per-package pagination and safety."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.worker import process_work_job


def _app(tmp_path):
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data), MEDIA_PACKAGE_ROOT=str(data / "Else" / "Collection"),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    return client, data, settings


def _package(root: Path, author: str, name: str, *, day: str = "261115") -> Path:
    path = root / "Else" / "Collection" / "2611" / day / author / name
    path.mkdir(parents=True)
    return path


def test_worker_preview_root_and_day_selection_are_paginated_read_only(tmp_path):
    client, root, settings = _app(tmp_path)
    p = _package(root, "SampleAuthor", "SampleBundle")
    q = _package(root, "其他作者", "包二")
    r = _package(root, "最后作者", "包三", day="261116")
    (p / "001.jpg").write_bytes(b"image")
    (p / "001.mp4").write_bytes(b"video")
    nested = q / "视频A"
    nested.mkdir()
    (nested / "01.mp4").write_bytes(b"clip")
    (r / "photo.jpg").write_bytes(b"photo")
    selection = root / "Else" / "Collection" / "2611"

    result = client.post("/api/media_package/previews", json={"selection": str(selection)})
    assert result.status_code == 200, result.text
    job_id = result.json()["job_id"]
    queued = client.get(f"/api/media_package/previews/{job_id}")
    assert queued.status_code == 200
    assert queued.json()["summary"] is None
    assert process_work_job(settings, job_id)

    first = client.get(f"/api/media_package/previews/{job_id}",
                       params={"page": 1, "page_size": 2})
    assert first.status_code == 200, first.text
    page = first.json()
    assert page["status"] == "completed"
    assert page["read_only"] is True
    assert page["summary"]["package_count"] == 3
    assert page["summary"]["ready_count"] == 3
    assert page["summary"]["skipped_count"] == 0
    assert len(page["packages"]) == 2
    assert page["progress"]["current"] == 3
    assert page["summary"]["needed_moves"] == 4

    second = client.get(f"/api/media_package/previews/{job_id}",
                        params={"page": 2, "page_size": 2})
    assert second.status_code == 200
    assert len(second.json()["packages"]) == 1
    assert (p / "001.jpg").read_bytes() == b"image"
    assert (nested / "01.mp4").read_bytes() == b"clip"
    assert not (p / "P [1 5B]").exists()

    # A narrowed selection must not pull in the next day's resource pack.
    narrowed = client.post("/api/media_package/previews", json={
        "selection": str(root / "Else" / "Collection" / "2611" / "261115"),
    })
    assert narrowed.status_code == 200
    day_job = narrowed.json()["job_id"]
    assert process_work_job(settings, day_job)
    day_result = client.get(f"/api/media_package/previews/{day_job}").json()
    assert day_result["summary"]["package_count"] == 2


def test_worker_marks_unsafe_package_blocked_and_continues_read_only(tmp_path):
    client, root, settings = _app(tmp_path)
    p = _package(root, "authorA", "first")
    q = _package(root, "authorB", "second")
    (q / "001.jpg").write_bytes(b"photo")
    (q / "001.mp4").write_bytes(b"movie")
    p.joinpath("bad-link").symlink_to(q, target_is_directory=True)
    job = client.post("/api/media_package/previews", json={
        "selection": str(root / "Else" / "Collection"),
    })
    assert job.status_code == 200, job.text
    job_id = job.json()["job_id"]
    assert process_work_job(settings, job_id)
    result = client.get(f"/api/media_package/previews/{job_id}").json()
    assert result["summary"]["blocked_count"] == 1
    assert result["summary"]["ready_count"] == 1
    bad = next(x for x in result["packages"] if x["package"] == str(p))
    assert bad["status"] == "blocked"
    assert bad["conflicts"][0]["reason"] == "scan_error"
    assert p.joinpath("bad-link").is_symlink()
    assert (q / "001.mp4").read_bytes() == b"movie"

    # Filter the entire frozen report *before* pagination, even when the
    # matching row would not be present on the first unfiltered page.
    blocked = client.get(f"/api/media_package/previews/{job_id}", params={
        "status_filter": "blocked", "page": 1, "page_size": 1,
    })
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["summary"]["package_count"] == 2
    assert blocked.json()["filtered_total"] == 1
    assert [x["package"] for x in blocked.json()["packages"]] == [str(p)]

    ready = client.get(f"/api/media_package/previews/{job_id}", params={
        "status_filter": "ready", "page": 1, "page_size": 1,
    })
    assert ready.status_code == 200, ready.text
    assert ready.json()["filtered_total"] == 1
    assert [x["package"] for x in ready.json()["packages"]] == [str(q)]

    assert client.get(f"/api/media_package/previews/{job_id}", params={
        "status_filter": "blocked", "page": 2, "page_size": 1,
    }).json()["packages"] == []
    assert client.get(f"/api/media_package/previews/{job_id}", params={
        "status_filter": "skipped",
    }).json()["filtered_total"] == 0
    assert client.get(f"/api/media_package/previews/{job_id}", params={
        "status_filter": "already_organized",
    }).json()["filtered_total"] == 0
    assert client.get(f"/api/media_package/previews/{job_id}", params={
        "status_filter": "all", "page": 1, "page_size": 1,
    }).json()["filtered_total"] == 2
    assert client.get(f"/api/media_package/previews/{job_id}", params={
        "status_filter": "unknown",
    }).status_code == 409


def test_worker_media_package_enforces_auth_exact_root_and_bounded_pagination(tmp_path):
    client, root, settings = _app(tmp_path)
    selection = root / "Else" / "Collection"
    selection.mkdir(parents=True)
    assert client.post("/api/media_package/previews", json={
        "selection": str(root),
    }).status_code == 409
    assert client.post("/api/media_package/previews", json={
        "selection": str(selection), "extra": True,
    }).status_code == 422
    assert client.get("/api/media_package/previews/999999").status_code == 404
    assert client.get("/api/media_package/previews/1", params={"page_size": 1000}).status_code == 422

    client.cookies.clear()
    assert client.post("/api/media_package/previews", json={
        "selection": str(selection),
    }).status_code == 401


def test_media_package_scope_requires_deploy_private_absolute_root(tmp_path):
    from app.batch.media_package_jobs import _root
    data = tmp_path / "data"
    data.mkdir()
    base = {"_env_file": None, "DATA_MOUNT": str(data),
            "ALLOWED_ROOTS": str(data)}
    unconfigured = Settings(**base)
    with pytest.raises(ValueError, match="MEDIA_PACKAGE_ROOT is not configured"):
        _root(unconfigured)
    relative = Settings(**base, MEDIA_PACKAGE_ROOT="private/relative/path")
    with pytest.raises(ValueError, match="absolute path"):
        _root(relative)
    outside = Settings(**base, MEDIA_PACKAGE_ROOT=str(tmp_path / "outside"))
    with pytest.raises(ValueError, match="outside configured roots"):
        _root(outside)
    protected = Settings(**base, MEDIA_PACKAGE_ROOT=str(data / "Else" / "Collection"))
    assert _root(protected) == data / "Else" / "Collection"


def test_deleted_preview_job_id_is_not_reused_when_reports_remain(tmp_path):
    client, root, settings = _app(tmp_path)
    package = _package(root, "SampleAuthor", "SampleBundle")
    (package / "image.jpg").write_bytes(b"img")
    (package / "video.mp4").write_bytes(b"video")
    selection = str(root / "Else" / "Collection" / "2611")
    first = client.post("/api/media_package/previews", json={"selection": selection})
    assert first.status_code == 200, first.text
    old_id = first.json()["job_id"]
    assert process_work_job(settings, old_id)
    old_report = (settings.reports_dir / "media_package-previews"
                  / f"{old_id}.packages.jsonl")
    before = old_report.read_bytes()

    # SQLite can reuse a deleted max WorkJob ID. Report evidence must not.
    deleted = client.delete(f"/api/tasks/{old_id}")
    assert deleted.status_code == 200, deleted.text
    second = client.post("/api/media_package/previews", json={"selection": selection})
    assert second.status_code == 200, second.text
    new_id = second.json()["job_id"]
    assert new_id > old_id
    assert old_report.read_bytes() == before
    assert process_work_job(settings, new_id)


def test_existing_preview_artifact_is_not_silently_removed(tmp_path):
    client, root, settings = _app(tmp_path)
    package = _package(root, "SampleAuthor", "SampleBundle")
    (package / "image.jpg").write_bytes(b"img")
    (package / "video.mp4").write_bytes(b"video")
    selection = str(root / "Else" / "Collection" / "2611")
    response = client.post("/api/media_package/previews", json={"selection": selection})
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    artifact = (settings.reports_dir / "media_package-previews"
                / f"{job_id}.packages.jsonl")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"foreign report evidence")
    process_work_job(settings, job_id)
    assert artifact.read_bytes() == b"foreign report evidence"
    status = client.get(f"/api/media_package/previews/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
