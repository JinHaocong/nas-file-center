from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import BatchPlan, IndexRoot, IndexedPath, User, WorkJob, utcnow
from app.service import FileCenterService
from app.tasks.recovery import acquire_worker_ownership, recover_interrupted_jobs
from app.worker import process_work_job
from tests.test_workflow_api import workflow_test_env  # noqa: F401 - shared local test fixture


def _workflow(env: dict) -> int:
    with env["service"].SessionLocal() as session:
        session.get(IndexRoot, env["root_id"]).last_indexed_at = utcnow()
        for indexed in session.scalars(select(IndexedPath).where(IndexedPath.root_key == str(env["media"]))):
            indexed.mtime_ns = Path(indexed.absolute_path).stat().st_mtime_ns
        session.commit()
    response = env["admin_client"].post("/api/workflows", json={
        "name": "临时媒体归档",
        "definition": {
            "mode": "file",
            "steps": [
                {"id": "scan", "type": "scan", "root_ids": [env["root_id"]]},
                {"id": "rename", "type": "rename", "pattern": "movie", "replacement": "archived"},
            ],
        },
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _request(env: dict, digest: str = "a" * 64) -> dict:
    return {
        "revision": 1, "directory": str(env["media"]), "expected_compile_digest": digest,
        "request_id": str(uuid4()),
    }


def _confirm(env: dict, workflow_id: int, payload: dict, *, actor: str = "admin"):
    return env[f"{actor}_client"].post(f"/api/workflows/{workflow_id}/quick-run", json=payload)


def _ready_preview(env: dict, workflow_id: int) -> tuple[dict, str]:
    response = env["admin_client"].post(f"/api/workflows/{workflow_id}/preview", json={
        "revision": 1, "runtime_inputs": {"directory": str(env["media"])},
    })
    assert response.status_code == 200, response.text
    payload = _request(env, response.json()["compile_digest"])
    receipt = _confirm(env, workflow_id, payload)
    assert receipt.status_code == 202, receipt.text
    return payload, receipt.json()["job_id"]


def _process(service: FileCenterService, job_id: str, worker: str) -> bool:
    return process_work_job(service.settings, int(job_id), service.SessionLocal, service.engine, worker_id=worker)


def _take_lease(service: FileCenterService) -> str:
    worker = "test-quick-run-worker"
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker)
    return worker


def test_quick_run_confirmation_only_enqueues_and_is_idempotent_per_actor(workflow_test_env):
    env = workflow_test_env
    env["service"].settings.allow_mutation = True
    workflow_id = _workflow(env)
    payload = _request(env)
    first = _confirm(env, workflow_id, payload)
    duplicate = _confirm(env, workflow_id, payload)
    altered = _confirm(env, workflow_id, {**payload, "expected_compile_digest": "b" * 64})
    member = _confirm(env, workflow_id, payload, actor="member")

    assert first.status_code == duplicate.status_code == member.status_code == 202
    assert altered.status_code == 409
    assert first.json() == duplicate.json()
    assert isinstance(first.json()["job_id"], str)
    assert first.json()["job_id"] != member.json()["job_id"]
    with env["service"].SessionLocal() as session:
        jobs = list(session.scalars(select(WorkJob)))
        assert len(jobs) == 2
        assert {job.kind for job in jobs} == {"workflow-quick-run"}
        assert {job.status for job in jobs} == {"queued"}
        assert all(json.loads(job.checkpoint_json)["phase"] == "generate_plan" for job in jobs)
        assert session.scalar(select(func.count(BatchPlan.id))) == 0


def test_quick_run_rejects_read_only_deployment(workflow_test_env):
    env = workflow_test_env
    env["service"].settings.allow_mutation = False
    workflow_id = _workflow(env)
    result = _confirm(env, workflow_id, _request(env))
    assert result.status_code == 403
    with env["service"].SessionLocal() as session:
        assert session.scalar(select(func.count(WorkJob.id))) == 0


@pytest.mark.parametrize("interruption", ["after_draft", "after_enqueue"])
def test_quick_run_resumes_without_duplicate_plans_or_execution(workflow_test_env, monkeypatch, interruption):
    env = workflow_test_env
    service = env["service"]
    service.settings.allow_mutation = True
    workflow_id = _workflow(env)
    payload, queued_id = _ready_preview(env, workflow_id)
    worker = _take_lease(service)

    with monkeypatch.context() as patch:
        if interruption == "after_draft":
            def interrupted_freeze(*args, **kwargs):
                raise SystemExit("simulated Worker crash after committing draft")

            patch.setattr(FileCenterService, "freeze_plan", interrupted_freeze)
        else:
            enqueue = FileCenterService.enqueue_plan_execution

            def interrupted_enqueue(*args, **kwargs):
                enqueue(*args, **kwargs)
                raise SystemExit("simulated Worker crash after committing execution")

            patch.setattr(FileCenterService, "enqueue_plan_execution", interrupted_enqueue)
        with pytest.raises(SystemExit):
            _process(service, queued_id, worker)

    recovery = recover_interrupted_jobs(service.engine, service.SessionLocal, worker_id=worker)
    assert recovery["recovered_requeued"] == 1
    assert _process(service, queued_id, worker)
    detail = env["admin_client"].get(f"/api/tasks/{queued_id}").json()
    assert detail["status"] == "completed"
    assert detail["checkpoint"]["phase"] == "queued"
    child_id = detail["checkpoint"]["execution_job_id"]
    assert isinstance(child_id, str)
    assert env["admin_client"].get(f"/api/tasks/{child_id}").json()["id"] == child_id
    assert env["admin_client"].get(f"/api/workflows/{workflow_id}/latest-run").json()["id"] == child_id
    assert _confirm(env, workflow_id, payload).json() == {"job_id": queued_id}
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == 1
        assert session.scalar(select(func.count(WorkJob.id)).where(WorkJob.kind == "batch-plan-execute")) == 1
    assert _process(service, child_id, worker)
    assert (Path(env["media"]) / "archived1.mkv").read_text() == "movie data 1"
    assert env["admin_client"].delete(f"/api/tasks/{queued_id}").status_code == 200
    assert _confirm(env, workflow_id, payload).status_code == 409


def test_quick_run_with_stale_digest_does_not_create_or_execute_plan(workflow_test_env):
    env = workflow_test_env
    service = env["service"]
    service.settings.allow_mutation = True
    workflow_id = _workflow(env)
    receipt = _confirm(env, workflow_id, _request(env))
    assert receipt.status_code == 202, receipt.text
    job_id = receipt.json()["job_id"]
    assert not _process(service, job_id, _take_lease(service))
    detail = env["admin_client"].get(f"/api/tasks/{job_id}").json()
    assert detail["status"] == "failed"
    assert detail["checkpoint"]["phase"] == "generate_plan"
    assert detail["error_code"] == "PREVIEW_CHANGED"
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == 0
        assert session.scalar(select(func.count(WorkJob.id))) == 1


def test_quick_run_rechecks_the_actor_before_preparing(workflow_test_env):
    env = workflow_test_env
    service = env["service"]
    service.settings.allow_mutation = True
    workflow_id = _workflow(env)
    receipt = _confirm(env, workflow_id, _request(env), actor="member")
    assert receipt.status_code == 202, receipt.text
    with service.SessionLocal() as session:
        member = session.scalar(select(User).where(User.username == "member1"))
        member.is_active = False
        session.commit()

    job_id = receipt.json()["job_id"]
    assert not _process(service, job_id, _take_lease(service))
    task = env["admin_client"].get(f"/api/tasks/{job_id}").json()
    assert task["error_code"] == "WORKFLOW_RUN_FORBIDDEN"
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == 0


def test_quick_run_exposes_validation_failure_without_enqueuing(workflow_test_env, monkeypatch):
    env = workflow_test_env
    service = env["service"]
    service.settings.allow_mutation = True
    workflow_id = _workflow(env)
    _payload, job_id = _ready_preview(env, workflow_id)
    source = env["media"] / "movie1.mkv"
    verify = FileCenterService.validate_plan

    def change_source_before_validation(instance, *args, **kwargs):
        source.write_text("external edit after freezing")
        return verify(instance, *args, **kwargs)

    monkeypatch.setattr(FileCenterService, "validate_plan", change_source_before_validation)
    assert not _process(service, job_id, _take_lease(service))
    detail = env["admin_client"].get(f"/api/tasks/{job_id}").json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == "WORKFLOW_RUN_VALIDATION_FAILED"
    assert "movie1.mkv" in detail["error"]
    assert detail["checkpoint"]["phase"] == "validate"
    assert "execution_job_id" not in detail["checkpoint"]
    assert source.read_text() == "external edit after freezing"
    assert not (env["media"] / "archived1.mkv").exists()
