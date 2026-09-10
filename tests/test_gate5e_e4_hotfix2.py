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
