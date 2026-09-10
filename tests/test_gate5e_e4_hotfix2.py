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
