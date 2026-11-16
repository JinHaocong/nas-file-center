"""MediaPackage execute queue and Worker e2e run on isolated temporary files."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_session
from app.main import create_app
from app.tasks.recovery import acquire_worker_ownership
from app.worker import process_work_job


def _fixture(tmp_path: Path, *, mutation=True, deletion=True):
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data), MEDIA_PACKAGE_ROOT=str(data / "Else" / "Collection"),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=mutation, ALLOW_DELETE=deletion,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    root = data / "Else" / "Collection"
    return client, settings, root


def _preview(client, settings, package: Path):
    created = client.post("/api/media_package/previews", json={
        "selection": str(package),
    })
    assert created.status_code == 200, created.text
    pid = created.json()["job_id"]
    assert process_work_job(settings, pid)
    result = client.get(f"/api/media_package/previews/{pid}")
    assert result.status_code == 200, result.text
    assert result.json()["summary"]["ready_count"] == 1
    return pid


def test_confirmed_media_package_execute_moves_only_inner_files_and_deletes_empty_wrapper(tmp_path):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "作者" / "SampleBundle"
    a = package / "视频A"
    b = package / "视频B"
    a.mkdir(parents=True)
    b.mkdir()
    (a / "001.mp4").write_bytes(b"one")
    (b / "002.mp4").write_bytes(b"two")
    preview_id = _preview(client, settings, package)

    path = f"/api/media_package/previews/{preview_id}/execute"
    assert client.post(path, json={"confirmation": "wrong"}).status_code == 409
    assert not (package / "001.mp4").exists()
    start = client.post(path, json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_id}",
    })
    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]
    dup = client.post(path, json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_id}",
    })
    assert dup.status_code == 200
    assert dup.json()["job_id"] == job_id

    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "media_package-test-owner"
    assert acquire_worker_ownership(engine, factory, worker_id=worker_id)
    assert process_work_job(settings, job_id, session_factory=factory,
                            engine=engine, worker_id=worker_id)
    result = client.get(f"/api/media_package/executions/{job_id}")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    assert (package / "001.mp4").read_bytes() == b"one"
    assert (package / "002.mp4").read_bytes() == b"two"
    assert not a.exists()
    assert not b.exists()
    assert package.name == "SampleBundle"
    assert package.parent.name == "作者"


def test_stale_snapshot_cannot_move_a_changed_package(tmp_path):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "作者" / "New"
    inner = package / "video"
    inner.mkdir(parents=True)
    source = inner / "001.mp4"
    source.write_bytes(b"source")
    preview_id = _preview(client, settings, package)
    source.write_bytes(b"changed after preview")
    start = client.post(f"/api/media_package/previews/{preview_id}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_id}",
    })
    assert start.status_code == 200
    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "media_package-stale-test"
    assert acquire_worker_ownership(engine, factory, worker_id=worker_id)
    assert process_work_job(settings, start.json()["job_id"], session_factory=factory,
                            engine=engine, worker_id=worker_id) is False
    assert source.read_bytes() == b"changed after preview"
    assert not (package / "001.mp4").exists()


def test_mutation_gates_block_execution_queue_and_no_approval_is_implicit(tmp_path):
    client, settings, root = _fixture(tmp_path, deletion=False)
    package = root / "2611" / "261115" / "作者" / "New"
    inner = package / "sub"
    inner.mkdir(parents=True)
    (inner / "001.mp4").write_bytes(b"one")
    pid = _preview(client, settings, package)
    result = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    assert result.status_code == 409
    assert (inner / "001.mp4").exists()


def test_execute_queue_rejects_preview_with_any_conflict(tmp_path):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "作者" / "New"
    (package / "A").mkdir(parents=True)
    (package / "B").mkdir()
    (package / "A" / "same.jpg").write_bytes(b"one")
    (package / "B" / "same.jpg").write_bytes(b"two")
    (package / "extra.mp4").write_bytes(b"video")
    (package / "P_1").mkdir()
    created = client.post("/api/media_package/previews", json={
        "selection": str(package),
    })
    assert created.status_code == 200
    pid = created.json()["job_id"]
    assert process_work_job(settings, pid)
    body = client.get(f"/api/media_package/previews/{pid}").json()
    assert body["summary"]["blocked_count"] == 1
    result = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    assert result.status_code == 409
    assert (package / "A" / "same.jpg").exists()
    assert (package / "B" / "same.jpg").exists()
