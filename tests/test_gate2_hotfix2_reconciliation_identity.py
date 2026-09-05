from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
from sqlalchemy import select
from app.config import Settings
from app.models import (
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    WorkJob,
    utcnow,
)
from app.service import FileCenterService
from app.tasks.handlers import _reconcile_executing_item, gather_reconcile_evidence


def _setup_service(tmp_path: Path):
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
    svc = FileCenterService(settings)
    return svc, settings, data_dir, trash_dir


def test_rename_crash_reconcile_rejects_unrelated_target(tmp_path: Path):
    svc, settings, data_dir, _ = _setup_service(tmp_path)

    src = data_dir / "source.txt"
    tgt = data_dir / "target.txt"

    src.write_text("original source", encoding="utf-8")
    st_src = src.stat()

    plan = svc.create_plan(
        name="Crash Reconcile Plan",
        kind="organize",
        items=[{"operation": "rename", "source": str(src), "target": str(tgt)}],
    )
    svc.freeze_plan(plan.id)

    # Create unrelated tgt while src is still on disk -> guaranteed different inode!
    tgt.write_text("unrelated file placed by third party", encoding="utf-8")
    st_tgt = tgt.stat()
    assert st_tgt.st_ino != st_src.st_ino
    # Now remove src to simulate it missing after crash
    src.unlink()

    # Simulate item in 'executing' state after crash
    now = utcnow()
    with svc.SessionLocal() as session:
        job = WorkJob(id=100, kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": plan.id}), created_at=now)
        session.add(job)
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        item.state = "executing"
        item.metadata_json = json.dumps({
            "execution": {
                "task_id": 100,
                "operation": "rename",
                "source_stat": {
                    "object_type": "file",
                    "size": st_src.st_size,
                    "mtime_ns": getattr(st_src, "st_mtime_ns", int(st_src.st_mtime * 1e9)),
                    "device": st_src.st_dev,
                    "inode": st_src.st_ino,
                },
                "metadata_before": {
                    "object_type": "file",
                    "size": st_src.st_size,
                    "mtime_ns": getattr(st_src, "st_mtime_ns", int(st_src.st_mtime * 1e9)),
                    "device": st_src.st_dev,
                    "inode": st_src.st_ino,
                }
            }
        })
        session.commit()

        # Run reconciliation
        _reconcile_executing_item(session, item, plan.id, job_id=100, user_id=None, settings=settings, now=now)
        session.commit()

        # Verify: reconciliation MUST fail-closed because inode doesn't match!
        assert item.state == "failed"
        assert "target identity mismatch" in (item.reason or "")

        # No false OperationJournal!
        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
        assert journal is None


def test_rename_crash_reconcile_accepts_matching_target_and_writes_full_metadata(tmp_path: Path):
    svc, settings, data_dir, _ = _setup_service(tmp_path)

    src = data_dir / "source.txt"
    tgt = data_dir / "target.txt"

    src.write_text("actual moved content", encoding="utf-8")
    st_src = src.stat()

    plan = svc.create_plan(
        name="Crash Reconcile Success Plan",
        kind="organize",
        items=[{"operation": "rename", "source": str(src), "target": str(tgt)}],
    )
    svc.freeze_plan(plan.id)

    # True rename occurred before crash: rename src to tgt directly
    os.rename(src, tgt)
    st_tgt = tgt.stat()
    assert st_tgt.st_ino == st_src.st_ino

    now = utcnow()
    with svc.SessionLocal() as session:
        job = WorkJob(id=101, kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": plan.id}), created_at=now)
        session.add(job)
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        item.state = "executing"
        item.metadata_json = json.dumps({
            "execution": {
                "task_id": 101,
                "operation": "rename",
                "source_stat": {
                    "object_type": "file",
                    "size": st_src.st_size,
                    "mtime_ns": getattr(st_src, "st_mtime_ns", int(st_src.st_mtime * 1e9)),
                    "device": st_src.st_dev,
                    "inode": st_src.st_ino,
                },
                "metadata_before": {
                    "object_type": "file",
                    "size": st_src.st_size,
                    "mtime_ns": getattr(st_src, "st_mtime_ns", int(st_src.st_mtime * 1e9)),
                    "device": st_src.st_dev,
                    "inode": st_src.st_ino,
                }
            }
        })
        session.commit()

        # Run reconciliation
        _reconcile_executing_item(session, item, plan.id, job_id=101, user_id=None, settings=settings, now=now)
        session.commit()

        # Verify: reconciliation succeeds
        assert item.state == "completed"

        # Verify journal metadata is NOT "{}"
        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
        assert journal is not None
        meta_b = json.loads(journal.metadata_before_json)
        meta_a = json.loads(journal.metadata_after_json)

        assert meta_b != {}, "metadata_before_json must not be empty"
        assert meta_a != {}, "metadata_after_json must not be empty"
        assert meta_b["inode"] == st_src.st_ino
        assert meta_a["inode"] == st_tgt.st_ino
        assert meta_a["size"] == st_tgt.st_size


def test_quarantine_crash_reconcile_rejects_unrelated_target(tmp_path: Path):
    svc, settings, data_dir, trash_dir = _setup_service(tmp_path)

    src = data_dir / "quar_src.txt"
    src.write_text("quar content", encoding="utf-8")
    st_src = src.stat()

    plan = svc.create_plan(
        name="Quar Crash Plan",
        kind="organize",
        items=[{"operation": "quarantine", "source": str(src)}],
    )
    svc.freeze_plan(plan.id)

    q_file = trash_dir / "fake_quar.txt"
    q_file.write_text("unrelated fake quarantine content", encoding="utf-8")
    st_q = q_file.stat()
    assert st_q.st_ino != st_src.st_ino
    src.unlink()

    now = utcnow()
    with svc.SessionLocal() as session:
        job = WorkJob(id=102, kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": plan.id}), created_at=now)
        session.add(job)
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        item.state = "executing"
        item.metadata_json = json.dumps({
            "execution": {
                "task_id": 102,
                "operation": "quarantine",
                "source_stat": {
                    "object_type": "file",
                    "size": st_src.st_size,
                    "mtime_ns": getattr(st_src, "st_mtime_ns", int(st_src.st_mtime * 1e9)),
                    "device": st_src.st_dev,
                    "inode": st_src.st_ino,
                }
            }
        })
        q_entry = QuarantineEntry(
            plan_item_id=item.id,
            task_id=102,
            original_path=str(src),
            quarantine_path=str(q_file),
            state="preparing",
            created_at=now,
            updated_at=now,
        )
        session.add(q_entry)
        session.commit()

        _reconcile_executing_item(session, item, plan.id, job_id=102, user_id=None, settings=settings, now=now)
        session.commit()

        assert item.state == "failed"
        assert "target identity mismatch" in (item.reason or "")
        refreshed_q = session.get(QuarantineEntry, q_entry.id)
        assert refreshed_q.state == "abandoned"

        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
        assert journal is None


def test_quarantine_crash_reconcile_accepts_matching_target_with_metadata(tmp_path: Path):
    svc, settings, data_dir, trash_dir = _setup_service(tmp_path)

    src = data_dir / "quar_src_ok.txt"
    src.write_text("quar content to match", encoding="utf-8")
    st_src = src.stat()

    plan = svc.create_plan(
        name="Quar Crash Success Plan",
        kind="organize",
        items=[{"operation": "quarantine", "source": str(src)}],
    )
    svc.freeze_plan(plan.id)

    q_file = trash_dir / "real_quar.txt"
    os.rename(src, q_file)
    st_q = q_file.stat()
    assert st_q.st_ino == st_src.st_ino

    now = utcnow()
    with svc.SessionLocal() as session:
        job = WorkJob(id=103, kind="batch-plan-execute", status="running", state_json=json.dumps({"plan_id": plan.id}), created_at=now)
        session.add(job)
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        item.state = "executing"
        item.metadata_json = json.dumps({
            "execution": {
                "task_id": 103,
                "operation": "quarantine",
                "source_stat": {
                    "object_type": "file",
                    "size": st_src.st_size,
                    "mtime_ns": getattr(st_src, "st_mtime_ns", int(st_src.st_mtime * 1e9)),
                    "device": st_src.st_dev,
                    "inode": st_src.st_ino,
                }
            }
        })
        q_entry = QuarantineEntry(
            plan_item_id=item.id,
            task_id=103,
            original_path=str(src),
            quarantine_path=str(q_file),
            state="preparing",
            created_at=now,
            updated_at=now,
        )
        session.add(q_entry)
        session.commit()

        evidence = gather_reconcile_evidence(q_file)
        _reconcile_executing_item(session, item, plan.id, job_id=103, user_id=None, settings=settings, now=now, precomputed_evidence=evidence)
        session.commit()

        assert item.state == "completed"
        refreshed_q = session.get(QuarantineEntry, q_entry.id)
        assert refreshed_q.state == "active"

        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
        assert journal is not None
        meta_b = json.loads(journal.metadata_before_json)
        meta_a = json.loads(journal.metadata_after_json)
        assert meta_b != {}
        assert meta_a != {}
        assert meta_a["inode"] == st_src.st_ino

