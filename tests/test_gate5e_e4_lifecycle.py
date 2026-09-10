import json
import os
import time
from pathlib import Path
import pytest

from app.models import IndexRoot, User, BatchPlan, BatchPlanItem
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password


@pytest.fixture
def lifecycle_env(tmp_path):
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
    )

    service = FileCenterService(settings)

    root_path = data_dir / "root1"
    root_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root_path))
        session.add(r)
        reg_user = User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        )
        session.add(reg_user)
        session.commit()

    return {
        "service": service,
        "settings": settings,
        "data_dir": data_dir,
        "root_path": root_path,
        "quarantine_dir": quarantine_dir,
    }


def test_freeze_rmdir_empty_captures_directory_identity(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]

    dir_to_remove = root / "empty_dir"
    dir_to_remove.mkdir()
    st = dir_to_remove.stat()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-freeze", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(dir_to_remove),
            expected_device=0,
            expected_inode=0,
            expected_size=0,
            expected_mtime_ns=0,
            state="planned",
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    frozen_plan = service.freeze_plan(plan_id)
    assert frozen_plan.status == "frozen"

    with service.SessionLocal() as session:
        frozen_item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert frozen_item.expected_device == st.st_dev
        assert frozen_item.expected_inode == st.st_ino
        assert frozen_item.expected_size == 0
        assert frozen_item.expected_mtime_ns == 0

        meta = json.loads(frozen_item.metadata_json)
        assert meta["snapshot"]["object_type"] == "directory"
        assert meta["snapshot"]["device"] == st.st_dev
        assert meta["snapshot"]["inode"] == st.st_ino


def test_freeze_rmdir_empty_rejects_non_directory(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]

    file_not_dir = root / "file.txt"
    file_not_dir.write_text("hello")

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-freeze-file", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(file_not_dir),
            expected_device=0,
            expected_inode=0,
            state="planned",
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    with pytest.raises(ValueError, match="not a directory|object_type"):
        service.freeze_plan(plan_id)


def test_freeze_rmdir_empty_rejects_symlink(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]

    target_dir = root / "real_dir"
    target_dir.mkdir()
    sym_dir = root / "sym_dir"
    os.symlink(str(target_dir), str(sym_dir))

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-freeze-symlink", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(sym_dir),
            expected_device=0,
            expected_inode=0,
            state="planned",
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    with pytest.raises(ValueError, match="symlink"):
        service.freeze_plan(plan_id)


def test_validate_rmdir_empty_success(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]

    empty_dir = root / "target_empty"
    empty_dir.mkdir()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-validate", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(empty_dir),
            state="planned",
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    service.freeze_plan(plan_id)
    val_res = service.validate_plan(plan_id)

    assert val_res["status"] == "ready"


def test_validate_rmdir_empty_mtime_change_stays_fresh(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]

    empty_dir = root / "target_empty_mtime"
    empty_dir.mkdir()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-mtime", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(empty_dir),
            state="planned",
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    service.freeze_plan(plan_id)

    # Change directory mtime by creating and removing a temporary file inside it
    temp_f = empty_dir / "temp.txt"
    temp_f.write_text("temp")
    temp_f.unlink()

    # Directory inode and dev are unchanged, only mtime changed
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "ready"


def test_validate_rmdir_empty_inode_change_becomes_stale(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]

    empty_dir = root / "target_recreated"
    empty_dir.mkdir()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-inode-change", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(empty_dir),
            state="planned",
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    service.freeze_plan(plan_id)

    # Recreate directory with guaranteed different inode
    old_ino = empty_dir.stat().st_ino
    empty_dir.rmdir()
    fillers = []
    while True:
        f = root / f"filler_{len(fillers)}"
        f.mkdir()
        fillers.append(f)
        empty_dir.mkdir()
        if empty_dir.stat().st_ino != old_ino:
            break
        empty_dir.rmdir()

    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "stale"


def test_validate_mkdir_empty_destination_contract(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]

    anchor = root / "anchor"
    anchor.mkdir()

    # Case 1: valid mkdir_empty (target strict descendant, not existing, parent exists)
    target = anchor / "a" / "b"
    (anchor / "a").mkdir()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-mkdir-valid", kind="batch-utility", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="mkdir_empty",
            source_path=str(anchor),
            target_path=str(target),
            state="planned",
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    service.freeze_plan(plan_id)
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "ready"

    # Case 2: target already exists -> skipped
    target.mkdir()
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "partial"
    target.rmdir()

    # Case 3: target parent missing -> skipped
    (anchor / "a").rmdir()
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "partial"
