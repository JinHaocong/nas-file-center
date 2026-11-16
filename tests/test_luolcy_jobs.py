"""Luolcy read-only Worker preview: admin API, per-package pagination and safety."""
from pathlib import Path

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
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
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
    path = root / "Else" / "Luolcy" / "2611" / day / author / name
    path.mkdir(parents=True)
    return path


def test_worker_preview_root_and_day_selection_are_paginated_read_only(tmp_path):
    client, root, settings = _app(tmp_path)
    p = _package(root, "疑心病", "New 1432.1MB")
    q = _package(root, "其他作者", "包二")
    r = _package(root, "最后作者", "包三", day="261116")
    (p / "001.jpg").write_bytes(b"image")
    (p / "001.mp4").write_bytes(b"video")
    nested = q / "视频A"
    nested.mkdir()
    (nested / "01.mp4").write_bytes(b"clip")
    (r / "photo.jpg").write_bytes(b"photo")
    selection = root / "Else" / "Luolcy" / "2611"

    result = client.post("/api/luolcy/previews", json={"selection": str(selection)})
    assert result.status_code == 200, result.text
    job_id = result.json()["job_id"]
    queued = client.get(f"/api/luolcy/previews/{job_id}")
    assert queued.status_code == 200
    assert queued.json()["summary"] is None
    assert process_work_job(settings, job_id)

    first = client.get(f"/api/luolcy/previews/{job_id}",
                       params={"page": 1, "page_size": 2})
    assert first.status_code == 200, first.text
    page = first.json()
    assert page["status"] == "completed"
    assert page["read_only"] is True
    assert page["summary"]["package_count"] == 3
    assert page["summary"]["ready_count"] == 2
    assert page["summary"]["skipped_count"] == 1
    assert len(page["packages"]) == 2
    assert page["progress"]["current"] == 3
    assert page["summary"]["needed_moves"] == 3

    second = client.get(f"/api/luolcy/previews/{job_id}",
                        params={"page": 2, "page_size": 2})
    assert second.status_code == 200
    assert len(second.json()["packages"]) == 1
    assert (p / "001.jpg").read_bytes() == b"image"
    assert (nested / "01.mp4").read_bytes() == b"clip"
    assert not (p / "P [1 5B]").exists()

    # A narrowed selection must not pull in the next day's resource pack.
    narrowed = client.post("/api/luolcy/previews", json={
        "selection": str(root / "Else" / "Luolcy" / "2611" / "261115"),
    })
    assert narrowed.status_code == 200
    day_job = narrowed.json()["job_id"]
    assert process_work_job(settings, day_job)
    day_result = client.get(f"/api/luolcy/previews/{day_job}").json()
    assert day_result["summary"]["package_count"] == 2


def test_worker_marks_unsafe_package_blocked_and_continues_read_only(tmp_path):
    client, root, settings = _app(tmp_path)
    p = _package(root, "authorA", "first")
    q = _package(root, "authorB", "second")
    (q / "001.jpg").write_bytes(b"photo")
    (q / "001.mp4").write_bytes(b"movie")
    p.joinpath("bad-link").symlink_to(q, target_is_directory=True)
    job = client.post("/api/luolcy/previews", json={
        "selection": str(root / "Else" / "Luolcy"),
    })
    assert job.status_code == 200, job.text
    job_id = job.json()["job_id"]
    assert process_work_job(settings, job_id)
    result = client.get(f"/api/luolcy/previews/{job_id}").json()
    assert result["summary"]["blocked_count"] == 1
    assert result["summary"]["ready_count"] == 1
    bad = next(x for x in result["packages"] if x["package"] == str(p))
    assert bad["status"] == "blocked"
    assert bad["conflicts"][0]["reason"] == "scan_error"
    assert p.joinpath("bad-link").is_symlink()
    assert (q / "001.mp4").read_bytes() == b"movie"


def test_worker_luolcy_enforces_auth_exact_root_and_bounded_pagination(tmp_path):
    client, root, settings = _app(tmp_path)
    selection = root / "Else" / "Luolcy"
    selection.mkdir(parents=True)
    assert client.post("/api/luolcy/previews", json={
        "selection": str(root),
    }).status_code == 409
    assert client.post("/api/luolcy/previews", json={
        "selection": str(selection), "extra": True,
    }).status_code == 422
    assert client.get("/api/luolcy/previews/999999").status_code == 404
    assert client.get("/api/luolcy/previews/1", params={"page_size": 1000}).status_code == 422

    client.cookies.clear()
    assert client.post("/api/luolcy/previews", json={
        "selection": str(selection),
    }).status_code == 401
