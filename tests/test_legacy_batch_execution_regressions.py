from __future__ import annotations

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
