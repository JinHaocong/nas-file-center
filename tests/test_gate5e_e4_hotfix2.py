import errno
import json
import os
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
