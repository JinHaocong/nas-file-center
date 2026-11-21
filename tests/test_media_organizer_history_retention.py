"""Task-history dismissal must preserve explicit organizer recovery authority."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.db import create_engine_and_session
from app.models import TaskEvent, WorkJob
from tests.test_media_organizer_cleanup_jobs import _published
from tests.test_media_organizer_execute_jobs import worker


OWNER = "synthetic-original-worker"


def _queue(client, execution_id, token):
    response = client.post(f"/api/media-organizer/executions/{execution_id}/cleanup",
                           json={"confirmation": token})
    assert response.status_code == 200, response.text
    return response.json()["job_id"]


def _recover(client, failed_id, token):
    response = client.post(f"/api/media-organizer/cleanups/{failed_id}/recover", json={
        "confirmation": f"RECOVER_CLEANUP_JOB_{failed_id}_{token}",
    })
    assert response.status_code == 200, response.text
    return response.json()["job_id"]


def _failed_chain(tmp_path, monkeypatch):
    client, settings, unit, execution_id, token, issuer = _published(tmp_path, monkeypatch)
    cleanup_id = _queue(client, execution_id, token)
    issuer["allowed"] = False
    assert worker(settings, cleanup_id, name=OWNER) is False
    issuer["allowed"] = True
    recovery_id = _recover(client, cleanup_id, token)
    _, factory = create_engine_and_session(settings.database_path)
    return client, settings, factory, execution_id, cleanup_id, recovery_id, token


def _authority(factory, ids):
    with factory() as session:
        result = {}
        for job_id in ids:
            job = session.get(WorkJob, job_id)
            assert job is not None, "history clearing destroyed organizer authority"
            result[job_id] = (job.status, job.state_json, json.loads(job.checkpoint_json),
                              job.retry_of, tuple(session.scalars(select(TaskEvent.id).where(
                                  TaskEvent.job_id == job_id).order_by(TaskEvent.id))))
        return result


def _assert_dismissed(factory, before):
    after = _authority(factory, before)
    for job_id, (status, state, checkpoint, retry_of, events) in after.items():
        assert checkpoint.pop("_task_queue_dismissed") is True
        assert (status, state, checkpoint, retry_of, events) == before[job_id]


@pytest.mark.parametrize("recovery_status", ["queued", "running", "failed"])
def test_delete_history_preserves_ancestors_for_cleanup_recovery(
    tmp_path, monkeypatch, recovery_status,
):
    client, settings, factory, execution_id, cleanup_id, recovery_id, token = _failed_chain(
        tmp_path, monkeypatch,
    )
    with factory() as session:
        session.get(WorkJob, recovery_id).status = recovery_status
        session.commit()
    before = _authority(factory, [execution_id, cleanup_id])

    for job_id in before:
        response = client.delete(f"/api/tasks/{job_id}")
        assert response.status_code == 200, response.text
        assert response.json() == {"deleted": True, "id": job_id}

    _assert_dismissed(factory, before)
    with factory() as session:
        assert session.get(WorkJob, recovery_id).retry_of == cleanup_id
    visible = {item["id"] for item in client.get("/api/tasks").json()["items"]}
    assert execution_id not in visible and cleanup_id not in visible
    assert recovery_id in visible
    if recovery_status == "failed":
        recovery_id = _recover(client, recovery_id, token)
    assert worker(settings, recovery_id, name=OWNER)
    assert client.get(f"/api/media-organizer/executions/{execution_id}").json()["finalized"]


@pytest.mark.parametrize("statuses", [["completed"], ["completed", "failed"]])
def test_clear_history_preserves_recovery_authority_and_status_filter(
    tmp_path, monkeypatch, statuses,
):
    client, settings, factory, execution_id, cleanup_id, recovery_id, token = _failed_chain(
        tmp_path, monkeypatch,
    )
    before = _authority(factory, [execution_id, cleanup_id])
    with factory() as session:
        unrelated = WorkJob(kind="index-root", status="completed")
        session.add(unrelated)
        session.flush()
        unrelated_id = unrelated.id
        session.add(TaskEvent(job_id=unrelated_id, event_type="completed", message="done"))
        session.commit()

    response = client.post("/api/tasks/clear-history", json={"statuses": statuses})
    assert response.status_code == 200, response.text
    # One preview and one unrelated job are deleted; organizer rows are hidden.
    assert response.json() == {"deleted_count": 4 if "failed" in statuses else 3}
    _assert_dismissed(factory, {execution_id: before[execution_id]})
    if "failed" in statuses:
        _assert_dismissed(factory, {cleanup_id: before[cleanup_id]})
    else:
        assert _authority(factory, [cleanup_id]) == {cleanup_id: before[cleanup_id]}
    with factory() as session:
        assert session.get(WorkJob, unrelated_id) is None
        assert not list(session.scalars(select(TaskEvent.id).where(
            TaskEvent.job_id == unrelated_id)))
        assert session.get(WorkJob, recovery_id).retry_of == cleanup_id
    second = client.post("/api/tasks/clear-history", json={"statuses": statuses})
    assert second.status_code == 200, second.text
    assert second.json() == {"deleted_count": 0}
    assert worker(settings, recovery_id, name=OWNER)
    assert client.get(f"/api/media-organizer/executions/{execution_id}").json()["finalized"]


@pytest.mark.parametrize("operation", ["delete", "clear"])
def test_finalized_organizer_history_remains_durable_and_idempotent(
    tmp_path, monkeypatch, operation,
):
    client, settings, _, execution_id, token, _ = _published(tmp_path, monkeypatch)
    cleanup_id = _queue(client, execution_id, token)
    assert worker(settings, cleanup_id, name=OWNER)
    _, factory = create_engine_and_session(settings.database_path)
    before = _authority(factory, [execution_id, cleanup_id])

    if operation == "delete":
        for job_id in before:
            assert client.delete(f"/api/tasks/{job_id}").status_code == 200
    else:
        assert client.post("/api/tasks/clear-history", json={}).status_code == 200

    _assert_dismissed(factory, before)
    with factory() as session:
        checkpoint = json.loads(session.get(WorkJob, execution_id).checkpoint_json)
        assert checkpoint["finalized_by_cleanup_job_id"] == cleanup_id
    assert _queue(client, execution_id, token) == cleanup_id
    assert client.get(f"/api/media-organizer/executions/{execution_id}").json()["finalized"]


def test_failed_original_execution_is_dismissed_without_losing_frozen_phase(tmp_path, monkeypatch):
    client, settings, _, execution_id, _, _ = _published(tmp_path, monkeypatch)
    _, factory = create_engine_and_session(settings.database_path)
    with factory() as session:
        job = session.get(WorkJob, execution_id)
        job.status = "failed"
        job.checkpoint_json = json.dumps({"schema_version": 1, "phase": "published",
                                          "frozen_job_id": execution_id})
        session.commit()
    before = _authority(factory, [execution_id])

    assert client.delete(f"/api/tasks/{execution_id}").status_code == 200

    _assert_dismissed(factory, before)


@pytest.mark.parametrize("operation", ["delete", "clear"])
def test_malformed_organizer_authority_is_preserved_verbatim(tmp_path, monkeypatch, operation):
    client, settings, _, execution_id, _, _ = _published(tmp_path, monkeypatch)
    _, factory = create_engine_and_session(settings.database_path)
    with factory() as session:
        session.get(WorkJob, execution_id).checkpoint_json = "{damaged-authority"
        session.commit()

    response = (client.delete(f"/api/tasks/{execution_id}") if operation == "delete"
                else client.post("/api/tasks/clear-history", json={}))

    assert response.status_code in (400, 409), response.text
    with factory() as session:
        job = session.get(WorkJob, execution_id)
        assert job is not None
        assert job.checkpoint_json == "{damaged-authority"
