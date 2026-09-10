import json
import os
import time
from pathlib import Path
import pytest

from app.models import IndexRoot, User, BatchPlan, BatchPlanItem
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password
from app.batch.plans import OperationItem
from app.execution.executor import execute_item


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


def test_execute_rmdir_empty_permission_gates(lifecycle_env):
    root = lifecycle_env["root_path"]
    quarantine_dir = lifecycle_env["quarantine_dir"]

    target_dir = root / "perm_dir"
    target_dir.mkdir()

    item = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=target_dir,
    )

    # Gate 1: allow_mutation=False -> skip
    res1 = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=False,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res1.state == "skipped"
    assert "mutation is disabled" in res1.reason
    assert target_dir.is_dir()

    # Gate 2: allow_delete=False -> skip
    res2 = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res2.state == "skipped"
    assert "permanent deletion is disabled" in res2.reason
    assert target_dir.is_dir()


def test_execute_rmdir_empty_success_removes_dir(lifecycle_env):
    root = lifecycle_env["root_path"]
    quarantine_dir = lifecycle_env["quarantine_dir"]

    target_dir = root / "success_rmdir"
    target_dir.mkdir()
    st = target_dir.stat()

    item = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=target_dir,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    res = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res.state == "completed"
    assert "empty directory removed" in res.reason
    assert not target_dir.exists()


def test_execute_rmdir_empty_no_unlink_or_rmtree(lifecycle_env, monkeypatch):
    import shutil
    root = lifecycle_env["root_path"]
    quarantine_dir = lifecycle_env["quarantine_dir"]

    target_dir = root / "safe_rmdir"
    target_dir.mkdir()

    item = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=target_dir,
    )

    def forbidden_unlink(*args, **kwargs):
        raise AssertionError("FORBIDDEN: os.unlink called during rmdir_empty")

    def forbidden_rmtree(*args, **kwargs):
        raise AssertionError("FORBIDDEN: shutil.rmtree called during rmdir_empty")

    monkeypatch.setattr(os, "unlink", forbidden_unlink)
    monkeypatch.setattr(shutil, "rmtree", forbidden_rmtree)

    res = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res.state == "completed"
    assert not target_dir.exists()


def test_execute_rmdir_empty_not_empty_fails(lifecycle_env):
    root = lifecycle_env["root_path"]
    quarantine_dir = lifecycle_env["quarantine_dir"]

    target_dir = root / "not_empty_dir"
    target_dir.mkdir()
    (target_dir / "blocker.txt").write_text("blocked")

    item = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=target_dir,
    )

    res = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res.state == "failed"
    assert target_dir.exists()
    assert (target_dir / "blocker.txt").exists()


def test_execute_rmdir_empty_symlink_or_inode_mismatch_skips(lifecycle_env):
    root = lifecycle_env["root_path"]
    quarantine_dir = lifecycle_env["quarantine_dir"]

    # Symlink source
    real_d = root / "real_dir"
    real_d.mkdir()
    sym_d = root / "sym_dir"
    os.symlink(str(real_d), str(sym_d))

    item_sym = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=sym_d,
    )
    res_sym = execute_item(
        item_sym,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res_sym.state == "skipped"

    # Inode mismatch
    target_d = root / "inode_dir"
    target_d.mkdir()
    st = target_d.stat()

    item_ino = OperationItem(
        sequence=2,
        operation="rmdir_empty",
        source=target_d,
        expected_device=st.st_dev,
        expected_inode=st.st_ino + 999999,
    )
    res_ino = execute_item(
        item_ino,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res_ino.state == "skipped"
    assert target_d.exists()


def test_execute_mkdir_empty_success_and_fences(lifecycle_env, monkeypatch):
    root = lifecycle_env["root_path"]
    quarantine_dir = lifecycle_env["quarantine_dir"]

    anchor = root / "anchor"
    anchor.mkdir()
    st_anchor = anchor.stat()

    target = anchor / "sub_new"

    item = OperationItem(
        sequence=1,
        operation="mkdir_empty",
        source=anchor,
        target=target,
        expected_device=st_anchor.st_dev,
        expected_inode=st_anchor.st_ino,
    )

    # 1. Mutation disabled -> skip
    res_dis = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=False,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res_dis.state == "skipped"
    assert not target.exists()

    # 2. Verify single-level mkdir only (no makedirs)
    def forbidden_makedirs(*args, **kwargs):
        raise AssertionError("FORBIDDEN: os.makedirs called during mkdir_empty")
    monkeypatch.setattr(os, "makedirs", forbidden_makedirs)

    # 3. Successful execution
    res = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res.state == "completed"
    assert "empty directory created" in res.reason
    assert target.is_dir()

    # 4. Target already exists -> skip
    res_exists = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_dir,
        plan_id="p1",
    )
    assert res_exists.state == "skipped"

