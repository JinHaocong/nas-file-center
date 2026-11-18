"""Explicit cleanup recovery through HTTP and the real exclusive Worker lease."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest

from app.batch import media_organizer_cleanup_jobs as cleanup_jobs
from app.batch.media_organizer_planner import preview_semantic_unit
from app.db import create_engine_and_session
from app.models import TaskLock, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.recovery import acquire_worker_ownership, recover_interrupted_jobs
from app.worker import process_work_job
from tests.test_media_organizer_cleanup_jobs import _published
from tests.test_media_organizer_execute_jobs import execute_request, preview, worker


OWNER = "synthetic-original-worker"
SUCCESSOR = "synthetic-replacement-worker"


def _db(settings):
    return create_engine_and_session(settings.database_path)


def _row(settings, job_id):
    _, factory = _db(settings)
    with factory() as session:
        row = session.get(WorkJob, job_id)
        return row.status, json.loads(row.state_json), json.loads(row.checkpoint_json or "{}")


def _queue(client, execution_id, token):
    response = client.post(f"/api/media-organizer/executions/{execution_id}/cleanup",
                           json={"confirmation": token})
    assert response.status_code == 200, response.text
    return response.json()["job_id"]


def _recovery_token(job_id, token):
    return f"RECOVER_CLEANUP_JOB_{job_id}_{token}"


def _recover(client, job_id, token):
    return client.post(f"/api/media-organizer/cleanups/{job_id}/recover",
                       json={"confirmation": _recovery_token(job_id, token)})


def _expire(settings):
    _, factory = _db(settings)
    with factory() as session:
        session.get(TaskLock, 1).acquired_at = utcnow() - timedelta(seconds=31)
        session.commit()


def _snapshot(unit):
    return {str(p.relative_to(unit)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in unit.rglob("*") if p.is_file()}


def _frozen(settings, execution_id):
    folder = settings.reports_dir / "media_organizer-executions" / str(execution_id)
    return json.loads((folder / "manifest.json").read_text())["manifest"], folder


def _assert_final(client, settings, unit, execution_id, expected):
    status = client.get(f"/api/media-organizer/executions/{execution_id}").json()
    assert status["status"] == "completed"
    assert status["finalized"] is True
    assert status["manual_cleanup_required"] is False
    assert _snapshot(unit) == expected
    assert not any(p.name.startswith(".nfc-") for p in unit.rglob("*"))
    assert not (unit / "P1").exists()
    scan = preview_semantic_unit(unit, allowed_roots=[settings.data_mount],
                                 quarantine_root=settings.quarantine_root)
    assert scan["status"] == "already_organized"
    assert scan["needed_moves"] == scan["renamed_count"] == 0


def _expected(settings, execution_id, unit):
    manifest, _ = _frozen(settings, execution_id)
    return {str(Path(row["final"]).relative_to(unit)):
            hashlib.sha256(Path(row["source"]).read_bytes()).hexdigest()
            for row in manifest["moves"]}


@pytest.mark.parametrize("mixed", [False, True])
def test_new_worker_must_wait_for_lease_expiry_then_cleanup_reaches_zero(tmp_path, monkeypatch, mixed):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch, mixed=mixed)
    expected = _expected(settings, jid, unit)
    cleanup_id = _queue(client, jid, token)
    engine, factory = _db(settings)
    assert acquire_worker_ownership(engine, factory, worker_id=SUCCESSOR) is False
    before = _snapshot(unit)
    assert process_work_job(settings, cleanup_id, factory, engine, SUCCESSOR) is False
    assert _snapshot(unit) == before
    assert _row(settings, cleanup_id)[0] == "queued"
    _expire(settings)
    assert acquire_worker_ownership(engine, factory, worker_id=SUCCESSOR) is True
    assert process_work_job(settings, cleanup_id, factory, engine, OWNER) is False
    assert _snapshot(unit) == before
    assert process_work_job(settings, cleanup_id, factory, engine, SUCCESSOR) is True
    assert _row(settings, cleanup_id)[0] == "completed"
    _assert_final(client, settings, unit, jid, expected)


@pytest.mark.parametrize("mixed", [False, True])
def test_worker_restart_requires_explicit_cleanup_recovery_and_preserves_bytes(tmp_path, monkeypatch, mixed):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch, mixed=mixed)
    expected = _expected(settings, jid, unit)
    manifest, folder = _frozen(settings, jid)
    cleanup_id = _queue(client, jid, token)
    finish = cleanup_jobs.finish_deferred_cleanup

    def interrupted(*args, **kwargs):
        def crash(index):
            if index == 0:
                raise SystemExit("synthetic worker process exit after unlink")
        return finish(*args, **kwargs, after_mutation=crash)

    with monkeypatch.context() as fault:
        fault.setattr(cleanup_jobs, "finish_deferred_cleanup", interrupted)
        with pytest.raises(SystemExit, match="synthetic worker"):
            worker(settings, cleanup_id, name=OWNER)
    assert _row(settings, cleanup_id)[0] == "running"
    assert not Path(manifest["moves"][0]["source"]).exists()
    assert Path(manifest["moves"][1]["source"]).exists()
    engine, factory = _db(settings)
    assert acquire_worker_ownership(engine, factory, worker_id=SUCCESSOR) is False
    _expire(settings)
    assert acquire_worker_ownership(engine, factory, worker_id=SUCCESSOR)
    recovered = recover_interrupted_jobs(engine, factory, worker_id=SUCCESSOR)
    assert recovered["failed_interrupted"] == 1
    assert recovered["recovered_requeued"] == 0
    assert _row(settings, cleanup_id)[0] == "failed"
    assert client.post(f"/api/media-organizer/executions/{jid}/cleanup",
                       json={"confirmation": token}).status_code == 409
    before = _snapshot(unit)
    journal = folder / "manifest.json.cleanup-progress.jsonl"
    before_journal = journal.read_bytes()
    recovery = _recover(client, cleanup_id, token)
    assert recovery.status_code == 200, recovery.text
    rid = recovery.json()["job_id"]
    assert rid != cleanup_id
    assert _row(settings, rid)[1]["recovery_of_job_id"] == cleanup_id
    assert _snapshot(unit) == before
    assert journal.read_bytes() == before_journal
    assert process_work_job(settings, rid, factory, engine, OWNER) is False
    assert process_work_job(settings, rid, factory, engine, SUCCESSOR)
    assert _row(settings, rid)[0] == "completed"
    _assert_final(client, settings, unit, jid, expected)
    completed_journal = journal.read_bytes()
    duplicate = _recover(client, cleanup_id, token)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["job_id"] == rid
    assert process_work_job(settings, rid, factory, engine, SUCCESSOR)
    assert journal.read_bytes() == completed_journal


@pytest.mark.parametrize("crash_point", ["after_filesystem", "after_original_commit"])
def test_cleanup_recovery_closes_filesystem_and_database_commit_gaps(tmp_path, monkeypatch, crash_point):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch, mixed=True)
    expected = _expected(settings, jid, unit)
    cleanup_id = _queue(client, jid, token)
    finish = cleanup_jobs.finish_deferred_cleanup
    checkpoint = JobContext.checkpoint

    def finalizer(*args, **kwargs):
        finish(*args, **kwargs)
        raise RuntimeError("synthetic exit after durable finalized journal")

    def last_checkpoint(self, **kwargs):
        if self.job_id == cleanup_id and kwargs.get("progress_current") == 2:
            raise RuntimeError("synthetic exit after original database commit")
        return checkpoint(self, **kwargs)

    with monkeypatch.context() as fault:
        if crash_point == "after_filesystem":
            fault.setattr(cleanup_jobs, "finish_deferred_cleanup", finalizer)
        else:
            fault.setattr(JobContext, "checkpoint", last_checkpoint)
        assert worker(settings, cleanup_id, name=OWNER) is False
    assert _row(settings, cleanup_id)[0] == "failed"
    assert _snapshot(unit) == expected
    original = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert original["finalized"] is (crash_point == "after_original_commit")
    recovery = _recover(client, cleanup_id, token)
    assert recovery.status_code == 200, recovery.text
    rid = recovery.json()["job_id"]
    assert worker(settings, rid, name=OWNER)
    assert _row(settings, rid)[0] == "completed"
    _assert_final(client, settings, unit, jid, expected)


def _failed_before_cleanup(tmp_path, monkeypatch):
    client, settings, unit, jid, token, state = _published(tmp_path, monkeypatch)
    cleanup_id = _queue(client, jid, token)
    state["allowed"] = False
    assert worker(settings, cleanup_id, name=OWNER) is False
    assert _row(settings, cleanup_id)[0] == "failed"
    state["allowed"] = True
    return client, settings, unit, jid, cleanup_id, token, state


def test_recovery_confirmation_is_attempt_bound_and_duplicate_queue_is_idempotent(tmp_path, monkeypatch):
    client, settings, unit, jid, cid, token, _ = _failed_before_cleanup(tmp_path, monkeypatch)
    before = _snapshot(unit)
    path = f"/api/media-organizer/cleanups/{cid}/recover"
    for invalid in (token, _recovery_token(cid + 1, token), "RECOVER_EXECUTION_1"):
        assert client.post(path, json={"confirmation": invalid}).status_code == 409
    first = _recover(client, cid, token)
    assert first.status_code == 200, first.text
    second = _recover(client, cid, token)
    assert second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    assert _snapshot(unit) == before
    _, factory = _db(settings)
    with factory() as session:
        recovered = session.get(WorkJob, first.json()["job_id"])
        assert recovered.retry_of == cid
    assert client.post(path, json={"confirmation": _recovery_token(cid, token),
                                   "skip_validation": True}).status_code == 422
    client.cookies.clear()
    assert _recover(client, cid, token).status_code == 401


def test_recovery_rechecks_revoked_custody_and_allows_explicit_next_attempt(tmp_path, monkeypatch):
    client, settings, unit, jid, cid, token, state = _failed_before_cleanup(tmp_path, monkeypatch)
    before = _snapshot(unit)
    state["allowed"] = False
    assert _recover(client, cid, token).status_code == 409
    state["allowed"] = True
    first = _recover(client, cid, token)
    assert first.status_code == 200, first.text
    rid = first.json()["job_id"]
    state["allowed"] = False
    assert worker(settings, rid, name=OWNER) is False
    assert _snapshot(unit) == before
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False
    state["allowed"] = True
    assert _recover(client, cid, token).status_code == 409
    next_attempt = _recover(client, rid, token)
    assert next_attempt.status_code == 200, next_attempt.text
    expected = _expected(settings, jid, unit)
    assert worker(settings, next_attempt.json()["job_id"], name=OWNER)
    _assert_final(client, settings, unit, jid, expected)


@pytest.mark.parametrize("field,value", [("plan_sha256", "f" * 64), ("frozen_job_id", 99999)])
def test_changed_frozen_recovery_authority_cannot_queue_or_delete(tmp_path, monkeypatch, field, value):
    client, settings, unit, jid, cid, token, _ = _failed_before_cleanup(tmp_path, monkeypatch)
    before = _snapshot(unit)
    _, factory = _db(settings)
    with factory() as session:
        job = session.get(WorkJob, cid)
        state = json.loads(job.state_json)
        state[field] = value
        job.state_json = json.dumps(state)
        session.commit()
    assert _recover(client, cid, token).status_code == 409
    assert _snapshot(unit) == before


def test_cleanup_cannot_finalize_original_after_losing_lease_at_database_boundary(tmp_path, monkeypatch):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch)
    cid = _queue(client, jid, token)
    checkpoint = JobContext.checkpoint
    _, factory = _db(settings)

    def lose_after_verified(self, **kwargs):
        result = checkpoint(self, **kwargs)
        if self.job_id == cid and kwargs.get("progress_current") == 1:
            with factory() as session:
                lock = session.get(TaskLock, 1)
                lock.owner = SUCCESSOR
                lock.acquired_at = utcnow()
                session.commit()
        return result

    monkeypatch.setattr(JobContext, "checkpoint", lose_after_verified)
    assert worker(settings, cid, name=OWNER) is False
    original = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert original["finalized"] is False
    assert original["manual_cleanup_required"] is True


def test_publication_cannot_queue_while_a_separate_cleanup_is_active(tmp_path, monkeypatch):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch)
    sibling = unit.parent / "NO.002"
    sibling.mkdir()
    (sibling / "new.jpg").write_bytes(b"second isolated work")
    pid = preview(client, settings, sibling)
    _queue(client, jid, token)
    response = execute_request(client, pid, sibling)
    assert response.status_code == 409, response.text
    assert (sibling / "new.jpg").read_bytes() == b"second isolated work"


def test_initial_cleanup_post_is_idempotent_after_real_finalization(tmp_path, monkeypatch):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch)
    cid = _queue(client, jid, token)
    assert worker(settings, cid, name=OWNER)
    before = _snapshot(unit)
    response = client.post(f"/api/media-organizer/executions/{jid}/cleanup",
                           json={"confirmation": token})
    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == cid
    assert _snapshot(unit) == before


def test_execution_status_exposes_the_exact_cleanup_attempt_for_user_recovery(tmp_path, monkeypatch):
    client, settings, unit, jid, cid, token, _ = _failed_before_cleanup(tmp_path, monkeypatch)
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert status["cleanup"]["job_id"] == cid
    assert status["cleanup"]["status"] == "failed"
    assert status["cleanup"]["recovery_confirmation"] == _recovery_token(cid, token)
    recovery = _recover(client, cid, token)
    assert recovery.status_code == 200, recovery.text
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert status["cleanup"]["job_id"] == recovery.json()["job_id"]
    assert status["cleanup"]["status"] == "queued"
    assert status["cleanup"]["recovery_confirmation"] is None


def test_cleanup_plan_returns_bound_confirmation_without_approving_deletion(tmp_path, monkeypatch):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch)
    response = client.get(f"/api/media-organizer/executions/{jid}/cleanup-plan")
    assert response.status_code == 200
    assert response.json()["confirmation"] == token
    assert response.json()["cleanup_authorized"] is False
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["cleanup"] is None


def test_execution_status_provides_current_gate_without_a_new_preview(tmp_path, monkeypatch):
    client, settings, unit, jid, token, _ = _published(tmp_path, monkeypatch)
    path = f"/api/media-organizer/executions/{jid}"
    assert client.get(path).json()["execution_enabled"] is True
    monkeypatch.setattr(settings, "media_organizer_execution_enabled", False)
    assert client.get(path).json()["execution_enabled"] is False
    assert client.post(f"{path}/cleanup", json={"confirmation": token}).status_code == 409


def test_custody_revocation_before_original_commit_holds_finalized_status(tmp_path, monkeypatch):
    client, settings, unit, jid, token, state = _published(tmp_path, monkeypatch)
    issue = cleanup_jobs.namespace_custody.verified_namespace_custody

    def live_proof(settings, unit):
        proof = issue(settings, unit)

        class RevocableProof:
            def assert_exclusive(self, folder):
                if not state["allowed"]:
                    raise ValueError("synthetic custody revoked")
                proof.assert_exclusive(folder)
        return RevocableProof()

    monkeypatch.setattr(cleanup_jobs.namespace_custody, "verified_namespace_custody", live_proof)
    cid = _queue(client, jid, token)
    checkpoint = JobContext.checkpoint

    def revoke_after_verified(self, **kwargs):
        result = checkpoint(self, **kwargs)
        if self.job_id == cid and kwargs.get("progress_current") == 1:
            state["allowed"] = False
        return result

    with monkeypatch.context() as fault:
        fault.setattr(JobContext, "checkpoint", revoke_after_verified)
        assert worker(settings, cid, name=OWNER) is False
    assert _row(settings, cid)[0] == "failed"
    original = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert original["finalized"] is False
    state["allowed"] = True
    response = _recover(client, cid, token)
    assert response.status_code == 200, response.text
    assert worker(settings, response.json()["job_id"], name=OWNER)
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is True
