import errno
import json
import os
from pathlib import Path
import pytest

from app.models import IndexRoot, User, BatchPlan, BatchPlanItem, OperationJournal, WorkJob, utcnow
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


def test_rmdir_empty_final_identity_check_then_empty_replacement_is_never_destroyed(
    lifecycle_env,
    monkeypatch,
):
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    victim = root / "victim"
    victim.mkdir()
    frozen = victim.stat()

    saved_x = root / "saved-x"
    replacement_inode = {}

    original_stat = os.stat
    triggered = False

    def racing_stat(path, *args, **kwargs):
        nonlocal triggered
        result = original_stat(path, *args, **kwargs)

        if (
            not triggered
            and kwargs.get("dir_fd") is not None
            and path == "victim"
            and kwargs.get("follow_symlinks") is False
        ):
            triggered = True
            victim.rename(saved_x)
            victim.mkdir()
            replacement_inode["value"] = original_stat(
                victim,
                follow_symlinks=False,
            ).st_ino

        return result

    monkeypatch.setattr(os, "stat", racing_stat)

    item = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=victim,
        expected_device=frozen.st_dev,
        expected_inode=frozen.st_ino,
    )

    result = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine,
        plan_id="hotfix2-red",
    )

    assert victim.exists()
    assert original_stat(victim, follow_symlinks=False).st_ino == replacement_inode["value"]
    assert result.state != "completed"


def test_rename_noreplace_at_directory_success(tmp_path):
    from app.fs_ops import rename_noreplace_at

    src_dir = tmp_path / "src_dir"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst_dir"
    dst_dir.mkdir()

    sub = src_dir / "my_sub"
    sub.mkdir()
    (sub / "file.txt").write_text("hello")
    orig_inode = sub.stat().st_ino

    src_fd = os.open(str(src_dir), os.O_RDONLY | os.O_DIRECTORY)
    dst_fd = os.open(str(dst_dir), os.O_RDONLY | os.O_DIRECTORY)
    try:
        rename_noreplace_at(src_fd, "my_sub", dst_fd, "renamed_sub")
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert not (src_dir / "my_sub").exists()
    assert (dst_dir / "renamed_sub").is_dir()
    assert (dst_dir / "renamed_sub" / "file.txt").read_text() == "hello"
    assert (dst_dir / "renamed_sub").stat().st_ino == orig_inode


def test_rename_noreplace_at_target_collision_leaves_both_untouched(tmp_path):
    from app.fs_ops import rename_noreplace_at

    src_dir = tmp_path / "src_coll"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst_coll"
    dst_dir.mkdir()

    s = src_dir / "item"
    s.mkdir()
    (s / "s.txt").write_text("source")

    d = dst_dir / "item"
    d.mkdir()
    (d / "d.txt").write_text("dest")

    src_fd = os.open(str(src_dir), os.O_RDONLY | os.O_DIRECTORY)
    dst_fd = os.open(str(dst_dir), os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            rename_noreplace_at(src_fd, "item", dst_fd, "item")
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert (src_dir / "item" / "s.txt").read_text() == "source"
    assert (dst_dir / "item" / "d.txt").read_text() == "dest"


def test_rename_noreplace_at_exdev_raises_no_fallback(tmp_path, monkeypatch):
    import ctypes
    import app.fs_ops as fs_ops_mod
    from app.fs_ops import rename_noreplace_at

    src_dir = tmp_path / "src_exdev"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst_exdev"
    dst_dir.mkdir()

    s = src_dir / "sub"
    s.mkdir()

    src_fd = os.open(str(src_dir), os.O_RDONLY | os.O_DIRECTORY)
    dst_fd = os.open(str(dst_dir), os.O_RDONLY | os.O_DIRECTORY)

    def mock_exdev(sfd, src, dfd, dst):
        ctypes.set_errno(errno.EXDEV)
        return -1

    monkeypatch.setattr(fs_ops_mod, "_RENAME_AT_IMPL", mock_exdev)

    def forbidden_rename(*args, **kwargs):
        raise AssertionError("FORBIDDEN: os.rename fallback")
    monkeypatch.setattr(os, "rename", forbidden_rename)

    try:
        with pytest.raises(OSError) as exc_info:
            rename_noreplace_at(src_fd, "sub", dst_fd, "sub_moved")
        assert exc_info.value.errno == errno.EXDEV
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert s.exists()
    assert not (dst_dir / "sub_moved").exists()


def test_legacy_rename_noreplace_unchanged(tmp_path):
    from app.fs_ops import rename_noreplace

    f1 = tmp_path / "f1.txt"
    f1.write_text("data")
    f2 = tmp_path / "f2.txt"

    rename_noreplace(f1, f2)
    assert not f1.exists()
    assert f2.read_text() == "data"

    f3 = tmp_path / "f3.txt"
    f3.write_text("another")
    with pytest.raises(FileExistsError):
        rename_noreplace(f3, f2)
    assert f3.exists()
    assert f2.read_text() == "data"


def test_build_e4_quarantine_name():
    from app.batch_utilities.empty_dir_quarantine import build_e4_quarantine_name
    name = build_e4_quarantine_name("p123", 42, Path("/data/root1/a/b"))
    assert name.startswith(".nfc-e4-pp123-s42-")
    assert len(name) == len(".nfc-e4-pp123-s42-") + 16


def test_relocate_empty_dir_success_outcome_a(tmp_path, monkeypatch):
    import shutil
    from app.batch_utilities.empty_dir_quarantine import relocate_empty_dir_to_quarantine

    root = tmp_path / "root"
    root.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    d = root / "empty_dir"
    d.mkdir()
    st = d.stat()

    for fn in ("rmdir", "unlink"):
        def forbidden(*args, **kwargs):
            raise AssertionError(f"FORBIDDEN: os.{fn} called")
        monkeypatch.setattr(os, fn, forbidden)
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: pytest.fail("FORBIDDEN: rmtree"))

    res = relocate_empty_dir_to_quarantine(
        d,
        allowed_roots=[root],
        quarantine_root=q_dir,
        plan_id="planA",
        sequence=1,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    assert res.state == "completed"
    assert not d.exists()
    assert res.quarantine_path.exists()
    assert res.quarantine_path.is_dir()
    assert res.quarantine_path.stat().st_ino == st.st_ino


def test_relocate_empty_dir_post_move_mismatch_rollbacks_safely(tmp_path, monkeypatch):
    import app.batch_utilities.empty_dir_quarantine as eq_mod
    from app.batch_utilities.empty_dir_quarantine import relocate_empty_dir_to_quarantine

    root = tmp_path / "root"
    root.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    d = root / "race_dir"
    d.mkdir()
    st_orig = d.stat()

    # Pre-check passes with st_orig, but between pre-check and fstat(moved_fd),
    # fstat returns a different inode to simulate race
    orig_fstat = os.fstat
    fstat_calls = [0]

    def racing_fstat(fd):
        res = orig_fstat(fd)
        fstat_calls[0] += 1
        # Mock st_ino on moved object
        class FakeStat:
            st_dev = res.st_dev
            st_ino = res.st_ino + 9999
            st_mode = res.st_mode
        return FakeStat()

    monkeypatch.setattr(os, "fstat", racing_fstat)

    res = relocate_empty_dir_to_quarantine(
        d,
        allowed_roots=[root],
        quarantine_root=q_dir,
        plan_id="planB",
        sequence=1,
        expected_device=st_orig.st_dev,
        expected_inode=st_orig.st_ino,
    )

    assert res.state == "failed"
    assert "conflict detected, safely rolled back" in res.reason
    assert d.exists(), "Rolled back object must be restored to original path"
    assert res.quarantine_path is None


def test_relocate_empty_dir_rollback_collision_preserves_in_quarantine(tmp_path, monkeypatch):
    import app.batch_utilities.empty_dir_quarantine as eq_mod
    from app.batch_utilities.empty_dir_quarantine import relocate_empty_dir_to_quarantine

    root = tmp_path / "root"
    root.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    d = root / "coll_dir"
    d.mkdir()
    st_orig = d.stat()

    # Trigger mismatch on fstat
    orig_fstat = os.fstat
    def fake_fstat(fd):
        res = orig_fstat(fd)
        class FakeStat:
            st_dev = res.st_dev
            st_ino = res.st_ino + 8888
            st_mode = res.st_mode
        return FakeStat()
    monkeypatch.setattr(os, "fstat", fake_fstat)

    # Make rollback fail with FileExistsError
    orig_rename_at = eq_mod.rename_noreplace_at
    call_count = [0]
    def mock_rename_at(sfd, sname, dfd, dname):
        call_count[0] += 1
        if call_count[0] == 1:
            return orig_rename_at(sfd, sname, dfd, dname)
        raise FileExistsError(errno.EEXIST, "Original location occupied")
    monkeypatch.setattr(eq_mod, "rename_noreplace_at", mock_rename_at)

    res = relocate_empty_dir_to_quarantine(
        d,
        allowed_roots=[root],
        quarantine_root=q_dir,
        plan_id="planC",
        sequence=1,
        expected_device=st_orig.st_dev,
        expected_inode=st_orig.st_ino,
    )

    assert res.state == "failed"
    assert "preserved in quarantine" in res.reason
    assert res.quarantine_path is not None
    assert res.quarantine_path.exists(), "Object must remain preserved in quarantine!"


def test_relocate_empty_dir_non_empty_after_move_rollbacks(tmp_path, monkeypatch):
    from app.batch_utilities.empty_dir_quarantine import relocate_empty_dir_to_quarantine

    root = tmp_path / "root"
    root.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    d = root / "non_empty_dir"
    d.mkdir()
    st_orig = d.stat()

    # Simulate child appearing after move (os.listdir returns a child)
    monkeypatch.setattr(os, "listdir", lambda fd: ["ghost_file.txt"])

    res = relocate_empty_dir_to_quarantine(
        d,
        allowed_roots=[root],
        quarantine_root=q_dir,
        plan_id="planD",
        sequence=1,
        expected_device=st_orig.st_dev,
        expected_inode=st_orig.st_ino,
    )

    assert res.state == "failed"
    assert "conflict detected, safely rolled back" in res.reason
    assert d.exists(), "Object must be rolled back"


def test_relocate_empty_dir_target_collision_fails_safely(tmp_path):
    from app.batch_utilities.empty_dir_quarantine import relocate_empty_dir_to_quarantine, build_e4_quarantine_name

    root = tmp_path / "root"
    root.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    d = root / "exist_target"
    d.mkdir()
    st_orig = d.stat()

    # Pre-create the deterministic target in quarantine
    q_name = build_e4_quarantine_name("planE", 1, d)
    (q_dir / q_name).mkdir()

    res = relocate_empty_dir_to_quarantine(
        d,
        allowed_roots=[root],
        quarantine_root=q_dir,
        plan_id="planE",
        sequence=1,
        expected_device=st_orig.st_dev,
        expected_inode=st_orig.st_ino,
    )

    assert res.state == "failed"
    assert "already exists" in res.reason
    assert d.exists(), "Source must be untouched"


def test_execute_rmdir_empty_zero_rmdir_unlink_rmtree(lifecycle_env, monkeypatch):
    import shutil
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    victim = root / "zero_destruct_dir"
    victim.mkdir()
    st = victim.stat()

    for fn in ("rmdir", "unlink"):
        def forbidden(*args, **kwargs):
            raise AssertionError(f"FORBIDDEN: os.{fn} called")
        monkeypatch.setattr(os, fn, forbidden)
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: pytest.fail("FORBIDDEN: shutil.rmtree called"))

    item = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=victim,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    res = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine,
        plan_id="p_zero",
    )

    assert res.state == "completed"
    assert not victim.exists()
    assert res.result_path.exists()
    assert res.result_path.is_dir()
    assert res.result_path.stat().st_ino == st.st_ino


def test_execute_restore_empty_dir_success_exact_inode(lifecycle_env):
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    # 1. First logically remove an empty dir
    d = root / "to_restore"
    d.mkdir()
    st = d.stat()

    item_rm = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=d,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )
    res_rm = execute_item(
        item_rm,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine,
        plan_id="p_rest",
    )
    assert res_rm.state == "completed"
    q_path = res_rm.result_path
    assert q_path.exists()
    assert not d.exists()

    # 2. Now execute restore_empty_dir
    st_q = q_path.stat()
    item_restore = OperationItem(
        sequence=2,
        operation="restore_empty_dir",
        source=q_path,
        target=d,
        expected_device=st_q.st_dev,
        expected_inode=st_q.st_ino,
    )
    res_restore = execute_item(
        item_restore,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,  # Prove ALLOW_DELETE is NOT required
        quarantine_root=quarantine,
        plan_id="p_rest",
    )

    assert res_restore.state == "completed"
    assert d.exists()
    assert not q_path.exists()
    assert d.stat().st_ino == st.st_ino, "Exact inode must be preserved across restore!"


def test_execute_restore_empty_dir_target_occupied_fails_safely(lifecycle_env):
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    d = root / "occupied_target"
    d.mkdir()
    st = d.stat()

    item_rm = OperationItem(
        sequence=1,
        operation="rmdir_empty",
        source=d,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )
    res_rm = execute_item(
        item_rm,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine,
        plan_id="p_occ",
    )
    assert res_rm.state == "completed"
    q_path = res_rm.result_path

    # External actor occupies the original location
    d.mkdir()
    (d / "new_file.txt").write_text("blocker")

    item_restore = OperationItem(
        sequence=2,
        operation="restore_empty_dir",
        source=q_path,
        target=d,
    )
    res_restore = execute_item(
        item_restore,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=quarantine,
        plan_id="p_occ",
    )

    assert res_restore.state == "skipped"
    assert q_path.exists(), "Quarantined directory must remain preserved!"
    assert (d / "new_file.txt").exists(), "Occupying target must not be overwritten!"


def test_freeze_restore_empty_dir_captures_identity(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    # Prepare a directory in quarantine
    q_dir = quarantine / ".nfc-e4-p99-s1-testdummy"
    q_dir.mkdir()
    st = q_dir.stat()

    target_dir = root / "restored_dir"

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-freeze-restore", kind="undo", status="draft")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore_empty_dir",
            source_path=str(q_dir),
            target_path=str(target_dir),
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


def test_freeze_restore_empty_dir_rejects_non_quarantine_or_non_dir(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    # 1. Source not in quarantine
    outside_dir = root / "outside_dir"
    outside_dir.mkdir()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-freeze-outside", kind="undo", status="draft")
        session.add(plan)
        session.flush()
        session.add(BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore_empty_dir",
            source_path=str(outside_dir),
            target_path=str(root / "tgt"),
            state="planned",
        ))
        session.commit()
        p1_id = plan.id

    with pytest.raises(ValueError, match="quarantine storage"):
        service.freeze_plan(p1_id)

    # 2. Source in quarantine is a file, not a directory
    q_file = quarantine / ".nfc-e4-p99-s2-file"
    q_file.write_text("not a dir")

    with service.SessionLocal() as session:
        plan2 = BatchPlan(name="test-freeze-file", kind="undo", status="draft")
        session.add(plan2)
        session.flush()
        session.add(BatchPlanItem(
            plan_id=plan2.id,
            sequence=1,
            operation="restore_empty_dir",
            source_path=str(q_file),
            target_path=str(root / "tgt"),
            state="planned",
        ))
        session.commit()
        p2_id = plan2.id

    with pytest.raises(ValueError, match="not a directory"):
        service.freeze_plan(p2_id)


def test_validate_restore_empty_dir_success_and_chaining(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    # Nested restoration: parent 'p' restored first, then child 'p/c'
    q_parent = quarantine / ".nfc-e4-p10-s1-parent"
    q_child = quarantine / ".nfc-e4-p10-s2-child"
    q_parent.mkdir()
    q_child.mkdir()

    target_parent = root / "p_restored"
    target_child = target_parent / "c_restored"

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-validate-nested", kind="undo", status="draft")
        session.add(plan)
        session.flush()

        session.add(BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore_empty_dir",
            source_path=str(q_parent),
            target_path=str(target_parent),
            state="planned",
        ))
        session.add(BatchPlanItem(
            plan_id=plan.id,
            sequence=2,
            operation="restore_empty_dir",
            source_path=str(q_child),
            target_path=str(target_child),
            state="planned",
        ))
        session.commit()
        plan_id = plan.id

    service.freeze_plan(plan_id)
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "ready"


def test_validate_restore_empty_dir_stale_on_identity_mismatch(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    q_dir = quarantine / ".nfc-e4-p11-s1-stale"
    q_dir.mkdir()
    target_dir = root / "stale_tgt"

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-validate-stale", kind="undo", status="draft")
        session.add(plan)
        session.flush()
        session.add(BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore_empty_dir",
            source_path=str(q_dir),
            target_path=str(target_dir),
            state="planned",
        ))
        session.commit()
        plan_id = plan.id

    service.freeze_plan(plan_id)

    # Now replace q_dir with guaranteed different inode
    old_ino = q_dir.stat().st_ino
    q_dir.rmdir()
    fillers = []
    while True:
        f = quarantine / f"filler_{len(fillers)}"
        f.mkdir()
        fillers.append(f)
        q_dir.mkdir()
        if q_dir.stat().st_ino != old_ino:
            break
        q_dir.rmdir()

    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "stale"


def test_create_undo_plan_produces_restore_empty_dir(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    scope = root / "undo_scope"
    d_a = scope / "a"
    d_b = d_a / "b"
    d_b.mkdir(parents=True)

    # Simulate completed plan with two rmdir_empty operations
    # b removed first (seq 1), a removed second (seq 2)
    q_b = quarantine / ".nfc-e4-p20-s1-b"
    q_a = quarantine / ".nfc-e4-p20-s2-a"
    d_b.rename(q_b)
    d_a.rename(q_a)

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-undo-rmdir", kind="batch-utility", status="completed")
        session.add(plan)
        session.flush()

        j1 = OperationJournal(
            operation="rmdir_empty",
            sequence=1,
            plan_id=plan.id,
            plan_item_id=None,
            task_id=None,
            before_json=json.dumps({"path": str(d_b), "scope_root": str(scope)}),
            after_json=json.dumps({"logical_removed": True, "preserved": True, "quarantine_path": str(q_b)}),
        )
        j2 = OperationJournal(
            operation="rmdir_empty",
            sequence=2,
            plan_id=plan.id,
            plan_item_id=None,
            task_id=None,
            before_json=json.dumps({"path": str(d_a), "scope_root": str(scope)}),
            after_json=json.dumps({"logical_removed": True, "preserved": True, "quarantine_path": str(q_a)}),
        )
        session.add(j1)
        session.add(j2)
        session.commit()
        plan_id = plan.id

    undo_res = service.create_undo_plan(plan_id)
    undo_id = undo_res["id"]

    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=undo_id).order_by(BatchPlanItem.sequence).all()
        assert len(items) == 2

        # Reversal must produce shallowest-first: 'a' restored before 'a/b'
        assert items[0].sequence == 1
        assert items[0].operation == "restore_empty_dir"
        assert items[0].source_path == str(q_a)
        assert items[0].target_path == str(d_a)
        assert items[0].expected_device == 0
        assert items[0].expected_inode == 0

        assert items[1].sequence == 2
        assert items[1].operation == "restore_empty_dir"
        assert items[1].source_path == str(q_b)
        assert items[1].target_path == str(d_b)


def test_undo_restore_empty_dir_inverts_to_rmdir_empty(lifecycle_env):
    service = lifecycle_env["service"]
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    d = root / "restored_dir"

    with service.SessionLocal() as session:
        plan = BatchPlan(name="test-undo-restore", kind="undo", status="completed")
        session.add(plan)
        session.flush()

        j = OperationJournal(
            operation="restore_empty_dir",
            sequence=1,
            plan_id=plan.id,
            plan_item_id=None,
            task_id=None,
            before_json=json.dumps({"quarantine_path": str(quarantine / "dummy"), "target_path": str(d), "scope_root": str(root)}),
            after_json=json.dumps({"path": str(d), "restored": True, "object_type": "directory"}),
        )
        session.add(j)
        session.commit()
        plan_id = plan.id

    undo_res = service.create_undo_plan(plan_id)
    undo_id = undo_res["id"]

    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=undo_id).order_by(BatchPlanItem.sequence).all()
        assert len(items) == 1
        assert items[0].operation == "rmdir_empty"
        assert items[0].source_path == str(d)


def test_reconcile_rmdir_empty_state_a_returns_to_planned(lifecycle_env):
    """
    State A (§15.1):
    source exists as Frozen X, quarantine target absent -> return to planned, reason=None
    """
    from app.tasks.handlers import _reconcile_executing_item
    service = lifecycle_env["service"]
    settings = service.settings
    root = lifecycle_env["root_path"]

    d = root / "state_a_dir"
    d.mkdir()
    st = d.stat()

    with service.SessionLocal() as session:
        plan = BatchPlan(name="p_state_a", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(d),
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


def test_reconcile_rmdir_empty_state_b_relocated_completes_with_quarantine_journal(lifecycle_env):
    """
    State B (§15.1):
    source absent, quarantine target exists as Frozen X
    -> mark completed, create missing success journal with quarantine_path exactly once.
    """
    from app.tasks.handlers import _reconcile_executing_item
    from app.batch_utilities.empty_dir_quarantine import build_e4_quarantine_name
    service = lifecycle_env["service"]
    settings = service.settings
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    d = root / "state_b_dir"
    d.mkdir()
    st = d.stat()

    # Emulate crash right after atomic relocation to quarantine target
    plan_id = 901
    seq = 1
    q_name = build_e4_quarantine_name(plan_id, seq, str(d))
    q_target = quarantine / q_name
    d.rename(q_target)

    with service.SessionLocal() as session:
        plan = BatchPlan(id=plan_id, name="p_state_b", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=seq,
            operation="rmdir_empty",
            source_path=str(d),
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
        after = json.loads(j.after_json)
        assert after["quarantine_path"] == str(q_target)
        assert after["logical_removed"] is True
        assert after["preserved"] is True


def test_reconcile_rmdir_empty_state_c_quarantine_identity_mismatch_fails_safely(lifecycle_env):
    """
    State C (§15.1):
    quarantine target exists but identity != Frozen X
    -> mark failed/conflict, do not destroy target, attempt safe rollback if possible.
    """
    from app.tasks.handlers import _reconcile_executing_item
    from app.batch_utilities.empty_dir_quarantine import build_e4_quarantine_name
    service = lifecycle_env["service"]
    settings = service.settings
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    d = root / "state_c_dir"
    # Expected identity was from a previous object
    exp_dev = 1
    exp_ino = 9999999

    plan_id = 902
    seq = 1
    q_name = build_e4_quarantine_name(plan_id, seq, str(d))
    q_target = quarantine / q_name
    q_target.mkdir()  # Created with different inode

    with service.SessionLocal() as session:
        plan = BatchPlan(id=plan_id, name="p_state_c", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=seq,
            operation="rmdir_empty",
            source_path=str(d),
            expected_device=exp_dev,
            expected_inode=exp_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(root),
                "execution": {
                    "source_stat": {
                        "device": exp_dev,
                        "inode": exp_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id

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
        # Object in quarantine or rolled back to d must not be destroyed!
        assert q_target.exists() or d.exists()


def test_reconcile_rmdir_empty_state_d_both_source_and_quarantine_exist_conflicts(lifecycle_env):
    """
    State D (§15.1):
    source Frozen X exists AND quarantine target exists -> conflict, preserve both!
    """
    from app.tasks.handlers import _reconcile_executing_item
    from app.batch_utilities.empty_dir_quarantine import build_e4_quarantine_name
    service = lifecycle_env["service"]
    settings = service.settings
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    d = root / "state_d_dir"
    d.mkdir()
    st = d.stat()

    plan_id = 903
    seq = 1
    q_name = build_e4_quarantine_name(plan_id, seq, str(d))
    q_target = quarantine / q_name
    q_target.mkdir()

    with service.SessionLocal() as session:
        plan = BatchPlan(id=plan_id, name="p_state_d", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=seq,
            operation="rmdir_empty",
            source_path=str(d),
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
        assert d.exists()
        assert q_target.exists()


def test_reconcile_rmdir_empty_state_e_both_absent_fails_closed(lifecycle_env):
    """
    State E (§15.1):
    source absent AND quarantine target absent -> fail closed
    """
    from app.tasks.handlers import _reconcile_executing_item
    service = lifecycle_env["service"]
    settings = service.settings
    root = lifecycle_env["root_path"]

    d = root / "state_e_dir"
    exp_dev = 1
    exp_ino = 8888888

    with service.SessionLocal() as session:
        plan = BatchPlan(id=904, name="p_state_e", kind="batch-utility", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(d),
            expected_device=exp_dev,
            expected_inode=exp_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(root),
                "execution": {
                    "source_stat": {
                        "device": exp_dev,
                        "inode": exp_ino,
                        "object_type": "directory",
                    }
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session=session,
            item=item,
            plan_id=904,
            job_id=1,
            user_id=1,
            settings=settings,
            now=utcnow(),
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "failed"
        assert "absent" in (item.reason or "")


def test_reconcile_restore_empty_dir_states(lifecycle_env):
    """
    Restore empty dir crash states (§15.2):
    - restore source in quarantine, target absent -> planned
    - quarantine absent, target exists with Frozen identity -> completed + journal
    - target exists with wrong identity -> failed/conflict
    """
    from app.tasks.handlers import _reconcile_executing_item
    service = lifecycle_env["service"]
    settings = service.settings
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    # 1. Unfinished restore: source in quarantine, target absent -> planned
    q_src1 = quarantine / ".nfc-e4-p905-s1-test"
    q_src1.mkdir()
    st1 = q_src1.stat()
    tgt1 = root / "restored_1"

    with service.SessionLocal() as session:
        plan = BatchPlan(id=905, name="p_rest_crash", kind="undo", status="running")
        session.add(plan)
        session.flush()

        item1 = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore_empty_dir",
            source_path=str(q_src1),
            target_path=str(tgt1),
            expected_device=st1.st_dev,
            expected_inode=st1.st_ino,
            state="executing",
            metadata_json=json.dumps({"scope_root": str(root)}),
        )
        session.add(item1)
        session.commit()
        i1_id = item1.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, i1_id)
        _reconcile_executing_item(session, item, 905, 1, 1, settings, utcnow())
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, i1_id)
        assert item.state == "planned"
        assert item.reason is None

    # 2. Completed restore: quarantine absent, target exists with Frozen identity -> completed + journal
    q_src2 = quarantine / ".nfc-e4-p905-s2-test"
    tgt2 = root / "restored_2"
    tgt2.mkdir()
    st2 = tgt2.stat()

    with service.SessionLocal() as session:
        item2 = BatchPlanItem(
            plan_id=905,
            sequence=2,
            operation="restore_empty_dir",
            source_path=str(q_src2),
            target_path=str(tgt2),
            expected_device=st2.st_dev,
            expected_inode=st2.st_ino,
            state="executing",
            metadata_json=json.dumps({"scope_root": str(root)}),
        )
        session.add(item2)
        session.commit()
        i2_id = item2.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, i2_id)
        _reconcile_executing_item(session, item, 905, 1, 1, settings, utcnow())
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, i2_id)
        assert item.state == "completed"
        journals = session.query(OperationJournal).filter_by(plan_item_id=i2_id).all()
        assert len(journals) == 1
        j = journals[0]
        assert j.operation == "restore_empty_dir"
        after = json.loads(j.after_json)
        assert after["restored"] is True


def test_quarantine_root_symlink_is_rejected_before_relocation(tmp_path):
    from app.batch_utilities.empty_dir_quarantine import relocate_empty_dir_to_quarantine

    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    source = allowed_root / "empty_dir"
    source.mkdir()
    st_src = source.stat()

    real_q = tmp_path / "real_quarantine"
    real_q.mkdir()
    q_alias = tmp_path / "quarantine_alias"
    q_alias.symlink_to(real_q, target_is_directory=True)

    res = relocate_empty_dir_to_quarantine(
        source,
        allowed_roots=[allowed_root],
        quarantine_root=q_alias,
        plan_id="p-test",
        sequence=1,
        expected_device=st_src.st_dev,
        expected_inode=st_src.st_ino,
    )

    # Expected:
    # state != completed
    # source remains at original path
    # nothing appears in real_q
    # no rename_noreplace_at mutation occurred
    assert res.state != "completed"
    assert res.state == "failed"
    assert source.exists()
    assert list(real_q.iterdir()) == []


def test_reconcile_state_c_parent_symlink_hijack_preserves_quarantine(lifecycle_env, tmp_path):
    from app.tasks.handlers import _reconcile_executing_item
    from app.batch_utilities.empty_dir_quarantine import build_e4_quarantine_name

    service = lifecycle_env["service"]
    settings = lifecycle_env["settings"]
    root = lifecycle_env["root_path"]
    quarantine = lifecycle_env["quarantine_dir"]

    # Construct: authorized root / parent / victim
    parent = root / "parent"
    parent.mkdir()
    victim = parent / "victim"
    src = victim

    # Frozen X identity (dev, ino) recorded in plan item
    exp_dev = 12345
    exp_ino = 99999

    # Quarantine deterministic target contains mismatched inode Y
    q_name = build_e4_quarantine_name(999, 1, str(src))
    q_target = quarantine / q_name
    q_target.mkdir()
    st_y = q_target.stat()
    assert (st_y.st_dev, st_y.st_ino) != (exp_dev, exp_ino)

    # Destination directory to attempt hijacking into
    hijack_dest = tmp_path / "hijack_target"
    hijack_dest.mkdir()

    # Replace the original parent path with a symlink to hijack_dest
    parent.rmdir()
    parent.symlink_to(hijack_dest, target_is_directory=True)

    with service.SessionLocal() as session:
        plan = BatchPlan(id=999, name="p_crash_c", kind="execute", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rmdir_empty",
            source_path=str(src),
            target_path=None,
            expected_device=exp_dev,
            expected_inode=exp_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(root),
                "execution": {
                    "source_stat": {"device": exp_dev, "inode": exp_ino}
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(session, item, 999, 1, 1, settings, utcnow())
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        # Expected:
        # Y MUST remain in quarantine
        # no object appears under symlink destination / victim
        # item = failed/conflict
        # reconciliation must not follow the replaced parent symlink
        assert item.state == "failed"
        assert "conflict" in item.reason
        assert q_target.exists()
        assert q_target.is_dir()
        assert list(hijack_dest.iterdir()) == []
        assert not (hijack_dest / "victim").exists()


def test_reconcile_rmdir_empty_quarantine_root_symlink_fails_closed(lifecycle_env, tmp_path):
    from app.tasks.handlers import _reconcile_executing_item
    from app.batch_utilities.empty_dir_quarantine import build_e4_quarantine_name

    service = lifecycle_env["service"]
    settings = lifecycle_env["settings"]
    root = lifecycle_env["root_path"]

    # Setup:
    # real quarantine dir
    real_q = tmp_path / "real_quarantine"
    real_q.mkdir()

    # symlink alias -> real quarantine dir
    q_alias = tmp_path / "quarantine_alias"
    q_alias.symlink_to(real_q, target_is_directory=True)

    # Point settings.quarantine_root to the symlink alias
    settings.quarantine_root = q_alias

    # source is absent
    src = root / "missing_source"
    assert not src.exists()

    plan_id = 990
    seq = 1
    q_name = build_e4_quarantine_name(plan_id, seq, str(src))

    # real quarantine target contains deterministic q_name whose dev/inode == Frozen X
    q_target_real = real_q / q_name
    q_target_real.mkdir()
    st_q = q_target_real.stat()
    exp_dev = st_q.st_dev
    exp_ino = st_q.st_ino

    # item.operation = rmdir_empty, item.state = executing
    with service.SessionLocal() as session:
        plan = BatchPlan(id=plan_id, name="p_q_symlink_crash", kind="execute", status="running")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=seq,
            operation="rmdir_empty",
            source_path=str(src),
            target_path=None,
            expected_device=exp_dev,
            expected_inode=exp_ino,
            state="executing",
            metadata_json=json.dumps({
                "scope_root": str(root),
                "execution": {
                    "source_stat": {"device": exp_dev, "inode": exp_ino}
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(session, item, plan_id, 1, 1, settings, utcnow())
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        journals = session.query(OperationJournal).filter_by(plan_item_id=item_id).all()
        # Expected:
        # item MUST NOT become completed
        # NO success OperationJournal
        # NO rollback through invalid quarantine root
        # object remains untouched
        # item = failed/conflict
        assert item.state != "completed"
        assert item.state == "failed"
        assert "conflict" in (item.reason or "") or "invalid" in (item.reason or "")
        assert len(journals) == 0
        assert q_target_real.exists()
        assert not src.exists()





