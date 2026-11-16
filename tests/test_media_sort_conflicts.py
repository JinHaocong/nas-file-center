"""Conflict triage on large media-sort previews is paginated and fail-closed."""
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.batch import media_sort
from app.batch.media_sort_jobs import _paths, _status_index_path
from app.config import Settings
from app.main import create_app
from app.models import BatchPlanItem
from app.worker import process_work_job


def _scenario(tmp_path, monkeypatch, *, all_conflict: bool = False):
    root = tmp_path / "data"
    config = tmp_path / "config"
    root.mkdir()
    config.mkdir()
    names = ("good-a.jpg", "bad-b.mp4", "good-c.png", "bad-d.jpg", "good-e.mp4")
    for name in names:
        (root / name).write_bytes(name.encode())

    real_validator = media_sort.validate_mutation_destination

    def simulate_nas_conflict(path, *args, **kwargs):
        if all_conflict or Path(path).name.startswith("bad-"):
            raise ValueError("目标路径被占用或权限冲突：请手动检查")
        return real_validator(path, *args, **kwargs)

    monkeypatch.setattr(media_sort, "validate_mutation_destination", simulate_nas_conflict)
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=True, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    queued = client.post("/api/media-sort/previews", json={
        "parent": str(root), "recursive": False, "smart_skip": False,
    })
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    assert process_work_job(settings, job_id) is True
    return client, root, settings, job_id, names


def test_conflict_filter_and_explicit_skip_create_only_safe_plan(tmp_path, monkeypatch):
    client, root, settings, job_id, names = _scenario(tmp_path, monkeypatch)
    url = f"/api/media-sort/previews/{job_id}"
    all_rows = client.get(url, params={"page_size": 20}).json()
    assert all_rows["summary"]["count"] == 5
    assert all_rows["summary"]["ready_count"] == 3
    assert all_rows["summary"]["conflict_count"] == 2
    assert all_rows["item_total"] == 5
    assert all_rows["item_filter"] == "all"

    conflict = client.get(url, params={
        "item_filter": "conflict", "page": 1, "page_size": 1,
    }).json()
    assert conflict["item_total"] == 2
    assert len(conflict["items"]) == 1
    assert conflict["items"][0]["conflict"] is True
    assert "目标路径" in conflict["items"][0]["conflict_reason"]
    assert str(root) in conflict["items"][0]["source"]
    second = client.get(url, params={
        "item_filter": "conflict", "page": 2, "page_size": 1,
    }).json()
    assert second["item_total"] == 2
    assert len(second["items"]) == 1
    assert second["items"][0]["source"] != conflict["items"][0]["source"]

    ready = client.get(url, params={"item_filter": "ready", "page_size": 20}).json()
    assert ready["item_total"] == 3
    assert all(not row["conflict"] for row in ready["items"])
    assert {Path(row["source"]).name for row in ready["items"]} == {
        "good-a.jpg", "good-c.png", "good-e.mp4",
    }
    assert client.get(url, params={"item_filter": "somewhere"}).status_code == 422

    plan_url = f"/api/media-sort/previews/{job_id}/plan"
    assert client.post(plan_url).status_code == 409
    assert client.post(plan_url, json={"skip_conflicts": False}).status_code == 409
    assert client.post(plan_url, json={"skip_conflicts": "yes"}).status_code == 422
    assert client.post(plan_url, json={"skip_conflicts": True, "delete_conflicts": True}).status_code == 422

    started = client.post(plan_url, json={"skip_conflicts": True})
    assert started.status_code == 200, started.text
    plan_job_id = started.json()["job_id"]
    assert client.post(plan_url, json={"skip_conflicts": True}).json()["job_id"] == plan_job_id
    assert process_work_job(settings, plan_job_id) is True
    details = client.get(f"/api/media-sort/plan-jobs/{plan_job_id}").json()
    assert details["status"] == "completed"
    plan_id = details["plan_id"]
    plan = client.get(f"/api/plans/{plan_id}").json()
    assert plan["status"] == "draft"
    assert plan["expected_changes"] == 3
    assert plan["metadata"]["conflict_policy"] == "skip"
    assert plan["metadata"]["skipped_conflict_count"] == 2

    # No conflict record ever becomes a Move Plan item.
    from app.service import FileCenterService
    service = FileCenterService(settings)
    with service.SessionLocal() as session:
        rows = session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence)
        ).all()
    assert len(rows) == 3
    assert [row.sequence for row in rows] == [1, 2, 3]
    assert {Path(row.source_path).name for row in rows} == {
        "good-a.jpg", "good-c.png", "good-e.mp4",
    }
    for name in names:
        assert (root / name).read_bytes() == name.encode()

    freeze = client.post(f"/api/plans/{plan_id}/stage-tasks/freeze")
    assert freeze.status_code == 200
    assert process_work_job(settings, freeze.json()["job_id"]) is True
    validate = client.post(f"/api/plans/{plan_id}/stage-tasks/validate")
    assert validate.status_code == 200
    assert process_work_job(settings, validate.json()["job_id"]) is True
    execute = client.post(f"/api/plans/{plan_id}/execute")
    assert execute.status_code == 200, execute.text
    assert process_work_job(settings, execute.json()["work_job_id"]) is True
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "completed"
    for name in ("bad-b.mp4", "bad-d.jpg"):
        assert (root / name).read_bytes() == name.encode()
    for name in ("good-a.jpg", "good-c.png"):
        assert not (root / name).exists()
        assert (root / "P" / name).read_bytes() == name.encode()
    assert (root / "V" / "good-e.mp4").read_bytes() == b"good-e.mp4"


def test_all_conflicts_cannot_create_empty_plan(tmp_path, monkeypatch):
    client, root, settings, job_id, names = _scenario(tmp_path, monkeypatch, all_conflict=True)
    summary = client.get(f"/api/media-sort/previews/{job_id}").json()["summary"]
    assert summary["count"] == summary["conflict_count"] == 5
    assert summary["ready_count"] == 0
    response = client.post(f"/api/media-sort/previews/{job_id}/plan", json={"skip_conflicts": True})
    assert response.status_code == 409
    for name in names:
        assert (root / name).read_bytes() == name.encode()
    assert not (root / "P").exists()


def test_status_index_filters_late_pages_without_scanning_all_rows(tmp_path, monkeypatch):
    from app.batch import media_sort_jobs as jobs
    root = tmp_path / "data"
    root.mkdir()
    items = root / "preview.items.jsonl"
    filtered = {"conflict": [], "ready": []}
    with (items.open("w", encoding="utf-8") as stream,
          jobs._write_new_binary(jobs._status_index_path(items, "conflict")) as bad,
          jobs._write_new_binary(jobs._status_index_path(items, "ready")) as good):
        for i in range(1500):
            row = {"source": f"/data/{i}.jpg", "conflict": i % 3 == 0}
            target = bad if row["conflict"] else good
            target.write(jobs.struct.pack("<Q", stream.tell()))
            stream.write(jobs.json.dumps(row) + "\n")
            filtered["conflict" if row["conflict"] else "ready"].append(row)

    for kind in ("conflict", "ready"):
        expected = filtered[kind][250:269]
        actual = jobs._read_filtered_page(items, item_filter=kind, offset=250, page_size=19)
        assert actual == expected

    # Old previews without status indexes still work (streaming fallback).
    jobs._status_index_path(items, "ready").unlink()
    assert jobs._read_filtered_page(items, item_filter="ready", offset=250, page_size=19) == filtered["ready"][250:269]
    # Index corruption fails closed and cannot silently return mismatched rows.
    offset_path = jobs._status_index_path(items, "conflict")
    offset_path.write_bytes(jobs.struct.pack("<Q", 2**48))
    with pytest.raises((ValueError, OSError)):
        jobs._read_filtered_page(items, item_filter="conflict", offset=0, page_size=3)
