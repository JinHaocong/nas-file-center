import json
import os
from pathlib import Path
import pytest

from app.models import IndexRoot, User, WorkJob, BatchPlan, BatchPlanItem, OperationJournal, utcnow
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password
from app.tasks.handlers import _reconcile_executing_item


@pytest.fixture
def recovery_test_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    db_path = config_dir / "app.db"
    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=db_path,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        protect_last_file=True,
        allow_mutation=True,
        allow_delete=True,
    )

    service = FileCenterService(settings)

    root_path = data_dir / "root1"
    root_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root_path))
        session.add(r)
        reg_user = User(
            id=1,
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        )
        session.add(reg_user)
        job = WorkJob(
            id=1,
            kind="batch-plan-execute",
            status="running",
        )
        session.add(job)
        session.commit()

    return {
        "service": service,
        "settings": settings,
        "data_dir": data_dir,
        "root_path": root_path,
        "quarantine_dir": quarantine_dir,
    }


def test_reconcile_rmdir_empty_before_mutation_returns_to_planned(recovery_test_env):
    service = recovery_test_env["service"]
    settings = recovery_test_env["settings"]
    root = recovery_test_env["root_path"]

    dir_to_rm = root / "empty_dir"
    dir_to_rm.mkdir()
    st = dir_to_rm.stat()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="p1", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(dir_to_rm),
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(root),
                "execution": {
                    "source_stat": {
                        "device": st.st_dev,
                        "inode": st.st_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id
        plan_id = plan.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "planned"
        assert item.reason is None
        journals = session.query(OperationJournal).filter_by(plan_item_id=item_id).all()
        assert len(journals) == 0


def test_reconcile_rmdir_empty_after_successful_removal_completes_and_adds_one_journal(recovery_test_env):
    service = recovery_test_env["service"]
    settings = recovery_test_env["settings"]
    root = recovery_test_env["root_path"]

    dir_to_rm = root / "deleted_empty_dir"
    dir_to_rm.mkdir()
    st = dir_to_rm.stat()
    dir_to_rm.rmdir()  # Removed on disk, but DB was left executing

    with service.SessionLocal() as session:
        plan = BatchPlan(name="p1", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(dir_to_rm),
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(root),
                "execution": {
                    "source_stat": {
                        "device": st.st_dev,
                        "inode": st.st_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id
        plan_id = plan.id

    # First reconciliation run
    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "completed"
        journals = session.query(OperationJournal).filter_by(plan_item_id=item_id).all()
        assert len(journals) == 1
        j = journals[0]
        assert j.operation == "rmdir_empty"
        before = json.loads(j.before_json)
        after = json.loads(j.after_json)
        assert before["path"] == str(dir_to_rm)
        assert before["scope_root"] == str(root)
        assert after["removed"] is True

    # Repeated reconciliation is idempotent
    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        journals = session.query(OperationJournal).filter_by(plan_item_id=item_id).all()
        assert len(journals) == 1


def test_reconcile_rmdir_empty_source_replaced_conflicts(recovery_test_env):
    service = recovery_test_env["service"]
    settings = recovery_test_env["settings"]
    root = recovery_test_env["root_path"]

    dir_to_rm = root / "replaced_dir"
    dir_to_rm.mkdir()
    st = dir_to_rm.stat()
    dir_to_rm.rmdir()
    dir_to_rm.write_text("now it is a file")

    with service.SessionLocal() as session:
        plan = BatchPlan(name="p1", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(dir_to_rm),
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(root),
                "execution": {
                    "source_stat": {
                        "device": st.st_dev,
                        "inode": st.st_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id
        plan_id = plan.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "failed"
        assert "conflict" in (item.reason or "")


def test_reconcile_mkdir_empty_before_mutation_returns_to_planned(recovery_test_env):
    service = recovery_test_env["service"]
    settings = recovery_test_env["settings"]
    root = recovery_test_env["root_path"]

    anchor = root / "anchor"
    anchor.mkdir()
    st_anchor = anchor.stat()

    target = anchor / "target_dir"

    with service.SessionLocal() as session:
        plan = BatchPlan(name="p1", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="mkdir_empty",
            source_path=str(anchor),
            target_path=str(target),
            expected_device=st_anchor.st_dev,
            expected_inode=st_anchor.st_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(anchor),
                "execution": {
                    "source_stat": {
                        "device": st_anchor.st_dev,
                        "inode": st_anchor.st_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id
        plan_id = plan.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "planned"
        assert item.reason is None
        journals = session.query(OperationJournal).filter_by(plan_item_id=item_id).all()
        assert len(journals) == 0


def test_reconcile_mkdir_empty_after_safe_target_creation_completes_and_adds_one_journal(recovery_test_env):
    service = recovery_test_env["service"]
    settings = recovery_test_env["settings"]
    root = recovery_test_env["root_path"]

    anchor = root / "anchor"
    anchor.mkdir()
    st_anchor = anchor.stat()

    target = anchor / "target_dir"
    target.mkdir()  # Created on disk before crash

    with service.SessionLocal() as session:
        plan = BatchPlan(name="p1", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="mkdir_empty",
            source_path=str(anchor),
            target_path=str(target),
            expected_device=st_anchor.st_dev,
            expected_inode=st_anchor.st_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(anchor),
                "execution": {
                    "source_stat": {
                        "device": st_anchor.st_dev,
                        "inode": st_anchor.st_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id
        plan_id = plan.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "completed"
        journals = session.query(OperationJournal).filter_by(plan_item_id=item_id).all()
        assert len(journals) == 1
        j = journals[0]
        assert j.operation == "mkdir_empty"
        after = json.loads(j.after_json)
        assert after["created"] is True
        assert after["object_type"] == "directory"

    # Repeated reconciliation is idempotent
    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        journals = session.query(OperationJournal).filter_by(plan_item_id=item_id).all()
        assert len(journals) == 1


def test_reconcile_mkdir_empty_unsafe_targets_conflict(recovery_test_env):
    service = recovery_test_env["service"]
    settings = recovery_test_env["settings"]
    root = recovery_test_env["root_path"]

    anchor = root / "anchor"
    anchor.mkdir()
    st_anchor = anchor.stat()

    target = anchor / "target_file"
    target.write_text("a file, not a directory")

    with service.SessionLocal() as session:
        plan = BatchPlan(name="p1", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="mkdir_empty",
            source_path=str(anchor),
            target_path=str(target),
            expected_device=st_anchor.st_dev,
            expected_inode=st_anchor.st_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(anchor),
                "execution": {
                    "source_stat": {
                        "device": st_anchor.st_dev,
                        "inode": st_anchor.st_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id
        plan_id = plan.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=plan_id,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "failed"
        assert "conflict" in (item.reason or "")
