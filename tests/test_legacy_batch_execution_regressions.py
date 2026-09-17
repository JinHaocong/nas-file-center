from __future__ import annotations

import ctypes
import errno
from pathlib import Path

import pytest

from app.config import Settings
from app.models import BatchPlan
from app.service import FileCenterService


def _make_service(tmp_path: Path) -> tuple[FileCenterService, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir = data_dir / ".nas-file-center-trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config_dir,
        database_path=config_dir / "app.db",
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=trash_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    return FileCenterService(settings), data_dir


def _force_native_noreplace_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.fs_ops as fs_ops

    def unsupported_noreplace(_source: bytes, _target: bytes) -> int:
        ctypes.set_errno(errno.EOPNOTSUPP)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_IMPL", unsupported_noreplace)


@pytest.mark.parametrize("status", ["stale", "expired"])
def test_delete_plan_allows_inactive_stale_or_expired_plan(tmp_path: Path, status: str) -> None:
    service, data_dir = _make_service(tmp_path)
    source = data_dir / "source.txt"
    source.write_text("payload", encoding="utf-8")

    plan = service.create_plan(
        name=f"{status} plan",
        kind="organize",
        items=[
            {
                "operation": "rename",
                "source": str(source),
                "target": str(data_dir / "target.txt"),
            }
        ],
    )

    with service.SessionLocal() as session:
        stored = session.get(BatchPlan, plan.id)
        assert stored is not None
        stored.status = status
        session.commit()

    service.delete_plan(plan.id)

    with service.SessionLocal() as session:
        assert session.get(BatchPlan, plan.id) is None


def test_execute_rename_regular_file_survives_unsupported_native_noreplace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item

    root = tmp_path / "data"
    root.mkdir()
    trash = root / ".nas-file-center-trash"
    trash.mkdir()
    source = root / "source.webp"
    target = root / "renamed.webp"
    source.write_bytes(b"payload")
    _force_native_noreplace_unsupported(monkeypatch)

    result = execute_item(
        OperationItem(sequence=1, operation="rename", source=source, target=target),
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=trash,
        plan_id="compat-rename",
    )

    assert result.state == "completed"
    assert result.result_path == target
    assert not source.exists()
    assert target.read_bytes() == b"payload"


def test_execute_rename_compat_fallback_never_clobbers_existing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item

    root = tmp_path / "data"
    root.mkdir()
    trash = root / ".nas-file-center-trash"
    trash.mkdir()
    source = root / "source.webp"
    target = root / "renamed.webp"
    source.write_bytes(b"source")
    target.write_bytes(b"existing-target")
    _force_native_noreplace_unsupported(monkeypatch)

    result = execute_item(
        OperationItem(sequence=1, operation="rename", source=source, target=target),
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=trash,
        plan_id="compat-rename-collision",
    )

    assert result.state == "skipped"
    assert result.reason == "target already exists"
    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"existing-target"
