import errno
import json
import os
from pathlib import Path
import pytest

from app.models import IndexRoot, User, BatchPlan, BatchPlanItem, OperationJournal
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

