from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
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
# 1. Chained Same-Inode Metadata Mutation (chmod vs mtime)
# =====================================================================

def test_review_chained_same_inode_metadata_mutation_allowed(tmp_path: Path):
    """
    If an external process changes permissions (chmod) on the chained output entity,
    its device, inode, size, mtime remain unchanged.
    Since it is the exact physical entity produced by the producer, the consumer should succeed.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "meta_a.txt"
    file_a.write_bytes(b"SAME-INODE-PAYLOAD")
    orig_stat = file_a.stat()
    file_b = data_dir / "meta_b.txt"

    target_mtime = int(time.time() + 30000) * 1_000_000_000

    plan = service.create_plan(
        name="Chained Same-Inode Chmod Plan",
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

    worker_id = "test-worker-chmod"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)

    orig_checkpoint = ctx.checkpoint
    chmod_done = False

    def race_checkpoint(*args, **kwargs):
        nonlocal chmod_done
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not chmod_done:
            assert file_b.exists()
            os.chmod(file_b, 0o600)
            assert file_b.stat().st_ino == orig_stat.st_ino
            chmod_done = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert chmod_done
    assert file_b.exists()
    assert file_b.stat().st_ino == orig_stat.st_ino
    cur_mtime_ns = getattr(file_b.stat(), "st_mtime_ns", int(file_b.stat().st_mtime * 1e9))
    assert cur_mtime_ns == target_mtime, "touch must succeed on same-inode entity"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "completed"
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert len(journals) == 2


def test_review_chained_same_inode_mtime_tamper_is_rejected(tmp_path: Path):
    """
    If an external process tampers with the mtime of the chained entity before touch runs,
    freshness validation must detect mtime_changed and reject the mutation.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "mtime_tamper_a.txt"
    file_a.write_bytes(b"MTIME-TAMPER-PAYLOAD")
    orig_stat = file_a.stat()
    file_b = data_dir / "mtime_tamper_b.txt"

    target_mtime = int(time.time() + 50000) * 1_000_000_000

    plan = service.create_plan(
        name="Chained Mtime Tamper Plan",
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

    worker_id = "test-worker-mtime-tamper"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)

    orig_checkpoint = ctx.checkpoint
    tamper_done = False

    def race_checkpoint(*args, **kwargs):
        nonlocal tamper_done
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not tamper_done:
            assert file_b.exists()
            # External process modifies mtime (same inode, but mtime changed)
            tamper_mtime = time.time() - 1000
            os.utime(file_b, (tamper_mtime, tamper_mtime))
            assert file_b.stat().st_ino == orig_stat.st_ino
            tamper_done = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert tamper_done
    cur_mtime_ns = getattr(file_b.stat(), "st_mtime_ns", int(file_b.stat().st_mtime * 1e9))
    assert cur_mtime_ns != target_mtime, "tampered file must NOT have its target mtime applied"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "mtime_changed" in (items[1].reason or "").lower() or "stale" in (items[1].reason or "").lower()
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert len(journals) == 1


# =====================================================================
# 2. Nested 3-Level Descendant Origin Binding and Replacement
# =====================================================================

def test_review_nested_three_level_descendant_origin_binding_and_replacement(tmp_path: Path):
    """
    Tree: DirA / Sub1 / Sub2 / data.txt
    Plan:
      1. rename DirA -> DirB
      2. rename DirB/Sub1 -> DirB/Sub1_New
      3. touch DirB/Sub1_New/Sub2/data.txt
    Item 3 must trace back to DirA/Sub1/Sub2/data.txt and bind its frozen inode.
    If replaced before item 3 runs, item 3 must abort with PLAN_STALE.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    dir_a = data_dir / "DirA"
    sub1 = dir_a / "Sub1"
    sub2 = sub1 / "Sub2"
    sub2.mkdir(parents=True)
    file_data = sub2 / "data.txt"
    file_data.write_text("deep descendant content", encoding="utf-8")
    orig_stat = file_data.stat()

    dir_b = data_dir / "DirB"
    sub1_new = dir_b / "Sub1_New"
    file_data_final = sub1_new / "Sub2" / "data.txt"

    target_mtime = int(time.time() + 45000) * 1_000_000_000

    plan = service.create_plan(
        name="Deep Descendant Plan",
        kind="organizer",
        items=[
            {"source": str(dir_a), "target": str(dir_b), "operation": "rename"},
            {"source": str(dir_b / "Sub1"), "target": str(sub1_new), "operation": "rename"},
            {"source": str(file_data_final), "operation": "touch", "expected_mtime_ns": target_mtime},
        ],
    )
    service.freeze_plan(plan.id)

    with service.SessionLocal() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        meta_item3 = json.loads(items[2].metadata_json or "{}")
        assert meta_item3.get("chained_target") is True
        chain_info = meta_item3.get("chain", {})
        assert chain_info.get("origin_path") == str(file_data), f"Expected origin {file_data}, got {chain_info.get('origin_path')}"
        snap_item3 = meta_item3.get("snapshot", {})
        assert snap_item3.get("inode") == orig_stat.st_ino, "Inherited inode must match deep descendant"

    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-deep-desc"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        if "Executing item #3" in msg and not replaced:
            assert file_data_final.exists()
            temp_held = data_dir / "held_deep.tmp"
            file_data_final.rename(temp_held)
            file_data_final.write_text("REPLACED-DEEP-CONTENT", encoding="utf-8")
            assert file_data_final.stat().st_ino != orig_stat.st_ino
            temp_held.unlink()
            replaced = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replaced
    assert file_data_final.exists()
    assert file_data_final.read_text(encoding="utf-8") == "REPLACED-DEEP-CONTENT"
    cur_mtime_ns = getattr(file_data_final.stat(), "st_mtime_ns", int(file_data_final.stat().st_mtime * 1e9))
    assert cur_mtime_ns != target_mtime, "replaced deep descendant must NOT be touched"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "completed"
        assert items[2].state == "failed"
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert len(journals) == 2


# =====================================================================
# 3. Multiple Producers Disambiguation by Recency
# =====================================================================

def test_review_multiple_producers_disambiguation_by_recency(tmp_path: Path):
    """
    Plan:
      1. rename A -> B
      2. rename C -> B  (overwriting B)
      3. touch B
    Item 3 must resolve provenance to Item 2 (whose origin is C), not Item 1 (A).
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "mult_a.txt"
    file_a.write_bytes(b"PRODUCER-A")
    file_c = data_dir / "mult_c.txt"
    file_c.write_bytes(b"PRODUCER-C")
    stat_c = file_c.stat()
    file_b = data_dir / "mult_b.txt"

    plan = service.create_plan(
        name="Multiple Producers Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_c), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": int(time.time() + 10000) * 1_000_000_000},
        ],
    )
    service.freeze_plan(plan.id)

    with service.SessionLocal() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        meta_item3 = json.loads(items[2].metadata_json or "{}")
        assert meta_item3.get("chained_target") is True
        chain_info = meta_item3.get("chain", {})
        # Must resolve to Item 2 (C -> B)
        assert chain_info.get("producer_item_id") == items[1].id
        assert chain_info.get("origin_path") == str(file_c)
        snap_item3 = meta_item3.get("snapshot", {})
        assert snap_item3.get("inode") == stat_c.st_ino


# =====================================================================
# 4. Future Producer Not Accessible to Earlier Consumer
# =====================================================================

def test_review_future_producer_not_accessible_to_earlier_consumer(tmp_path: Path):
    """
    If an item targets a path that does NOT exist at freeze time,
    and a producer targeting that path appears AFTER it in sequence:
      1. touch B (B does not exist)
      2. rename A -> B (A exists)
    Item 1 cannot reference future producer Item 2. Freeze must reject Item 1.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "future_a.txt"
    file_a.write_bytes(b"FUTURE-PRODUCER-A")
    file_b = data_dir / "future_b.txt"

    plan = service.create_plan(
        name="Future Producer Inversion Plan",
        kind="organizer",
        items=[
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": int(time.time() + 10000) * 1_000_000_000},
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
        ],
    )
    with pytest.raises((FileNotFoundError, ValueError, KeyError)):
        service.freeze_plan(plan.id)


# =====================================================================
# 5. Parent / Child Producer Overlap
# =====================================================================

def test_review_parent_child_producer_overlap_resolution(tmp_path: Path):
    """
    DirA / Child / doc.txt
    Plan:
      1. rename DirA -> DirB
      2. rename DirB/Child -> DirB/NewChild
      3. touch DirB/NewChild/doc.txt
    Verify provenance unfolds sequentially without skipping intermediate child rename.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    dir_a = data_dir / "OverlapA"
    child = dir_a / "Child"
    child.mkdir(parents=True)
    doc = child / "doc.txt"
    doc.write_text("overlap document", encoding="utf-8")
    doc_stat = doc.stat()

    dir_b = data_dir / "OverlapB"
    new_child = dir_b / "NewChild"
    doc_final = new_child / "doc.txt"

    target_mtime = int(time.time() + 25000) * 1_000_000_000

    plan = service.create_plan(
        name="Overlap Resolution Plan",
        kind="organizer",
        items=[
            {"source": str(dir_a), "target": str(dir_b), "operation": "rename"},
            {"source": str(dir_b / "Child"), "target": str(new_child), "operation": "rename"},
            {"source": str(doc_final), "operation": "touch", "expected_mtime_ns": target_mtime},
        ],
    )
    service.freeze_plan(plan.id)

    with service.SessionLocal() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        meta_item3 = json.loads(items[2].metadata_json or "{}")
        assert meta_item3.get("chained_target") is True
        chain_info = meta_item3.get("chain", {})
        assert chain_info.get("origin_path") == str(doc)
        snap_item3 = meta_item3.get("snapshot", {})
        assert snap_item3.get("inode") == doc_stat.st_ino

    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-overlap"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert not dir_a.exists()
    assert dir_b.exists()
    assert new_child.exists()
    assert doc_final.exists()
    assert doc_final.stat().st_ino == doc_stat.st_ino
    cur_mtime = getattr(doc_final.stat(), "st_mtime_ns", int(doc_final.stat().st_mtime * 1e9))
    assert cur_mtime == target_mtime

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "completed"


# =====================================================================
# 6. Chained Symlink Replacements (Inside root, outside root, dangling)
# =====================================================================

@pytest.mark.parametrize("symlink_kind", ["inside", "outside", "dangling"])
def test_review_chained_target_symlink_replacements_rejected(tmp_path: Path, symlink_kind: str):
    """
    Verify that replacing a chained target with any symlink (inside allowed roots,
    outside allowed roots, or dangling) fails closed with symlink_replaced or symlink_escape.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / f"sym_test_a_{symlink_kind}.txt"
    file_a.write_bytes(b"SYM-PAYLOAD")
    file_b = data_dir / f"sym_test_b_{symlink_kind}.txt"

    plan = service.create_plan(
        name=f"Symlink {symlink_kind} Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": int(time.time() + 15000) * 1_000_000_000},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = f"test-worker-sym-{symlink_kind}"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not replaced:
            assert file_b.exists()
            file_b.unlink()
            if symlink_kind == "inside":
                target_f = data_dir / "target_inside.txt"
                target_f.write_bytes(b"INSIDE")
                file_b.symlink_to(target_f)
            elif symlink_kind == "outside":
                outside_f = tmp_path / "outside_allowed.txt"
                outside_f.write_bytes(b"OUTSIDE")
                file_b.symlink_to(outside_f)
            elif symlink_kind == "dangling":
                dangling_target = data_dir / "nonexistent_target.txt"
                file_b.symlink_to(dangling_target)
            assert os.path.islink(file_b)
            replaced = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replaced
    assert os.path.islink(file_b), "symlink must remain untouched"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "symlink" in (items[1].reason or "").lower()


# =====================================================================
# 7. Chained Directory Replaced by File Rejected
# =====================================================================

def test_review_chained_directory_replaced_by_file_rejected(tmp_path: Path):
    """
    Plan:
      1. rename dir_a -> dir_b (directory)
      2. rename dir_b -> dir_c
    Before item 2 runs, dir_b is replaced by a regular file!
    Item 2 must reject due to filesystem_identity_changed.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    dir_a = data_dir / "dir_type_a"
    dir_a.mkdir()
    dir_b = data_dir / "dir_type_b"
    dir_c = data_dir / "dir_type_c"

    plan = service.create_plan(
        name="Chained Dir Type Mismatch Plan",
        kind="organizer",
        items=[
            {"source": str(dir_a), "target": str(dir_b), "operation": "rename"},
            {"source": str(dir_b), "target": str(dir_c), "operation": "rename"},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-dir-type-race"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        if "Executing item #2" in msg and not replaced:
            assert dir_b.exists() and dir_b.is_dir()
            dir_b.rmdir()
            # Replace with a regular file
            dir_b.write_text("I AM A REGULAR FILE NOW", encoding="utf-8")
            assert dir_b.is_file()
            replaced = True
        return orig_checkpoint(*args, **kwargs)

    ctx.checkpoint = race_checkpoint

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert replaced
    assert dir_b.is_file(), "file must remain untouched"
    assert not dir_c.exists(), "target dir_c must NOT be created"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "filesystem_identity_changed" in (items[1].reason or "").lower() or "stale" in (items[1].reason or "").lower()


# =====================================================================
# 8. Producer Failure Halts Consumer (No Deferred Bypass)
# =====================================================================

def test_review_producer_failure_halts_chained_consumer(tmp_path: Path):
    """
    Plan:
      1. rename A -> B
      2. touch B
    If A is removed before Item 1 executes, Item 1 fails.
    When Item 2 boundary check runs, B does NOT exist.
    Item 2 must NOT treat B as deferred missing; it must fail closed and halt.
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "fail_prod_a.txt"
    file_a.write_bytes(b"FAIL-A")
    file_b = data_dir / "fail_prod_b.txt"

    plan = service.create_plan(
        name="Producer Failure Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "operation": "touch", "expected_mtime_ns": int(time.time() + 10000) * 1_000_000_000},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    # Now unlink file_a AFTER enqueue but BEFORE worker execution
    file_a.unlink()
    assert not file_a.exists()

    worker_id = "test-worker-fail-prod"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    handler.run(job, ctx, settings)

    assert not file_b.exists()

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status in ("stale", "failed")
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "failed"
        assert items[1].state in ("planned", "validated", "failed")
        assert items[1].state != "completed"
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert len(journals) == 0, "No journal must be created when producer fails"


# =====================================================================
# 9. Final Fence Catches Replacement in Chained Rename Operation
# =====================================================================

def test_review_final_fence_catches_replacement_in_chained_rename(tmp_path: Path):
    """
    Plan:
      1. rename A -> B
      2. rename B -> C
    Hook right between item 2 boundary check and item 2 final mutation fence:
    replace B with a new inode.
    Item 2 must be rejected at final mutation fence:
      - 0 physical rename of replacement B to C
      - C does NOT exist
      - 0 operation journal for item 2
      - item 2 failed
      - plan partial with PLAN_STALE
    """
    client, service, settings, data_dir, _ = _setup_test_env(tmp_path)
    file_a = data_dir / "fence_a.txt"
    file_a.write_bytes(b"FENCE-PAYLOAD-ORIG")
    orig_stat = file_a.stat()
    file_b = data_dir / "fence_b.txt"
    file_c = data_dir / "fence_c.txt"

    plan = service.create_plan(
        name="Chained Rename Final Fence Plan",
        kind="organizer",
        items=[
            {"source": str(file_a), "target": str(file_b), "operation": "rename"},
            {"source": str(file_b), "target": str(file_c), "operation": "rename"},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200
    job_id = resp.json()["work_job_id"]

    worker_id = "test-worker-chain-fence"
    _acquire_lease(service, worker_id)
    handler = get_handler("batch-plan-execute")
    ctx = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)

    orig_checkpoint = ctx.checkpoint
    replaced = False

    def race_checkpoint(*args, **kwargs):
        nonlocal replaced
        msg = kwargs.get("progress_message", "")
        # Hook at item 2 boundary checkpoint (AFTER boundary check, BEFORE Phase 1 / Final Fence)
        if "Executing item #2" in msg and not replaced:
            assert file_b.exists()
            temp_held = data_dir / "held_fence.tmp"
            file_b.rename(temp_held)
            file_b.write_bytes(b"REPLACED-AT-FENCE")
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
    assert file_b.read_bytes() == b"REPLACED-AT-FENCE", "replacement must NOT be moved to C"
    assert not file_c.exists(), "destination C must NOT be created"

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        assert p.status == "partial"
        meta = json.loads(p.metadata_json or "{}")
        assert meta.get("execution", {}).get("termination_reason") == "PLAN_STALE"
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "failed"
        assert "filesystem_identity_changed" in (items[1].reason or "").lower() or "stale" in (items[1].reason or "").lower()
        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert len(journals) == 1
        assert journals[0].plan_item_id == items[0].id
