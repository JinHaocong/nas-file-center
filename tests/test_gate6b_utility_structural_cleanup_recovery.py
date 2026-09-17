from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import BatchPlan, BatchPlanItem, OperationJournal, WorkJob, utcnow
from app.tasks.handlers import _reconcile_executing_item


def _seed_executing_structural_cleanup(tmp_path):
    data_root = tmp_path / "data"
    wrapper = data_root / "utility" / "A" / "B"
    wrapper.mkdir(parents=True)
    quarantine_root = data_root / ".nas-file-center-trash"
    assert not quarantine_root.exists()

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    db_path = config_dir / "app.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=db_path,
        allowed_roots_raw=str(data_root),
        quarantine_root=quarantine_root,
        protect_last_file=True,
    )

    st = os.lstat(wrapper)
    candidate_id = "native-cleanup-recovery"
    target = data_root / "utility" / "A" / "C"
    plan_metadata = {
        "source": "workflow",
        "workflow_mode": "utility",
        "compile_context": {
            "utility_action": "single_child_wrapper_collapse",
        },
    }
    item_metadata = {
        "candidate_id": candidate_id,
        "utility_action": "single_child_wrapper_collapse",
        "wrapper_path": str(wrapper),
        "child_path": str(wrapper / "C"),
        "target_path": str(target),
    }
    cleanup_metadata = dict(item_metadata)
    cleanup_metadata["execution"] = {
        "phase": "intent",
        "operation": "rmdir_empty",
        "source_stat": {
            "object_type": "directory",
            "device": st.st_dev,
            "inode": st.st_ino,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
        },
        "metadata_before": {
            "object_type": "directory",
            "device": st.st_dev,
            "inode": st.st_ino,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
        },
    }

    with SessionLocal() as session:
        plan = BatchPlan(
            name="native cleanup recovery",
            kind="workflow-1",
            status="executing",
            expected_changes=2,
            metadata_json=json.dumps(plan_metadata),
        )
        session.add(plan)
        session.flush()
        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id}),
        )
        session.add(job)
        session.flush()
        session.add_all([
            BatchPlanItem(
                plan_id=plan.id,
                sequence=1,
                operation="move",
                source_path=str(wrapper / "C"),
                target_path=str(target),
                keep_path=None,
                expected_size=0,
                expected_mtime_ns=0,
                expected_device=0,
                expected_inode=0,
                expected_hash=None,
                state="completed",
                reason="moved",
                metadata_json=json.dumps(item_metadata),
            ),
            BatchPlanItem(
                plan_id=plan.id,
                sequence=2,
                operation="rmdir_empty",
                source_path=str(wrapper),
                target_path=None,
                keep_path=None,
                expected_size=0,
                expected_mtime_ns=0,
                expected_device=st.st_dev,
                expected_inode=st.st_ino,
                expected_hash=None,
                state="executing",
                reason=None,
                metadata_json=json.dumps(cleanup_metadata),
            ),
        ])
        session.commit()
        cleanup_id = session.scalar(
            select(BatchPlanItem.id).where(
                BatchPlanItem.plan_id == plan.id,
                BatchPlanItem.sequence == 2,
            )
        )
        return (
            SessionLocal,
            int(plan.id),
            int(cleanup_id),
            int(job.id),
            wrapper,
            quarantine_root,
            settings,
        )


def test_recovery_retries_authorized_empty_wrapper_without_quarantine_root(tmp_path):
    SessionLocal, plan_id, cleanup_id, job_id, wrapper, quarantine_root, settings = _seed_executing_structural_cleanup(tmp_path)

    with SessionLocal() as session:
        item = session.get(BatchPlanItem, cleanup_id)
        assert item is not None
        _reconcile_executing_item(
            session,
            item,
            plan_id,
            job_id=job_id,
            user_id=None,
            settings=settings,
            now=utcnow(),
        )
        assert item.state == "planned"
        assert item.reason is None
        assert wrapper.is_dir()
        assert not quarantine_root.exists()


def test_recovery_converges_completed_structural_cleanup_without_quarantine_root(tmp_path):
    SessionLocal, plan_id, cleanup_id, job_id, wrapper, quarantine_root, settings = _seed_executing_structural_cleanup(tmp_path)
    os.rmdir(wrapper)
    assert not wrapper.exists()

    with SessionLocal() as session:
        item = session.get(BatchPlanItem, cleanup_id)
        assert item is not None
        _reconcile_executing_item(
            session,
            item,
            plan_id,
            job_id=job_id,
            user_id=None,
            settings=settings,
            now=utcnow(),
        )
        assert item.state == "completed"
        assert "structural cleanup" in (item.reason or "")
        journal = session.scalar(
            select(OperationJournal).where(OperationJournal.plan_item_id == cleanup_id)
        )
        assert journal is not None
        after = json.loads(journal.after_json)
        assert after["logical_removed"] is True
        assert after["removed"] is True
        assert after["preserved"] is False
        assert after["structural_cleanup"] is True
        assert after["quarantine_path"] is None
        assert not quarantine_root.exists()
