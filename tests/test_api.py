from pathlib import Path

from fastapi.testclient import TestClient


def make_client(tmp_path, *, allow_mutation=False, allow_delete=False):
    data = tmp_path / "data"; data.mkdir()
    config = tmp_path / "config"; config.mkdir()
    from app.config import Settings
    from app.main import create_app
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=allow_mutation,
        ALLOW_DELETE=allow_delete,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
    return client, data


def test_health(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["allow_mutation"] is False


def test_path_match_preview_and_rename_preview_are_read_only(tmp_path):
    client, data = make_client(tmp_path)
    a = data / "A"; b = data / "B"; a.mkdir(); b.mkdir()
    (a / "same.jpg").write_text("a"); (b / "same.jpg").write_text("b")

    matched = client.post("/api/path-match/preview", json={"roots":[str(a), str(b)], "mode":"relative-path"})
    assert matched.status_code == 200
    assert matched.json()["groups"][0]["key"] == "same.jpg"

    renamed = client.post("/api/rename/preview", json={"paths":[str(a / "same.jpg")], "prefix":"NEW-"})
    assert renamed.status_code == 200
    assert renamed.json()["items"][0]["target"].endswith("NEW-same.jpg")
    assert (a / "same.jpg").exists()


def test_plan_freeze_and_mutation_guard(tmp_path):
    client, data = make_client(tmp_path, allow_mutation=False)
    src = data / "x.txt"; src.write_text("x")
    created = client.post("/api/plans", json={
        "name":"touch one",
        "kind":"touch",
        "items":[{"operation":"touch", "source":str(src)}],
    })
    assert created.status_code == 200
    plan_id = created.json()["id"]
    frozen = client.post(f"/api/plans/{plan_id}/freeze")
    assert frozen.status_code == 200 and frozen.json()["status"] == "frozen"
    val = client.post(f"/api/plans/{plan_id}/validate")
    assert val.status_code == 200
    executed = client.post(f"/api/plans/{plan_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "queued"
    from app.worker import process_work_job
    process_work_job(client.app.state.settings, executed.json()["work_job_id"])
    plan_after = client.get(f"/api/plans/{plan_id}").json()
    assert plan_after["status"] == "partial"
    assert plan_after["items"][0]["state"] == "skipped"


def test_quarantine_plan_executes_when_mutation_enabled(tmp_path):
    client, data = make_client(tmp_path, allow_mutation=True)
    src = data / "x.txt"; src.write_text("x")
    created = client.post("/api/plans", json={
        "name":"trash one",
        "kind":"quarantine",
        "items":[{"operation":"quarantine", "source":str(src), "expected_size":1}],
    })
    plan_id = created.json()["id"]
    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")
    executed = client.post(f"/api/plans/{plan_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "queued"
    from app.worker import process_work_job
    process_work_job(client.app.state.settings, executed.json()["work_job_id"])
    plan_after = client.get(f"/api/plans/{plan_id}").json()
    assert plan_after["status"] == "completed"
    assert list((data / ".trash" / f"task-{executed.json()['work_job_id']}").rglob("x.q-*.txt"))


def test_scan_enqueue_and_detail_api(tmp_path):
    client, data = make_client(tmp_path)
    a = data / "A"; b = data / "B"; a.mkdir(); b.mkdir()
    created = client.post("/api/scans", json={"name":"AB", "roots":[str(a), str(b)], "isolate":True})
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "queued"
    detail = client.get(f"/api/scans/{body['scan_job_id']}")
    assert detail.status_code == 200
    assert detail.json()["mode"] == "isolate"



def test_index_enqueue_api(tmp_path):
    client, data = make_client(tmp_path)
    root = data / "A"; root.mkdir(); (root / "x").write_text("x")
    created = client.post("/api/indexes", json={"root":str(root)})
    assert created.status_code == 200
    assert created.json()["status"] == "queued"
    job = client.get(f"/api/work-jobs/{created.json()['work_job_id']}")
    assert job.status_code == 200
    assert job.json()["kind"] == "index-root"
