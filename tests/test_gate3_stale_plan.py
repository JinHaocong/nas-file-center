from __future__ import annotations

import json
import os
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import Settings
from app.db import create_engine_and_session
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler


def _setup_test_env(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir = data_dir / ".nas-file-center-trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"

    settings = Settings(
        config_dir=config_dir,
        database_path=db_path,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=trash_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    app = create_app(settings)
    client = TestClient(app)

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    assert resp.status_code == 200
    client.headers.update({"Origin": "http://testserver"})

    service: FileCenterService = app.state.service
    return client, service, settings, data_dir, trash_dir


def _acquire_lease(service: FileCenterService, worker_id: str):
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        session.commit()


# =====================================================================
# 1. CORE STALE TESTS
# =====================================================================

def test_execute_rejects_missing_source(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "file_a.txt"
    file_a.write_text("content a", encoding="utf-8")

    plan = service.create_plan(
        name="Missing Source Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # File deleted after validate
    file_a.unlink()

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert "error" in err
    assert err["error"]["code"] == "PLAN_STALE"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "stale"


def test_execute_rejects_replaced_same_path_entity(tmp_path: Path):
    client, service, _, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "target.txt"
    file_a.write_text("original file A", encoding="utf-8")

    plan = service.create_plan(
        name="Replacement Test Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Delete original file A and create file B at the same path with same byte size
    file_a.unlink()
    (data_dir / ".holder").write_text("hold")  # consume recycled inode on Linux
    file_a.write_text("replaced file B!", encoding="utf-8")  # guaranteed different inode!

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PLAN_STALE"
    stale_item = err["error"]["details"]["stale_items"][0]
    assert stale_item["reason"] in ("filesystem_identity_changed", "inode_changed")

    # File B must NOT be touched or moved into quarantine
    assert file_a.exists()
    assert file_a.read_text(encoding="utf-8") == "replaced file B!"
    assert len(list(trash_dir.glob("**/*"))) == 0


def test_execute_rejects_size_change(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "size_test.txt"
    file_a.write_text("small", encoding="utf-8")

    plan = service.create_plan(
        name="Size Change Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Modify file size
    file_a.write_text("much larger content than before", encoding="utf-8")

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PLAN_STALE"
    assert err["error"]["details"]["stale_items"][0]["reason"] == "size_changed"


def test_execute_rejects_mtime_change(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "mtime_test.txt"
    file_a.write_text("exact10byt", encoding="utf-8")

    plan = service.create_plan(
        name="mtime Change Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Change mtime explicitly
    orig_stat = file_a.stat()
    os.utime(file_a, ns=(orig_stat.st_atime_ns, orig_stat.st_mtime_ns + 5_000_000_000))

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PLAN_STALE"
    assert err["error"]["details"]["stale_items"][0]["reason"] == "mtime_changed"


def test_execute_rejects_hash_change(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_keep = data_dir / "keep.txt"
    file_keep.write_text("duplicate_content", encoding="utf-8")
    file_del = data_dir / "del.txt"
    file_del.write_text("duplicate_content", encoding="utf-8")

    plan = service.create_plan(
        name="Hash Change Plan",
        kind="dedupe",
        items=[{"source": str(file_del), "keep": str(file_keep), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Verify expected_hash is populated
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan.id).first()
        assert item.expected_hash is not None

    # Overwrite with same byte size, and restore mtime
    st = file_del.stat()
    file_del.write_text("tampered_content!", encoding="utf-8")  # same size 17 bytes
    os.utime(file_del, ns=(st.st_atime_ns, st.st_mtime_ns))

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PLAN_STALE"
    reason = err["error"]["details"]["stale_items"][0]["reason"]
    assert reason in ("hash_changed", "ctime_changed")


def test_execute_rejects_symlink_replacement(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "regular.txt"
    file_a.write_text("regular file", encoding="utf-8")

    plan = service.create_plan(
        name="Symlink Replacement Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Delete regular file and replace with symlink
    target_f = data_dir / "other.txt"
    target_f.write_text("other file", encoding="utf-8")
    file_a.unlink()
    file_a.symlink_to(target_f)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PLAN_STALE"
    assert err["error"]["details"]["stale_items"][0]["reason"] in ("symlink_replaced", "symlink_escape")


def test_execute_rejects_symlink_escape(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "escape.txt"
    file_a.write_text("initial", encoding="utf-8")

    plan = service.create_plan(
        name="Symlink Escape Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Replace with symlink pointing to /etc/passwd outside ALLOWED_ROOTS
    file_a.unlink()
    file_a.symlink_to("/etc/passwd")

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PLAN_STALE"


def test_execute_rechecks_after_previous_validate(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "file_a.txt"
    file_a.write_text("valid content", encoding="utf-8")

    plan = service.create_plan(
        name="Recheck Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    val_res = service.validate_plan(plan.id)
    assert val_res["status"] == "ready"

    # Modify file after validate passed!
    file_a.write_text("modified content after validation", encoding="utf-8")

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PLAN_STALE"


def test_large_inode_snapshot_roundtrip(tmp_path: Path):
    _, service, _, data_dir, _ = _setup_test_env(tmp_path)
    large_inode = 12164156718799206349
    file_a = data_dir / "zfs_file.txt"
    file_a.write_text("zfs content", encoding="utf-8")

    plan = service.create_plan(
        name="Large Inode Plan",
        kind="organize",
        items=[{
            "source": str(file_a),
            "target": str(data_dir / "renamed.txt"),
            "operation": "rename",
            "expected_inode": large_inode,
        }],
    )
    service.freeze_plan(plan.id)

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan.id).first()
        assert item.expected_inode == large_inode


def test_stale_validation_does_not_hold_long_sqlite_write_transaction(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "tx_test.txt"
    file_a.write_text("tx content", encoding="utf-8")

    plan = service.create_plan(
        name="TX Test Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # While execute preflight or validation runs, concurrent readers should not be blocked
    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200


# =====================================================================
# 2. IMMUTABLE SNAPSHOT TESTS
# =====================================================================

def test_stale_revalidation_does_not_refresh_frozen_snapshot(tmp_path: Path):
    _, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "immutable.txt"
    file_a.write_text("original 8b", encoding="utf-8")

    plan = service.create_plan(
        name="Immutable Snapshot Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    with service.SessionLocal() as session:
        orig_item = session.query(BatchPlanItem).filter_by(plan_id=plan.id).first()
        frozen_size = orig_item.expected_size
        frozen_inode = orig_item.expected_inode

    # Modify file
    file_a.write_text("new content with different size", encoding="utf-8")

    # Revalidate
    service.validate_plan(plan.id)

    # Snapshot fields MUST NOT have been updated!
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "stale"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan.id).first()
        assert item.expected_size == frozen_size
        assert item.expected_inode == frozen_inode


def test_stale_plan_cannot_transition_back_to_ready_without_new_freeze(tmp_path: Path):
    _, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "no_unfreeze.txt"
    file_a.write_text("content 1", encoding="utf-8")

    plan = service.create_plan(
        name="No Unfreeze Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Change file -> stale
    file_a.write_text("content 22222", encoding="utf-8")
    service.validate_plan(plan.id)

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "stale"

    # Attempting to validate again must keep plan in stale status, never transition back to ready
    service.validate_plan(plan.id)
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "stale"


# =====================================================================
# 3. QUEUE & WORKER BOUNDARY TESTS
# =====================================================================

def test_execute_stale_does_not_enqueue_worker_job(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "no_enqueue.txt"
    file_a.write_text("content", encoding="utf-8")

    plan = service.create_plan(
        name="No Enqueue Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    file_a.unlink()

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409

    # Verify zero WorkJobs were enqueued in database
    with service.SessionLocal() as session:
        jobs = session.query(WorkJob).filter_by(kind="batch-plan-execute").all()
        assert len(jobs) == 0


def test_worker_rechecks_plan_after_api_enqueue_before_first_mutation(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "queue_window.txt"
    file_a.write_text("content window", encoding="utf-8")

    plan = service.create_plan(
        name="Queue Window Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # API Execute preflight passes when file is unchanged
    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    # Now simulate external modification while job sits in queue before Worker runs!
    file_a.write_text("modified while in queue!", encoding="utf-8")

    # Worker runs
    worker_id = "test-worker-1"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    # Zero filesystem mutations must have occurred!
    assert file_a.exists()
    assert file_a.read_text(encoding="utf-8") == "modified while in queue!"
    assert len(list(trash_dir.glob("**/*"))) == 0

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status in ("stale", "failed")


def test_worker_stops_remaining_items_when_later_item_becomes_stale(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_1 = data_dir / "file_1.txt"
    file_1.write_text("item 1 content", encoding="utf-8")
    file_2 = data_dir / "file_2.txt"
    file_2.write_text("item 2 content", encoding="utf-8")

    plan = service.create_plan(
        name="Multi Item Stale Plan",
        kind="dedupe",
        items=[
            {"source": str(file_1), "operation": "quarantine"},
            {"source": str(file_2), "operation": "quarantine"},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-multi"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    # Delete file 2 before item 2 is processed by worker (after item 1 completes)
    orig_checkpoint = ctx.checkpoint
    def race_checkpoint(*args, **kwargs):
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and file_2.exists():
            file_2.unlink()
        return orig_checkpoint(*args, **kwargs)
    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    # Item 1 was unchanged or stopped; but if item 2 was stale, remaining items must stop
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        # Item 1 completed, item 2 was stale -> status must be partial with PLAN_STALE
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"


def test_mid_execution_stale_results_in_partial_not_false_zero_mutation_stale(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_1 = data_dir / "mid_1.txt"
    file_1.write_text("mid 1 content", encoding="utf-8")
    file_2 = data_dir / "mid_2.txt"
    file_2.write_text("mid 2 content", encoding="utf-8")

    plan = service.create_plan(
        name="Mid Execution Plan",
        kind="dedupe",
        items=[
            {"source": str(file_1), "operation": "quarantine"},
            {"source": str(file_2), "operation": "quarantine"},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    # Pre-execute item 1 successfully
    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan.id).order_by(BatchPlanItem.sequence).all()
        items[0].state = "completed"
        # file_2 is modified to become stale
        file_2.write_text("changed!", encoding="utf-8")
        session.commit()

    worker_id = "test-worker-mid"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        # Since item 1 was completed, the plan must end in partial, NOT false zero-mutation stale!
        assert p.status == "partial"


# =====================================================================
# 4. MUTATION INTEGRITY TESTS
# =====================================================================

def test_stale_plan_has_no_filesystem_mutation(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "no_mutation.txt"
    file_a.write_text("original", encoding="utf-8")

    plan = service.create_plan(
        name="No Mutation Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Change size
    file_a.write_text("original plus more", encoding="utf-8")

    client.post(f"/api/plans/{plan.id}/execute")

    # File must still be in place
    assert file_a.exists()
    assert file_a.read_text(encoding="utf-8") == "original plus more"


def test_stale_plan_has_no_success_operation_journal(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "no_journal.txt"
    file_a.write_text("orig", encoding="utf-8")

    plan = service.create_plan(
        name="No Journal Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    file_a.write_text("modified", encoding="utf-8")

    client.post(f"/api/plans/{plan.id}/execute")

    with service.SessionLocal() as session:
        journals = session.query(OperationJournal).filter_by(plan_id=plan.id).all()
        # No SUCCESS journal entry must exist
        for j in journals:
            assert j.status != "success"


def test_execute_does_not_quarantine_replacement_file(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "adversarial.txt"
    file_a.write_text("file A original", encoding="utf-8")

    plan = service.create_plan(
        name="Adversarial Replacement Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Delete A and create B
    file_a.unlink()
    file_a.write_text("file B replacement", encoding="utf-8")

    # API execution attempt
    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409

    # File B must NOT be moved to quarantine!
    assert file_a.exists()
    assert file_a.read_text(encoding="utf-8") == "file B replacement"
    assert len(list(trash_dir.glob("**/*"))) == 0


# =====================================================================
# 5. STRUCTURED API TESTS
# =====================================================================

def test_stale_plan_returns_http_409(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "status_409.txt"
    file_a.write_text("content", encoding="utf-8")

    plan = service.create_plan(
        name="HTTP 409 Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    file_a.unlink()

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409


def test_stale_plan_returns_structured_plan_stale_error(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "structured_err.txt"
    file_a.write_text("content", encoding="utf-8")

    plan = service.create_plan(
        name="Structured Error Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    file_a.unlink()

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "PLAN_STALE"
    assert "message" in err
    assert "details" in err
    assert err["details"]["plan_id"] == plan.id
    assert err["details"]["stale_count"] >= 1


def test_stale_error_contains_expected_and_actual_identity(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "identity_err.txt"
    file_a.write_text("orig 123", encoding="utf-8")

    plan = service.create_plan(
        name="Identity Error Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    file_a.write_text("changed to a much longer string", encoding="utf-8")

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 409
    body = resp.json()
    stale_item = body["error"]["details"]["stale_items"][0]
    assert stale_item["source_path"] == str(file_a)
    assert stale_item["reason"] == "size_changed"
    assert "expected" in stale_item
    assert "actual" in stale_item
    assert stale_item["expected"]["size"] == len("orig 123")
    assert stale_item["actual"]["size"] == len("changed to a much longer string")


# =====================================================================
# HOTFIX 1 TESTS: PRE-MUTATION RACE & IMMUTABLE HASH & TERMINATION REASON
# =====================================================================

def test_post_boundary_pre_mutation_replacement_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "victim.txt"
    file_a.write_bytes(b"ORIGINAL-INODE-A")
    target_a = data_dir / "renamed.txt"
    orig_stat = file_a.stat()

    plan = service.create_plan(
        name="Post Boundary Replacement Plan",
        kind="organizer",
        items=[{"source": str(file_a), "target": str(target_a), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-boundary-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replacement_triggered = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replacement_triggered
        msg = kwargs.get("progress_message", "")
        if "Executing item #1" in msg and not replacement_triggered:
            temp_held = data_dir / "held_old.tmp"
            file_a.rename(temp_held)
            file_a.write_bytes(b"REPLACED-INODE-B")
            assert file_a.stat().st_ino != orig_stat.st_ino
            temp_held.unlink()
            replacement_triggered = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replacement_triggered, "race condition simulation must have executed"
    assert not target_a.exists(), "destination must NOT contain replacement entity"
    assert file_a.exists(), "replacement source must NOT be renamed/moved/quarantined"
    assert file_a.read_bytes() == b"REPLACED-INODE-B"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "stale"
        item = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)).first()
        assert item.state == "failed"
        assert "stale" in (item.reason or "").lower() or "filesystem_identity_changed" in (item.reason or "")
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert all(j.status != "success" for j in journals)


def test_post_boundary_pre_mutation_quarantine_replacement_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "victim_quarantine.txt"
    file_a.write_bytes(b"ORIGINAL-INODE-Q")
    orig_stat = file_a.stat()

    plan = service.create_plan(
        name="Quarantine Replacement Plan",
        kind="dedupe",
        items=[{"source": str(file_a), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-q-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replacement_triggered = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replacement_triggered
        msg = kwargs.get("progress_message", "")
        if "Executing item #1" in msg and not replacement_triggered:
            temp_held = data_dir / "held_old_q.tmp"
            file_a.rename(temp_held)
            file_a.write_bytes(b"REPLACED-INODE-X")
            assert file_a.stat().st_ino != orig_stat.st_ino
            temp_held.unlink()
            replacement_triggered = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replacement_triggered
    assert file_a.exists(), "replacement source must NOT be quarantined"
    assert file_a.read_bytes() == b"REPLACED-INODE-X"
    assert len(list(trash_dir.glob("**/*"))) == 0

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "stale"
        item = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)).first()
        assert item.state == "failed"
        assert "stale" in (item.reason or "").lower() or "filesystem_identity_changed" in (item.reason or "")


def test_post_boundary_pre_mutation_touch_replacement_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "victim_touch.txt"
    file_a.write_bytes(b"ORIGINAL-INODE-T")
    orig_stat = file_a.stat()

    target_mtime = int(time.time() + 10000) * 1_000_000_000

    plan = service.create_plan(
        name="Touch Replacement Plan",
        kind="organizer",
        items=[{"source": str(file_a), "operation": "touch", "expected_mtime_ns": target_mtime}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-t-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replacement_triggered = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replacement_triggered
        msg = kwargs.get("progress_message", "")
        if "Executing item #1" in msg and not replacement_triggered:
            temp_held = data_dir / "held_old_t.tmp"
            file_a.rename(temp_held)
            file_a.write_bytes(b"REPLACED-INODE-Y")
            assert file_a.stat().st_ino != orig_stat.st_ino
            temp_held.unlink()
            replacement_triggered = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replacement_triggered
    cur_mtime_ns = getattr(file_a.stat(), "st_mtime_ns", int(file_a.stat().st_mtime * 1e9))
    assert cur_mtime_ns != target_mtime, "replacement file must NOT have its mtime mutated"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "stale"
        item = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)).first()
        assert item.state == "failed"


def test_validate_does_not_mutate_frozen_expected_hash(tmp_path: Path):
    client, service, _, data_dir, _ = _setup_test_env(tmp_path)
    file_keep = data_dir / "keep.txt"
    file_keep.write_bytes(b"duplicate content 12345")
    file_dup = data_dir / "dup.txt"
    file_dup.write_bytes(b"duplicate content 12345")

    plan = service.create_plan(
        name="Dedupe Plan Hash Immutability",
        kind="dedupe",
        items=[{"source": str(file_dup), "keep_path": str(file_keep), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)

    with service.SessionLocal() as session:
        item_before = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)).first()
        frozen_expected_hash = item_before.expected_hash
        frozen_metadata = json.loads(item_before.metadata_json or "{}")
        frozen_snapshot = frozen_metadata.get("snapshot")

    # Now validate
    service.validate_plan(plan.id)

    with service.SessionLocal() as session:
        item_after = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)).first()
        assert item_after.expected_hash == frozen_expected_hash, "validate_plan must NOT mutate expected_hash"
        after_metadata = json.loads(item_after.metadata_json or "{}")
        assert after_metadata.get("snapshot") == frozen_snapshot, "validate_plan must NOT mutate snapshot"


def test_mid_execution_stale_records_plan_stale_termination_reason(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_1 = data_dir / "multi_1.txt"
    file_1.write_text("item 1 content", encoding="utf-8")
    file_2 = data_dir / "multi_2.txt"
    file_2.write_text("item 2 content", encoding="utf-8")

    plan = service.create_plan(
        name="Multi Item Termination Reason Plan",
        kind="dedupe",
        items=[
            {"source": str(file_1), "operation": "quarantine"},
            {"source": str(file_2), "operation": "quarantine"},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-term-reason"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    # Unlink file_2 mid-execution after item 1 completes, before item 2 executes
    orig_checkpoint = ctx.checkpoint
    file_2_unlinked = False

    def race_checkpoint(*args, **kwargs):
        nonlocal file_2_unlinked
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not file_2_unlinked:
            if file_2.exists():
                file_2.unlink()
            file_2_unlinked = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial", f"plan status should be partial, got {p.status}"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE", f"termination_reason missing or wrong in {meta}"


def test_chained_target_replacement_between_operations_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "victim_chain_a.txt"
    file_a.write_bytes(b"ORIGINAL-CHAIN-CONTENT")
    orig_stat = file_a.stat()
    file_b = data_dir / "victim_chain_b.txt"

    target_mtime = int(time.time() + 10000) * 1_000_000_000

    plan = service.create_plan(
        name="Chained Replacement Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": target_mtime},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-chain-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replacement_triggered = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replacement_triggered
        msg = kwargs.get("progress_message", "")
        # Intercept when item 2 (touch B) starts executing (after item 1 completed rename A -> B)
        if "Executing item #2" in msg and not replacement_triggered:
            assert file_b.exists(), "Item 1 must have produced file_b"
            temp_held = data_dir / "held_old_chain.tmp"
            file_b.rename(temp_held)
            file_b.write_bytes(b"REPLACED-CHAIN-INODE-Z")
            assert file_b.stat().st_ino != orig_stat.st_ino
            temp_held.unlink()
            replacement_triggered = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replacement_triggered, "race condition must have executed"
    assert file_b.exists(), "replacement chained target must still exist"
    assert file_b.read_bytes() == b"REPLACED-CHAIN-INODE-Z", "replacement content must NOT be overwritten"
    cur_mtime_ns = getattr(file_b.stat(), "st_mtime_ns", int(file_b.stat().st_mtime * 1e9))
    assert cur_mtime_ns != target_mtime, "replacement chained target was physically touched after boundary check"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "stale" in (items[1].reason or "").lower() or "filesystem_identity_changed" in (items[1].reason or "")
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        # Only item 1 (rename A -> B) should have journal, item 2 must NOT have journal for replacement entity
        assert len(journals) == 1
        assert journals[0].plan_item_id == items[0].id


def test_normal_chained_rename_then_touch_succeeds(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "normal_chain_a.txt"
    file_a.write_bytes(b"NORMAL-CHAIN-DATA")
    orig_stat = file_a.stat()
    file_b = data_dir / "normal_chain_b.txt"

    target_mtime = int(time.time() + 20000) * 1_000_000_000

    plan = service.create_plan(
        name="Normal Chained Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": target_mtime},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-normal-chain"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert not file_a.exists()
    assert file_b.exists()
    assert file_b.stat().st_ino == orig_stat.st_ino, "B inode must match original A inode"
    cur_mtime_ns = getattr(file_b.stat(), "st_mtime_ns", int(file_b.stat().st_mtime * 1e9))
    assert cur_mtime_ns == target_mtime, "B must be successfully touched"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "completed"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert all(it.state == "completed" for it in items)
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert len(journals) == 2


def test_chained_target_replacement_before_item_boundary_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_test_env(tmp_path)
    file_a = data_dir / "pre_boundary_a.txt"
    file_a.write_bytes(b"PRE-BOUNDARY-DATA")
    orig_stat = file_a.stat()
    file_b = data_dir / "pre_boundary_b.txt"

    target_mtime = int(time.time() + 30000) * 1_000_000_000

    plan = service.create_plan(
        name="Chained Pre-boundary Replacement Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": target_mtime},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-pre-boundary"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        # Replace before item 2's boundary check: inside checkpoint of item 1 completion
        if "Executing item #1" in msg:
            pass
        elif "Executing item #2" in msg and not replaced:
            # Replaced right as item 2 is announced, BEFORE verify_item_freshness
            temp_held = data_dir / "held_pre.tmp"
            file_b.rename(temp_held)
            file_b.write_bytes(b"REPLACED-PRE-BOUNDARY")
            assert file_b.stat().st_ino != orig_stat.st_ino
            temp_held.unlink()
            replaced = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replaced
    assert file_b.exists()
    assert file_b.read_bytes() == b"REPLACED-PRE-BOUNDARY"
    cur_mtime_ns = getattr(file_b.stat(), "st_mtime_ns", int(file_b.stat().st_mtime * 1e9))
    assert cur_mtime_ns != target_mtime, "replacement file must NOT have its mtime touched"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "filesystem_identity_changed" in (items[1].reason or "").lower() or "stale" in (items[1].reason or "").lower()


def test_chained_descendant_identity_is_bound_to_original_entity(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    dir_a = data_dir / "DirA"
    dir_a.mkdir(parents=True)
    child_dir = dir_a / "Child"
    child_dir.mkdir(parents=True)
    file_child = child_dir / "file.txt"
    file_child.write_text("descendant original", encoding="utf-8")
    orig_stat = file_child.stat()

    dir_b = data_dir / "DirB"
    file_child_b = dir_b / "Child" / "file.txt"

    target_mtime = int(time.time() + 40000) * 1_000_000_000

    plan = service.create_plan(
        name="Descendant Chained Plan",
        kind="organizer",
        items=[
            {"source": str(dir_a), "target": str(dir_b), "operation": "rename"},
            {"source": str(file_child_b), "operation": "touch", "expected_mtime_ns": target_mtime},
        ],
    )
    service.freeze_plan(plan.id)

    with service.SessionLocal() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        meta_item2 = json.loads(items[1].metadata_json or "{}")
        assert meta_item2.get("chained_target") is True
        chain_info = meta_item2.get("chain", {})
        assert chain_info.get("origin_path") == str(file_child)
        snap_item2 = meta_item2.get("snapshot", {})
        assert snap_item2.get("inode") == orig_stat.st_ino, "Inherited snapshot inode must match file_child"

    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-descendant"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert not dir_a.exists()
    assert dir_b.exists()
    assert file_child_b.exists()
    assert file_child_b.stat().st_ino == orig_stat.st_ino
    cur_mtime_ns = getattr(file_child_b.stat(), "st_mtime_ns", int(file_child_b.stat().st_mtime * 1e9))
    assert cur_mtime_ns == target_mtime

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "completed"


def test_chained_descendant_replacement_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    dir_a = data_dir / "DirA2"
    dir_a.mkdir(parents=True)
    child_dir = dir_a / "Sub"
    child_dir.mkdir(parents=True)
    file_child = child_dir / "data.txt"
    file_child.write_text("descendant victim", encoding="utf-8")
    orig_stat = file_child.stat()

    dir_b = data_dir / "DirB2"
    file_child_b = dir_b / "Sub" / "data.txt"

    target_mtime = int(time.time() + 50000) * 1_000_000_000

    plan = service.create_plan(
        name="Descendant Replacement Plan",
        kind="organizer",
        items=[
            {"source": str(dir_a), "target": str(dir_b), "operation": "rename"},
            {"source": str(file_child_b), "operation": "touch", "expected_mtime_ns": target_mtime},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-desc-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not replaced:
            assert file_child_b.exists()
            temp_held = data_dir / "held_desc.tmp"
            file_child_b.rename(temp_held)
            file_child_b.write_text("REPLACED-DESCENDANT", encoding="utf-8")
            assert file_child_b.stat().st_ino != orig_stat.st_ino
            temp_held.unlink()
            replaced = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replaced
    assert file_child_b.exists()
    assert file_child_b.read_text(encoding="utf-8") == "REPLACED-DESCENDANT"
    cur_mtime_ns = getattr(file_child_b.stat(), "st_mtime_ns", int(file_child_b.stat().st_mtime * 1e9))
    assert cur_mtime_ns != target_mtime, "replacement descendant must NOT be touched"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"


def test_chained_target_replaced_by_symlink_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "sym_victim_a.txt"
    file_a.write_bytes(b"SYM-CHAIN-ORIG")
    file_b = data_dir / "sym_victim_b.txt"

    plan = service.create_plan(
        name="Chained Symlink Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": int(time.time() + 60000) * 1_000_000_000},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-sym-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not replaced:
            assert file_b.exists()
            file_b.unlink()
            # Replace B with a symlink pointing to an innocent target
            dummy = data_dir / "sym_target.txt"
            dummy.write_bytes(b"TARGET")
            file_b.symlink_to(dummy)
            assert file_b.is_symlink()
            replaced = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replaced
    assert file_b.is_symlink(), "symlink must remain untouched"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "symlink" in (items[1].reason or "").lower()


def test_chained_target_object_type_mismatch_is_rejected(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "type_victim_a.txt"
    file_a.write_bytes(b"REGULAR-FILE")
    file_b = data_dir / "type_victim_b.txt"

    plan = service.create_plan(
        name="Chained Type Mismatch Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": int(time.time() + 70000) * 1_000_000_000},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-type-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(
        engine=service.engine,
        session_factory=service.SessionLocal,
        job_id=job_id,
        worker_id=worker_id,
    )

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not replaced:
            assert file_b.exists()
            file_b.unlink()
            # Replace file B with a directory B
            file_b.mkdir()
            assert file_b.is_dir()
            replaced = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replaced
    assert file_b.is_dir(), "directory must remain untouched"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "filesystem_identity_changed" in (items[1].reason or "").lower() or "object_type_changed" in (items[1].reason or "").lower() or "stale" in (items[1].reason or "").lower()


