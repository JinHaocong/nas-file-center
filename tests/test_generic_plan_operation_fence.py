from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.router import PlanItemInput, _plan_requires_admin
from app.auth.dependencies import get_current_user
from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, User, WorkJob
from app.service import FileCenterService


@pytest.mark.parametrize("operation", ["quarantine", "touch", "move", "rename"])
def test_public_generic_plan_accepts_only_exposed_operations(operation: str) -> None:
    item = PlanItemInput(operation=operation, source="/data/example")
    assert item.operation == operation


@pytest.mark.parametrize(
    "operation",
    [
        "hardlink_optimize",
        "reflink_optimize",
        "media_corrupt_unlink_delete",
        "quarantine_unlink_purge",
        "quarantine_purge",
        "restore",
        "rmdir_empty",
        "mkdir_empty",
        "restore_empty_dir",
        "unlink",
    ],
)
def test_public_generic_plan_rejects_reserved_internal_operations(operation: str) -> None:
    with pytest.raises(ValidationError):
        PlanItemInput(operation=operation, source="/data/example")


def test_existing_reserved_optimization_item_remains_admin_restricted(tmp_path: Path) -> None:
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()

    service = FileCenterService(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
        )
    )

    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="legacy-injected-plan",
            kind="custom",
            status="draft",
            expected_changes=1,
            metadata_json="{}",
        )
        session.add(plan)
        session.flush()
        session.add(
            BatchPlanItem(
                plan_id=plan.id,
                sequence=1,
                operation="hardlink_optimize",
                source_path=str(data / "source.bin"),
                target_path=None,
                keep_path=str(data / "keep.bin"),
                expected_size=0,
                expected_mtime_ns=0,
                expected_device=0,
                expected_inode=0,
                expected_hash=None,
                state="planned",
                metadata_json="{}",
            )
        )
        session.commit()
        session.refresh(plan)

        assert _plan_requires_admin(plan, session) is True

@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [
        ("post", "pause"),
        ("post", "cancel"),
        ("delete", ""),
    ],
)
def test_member_cannot_manage_restricted_optimization_task(
    tmp_path: Path,
    method: str,
    path_suffix: str,
) -> None:
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
    )
    app = create_app(settings)
    service = app.state.service

    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="restricted-storage-plan",
            kind="dedupe",
            status="ready",
            expected_changes=1,
            metadata_json='{"source":"dedupe","storage_action":"hardlink"}',
        )
        session.add(plan)
        session.flush()
        job = WorkJob(
            kind="batch-plan-execute",
            status="queued",
            state_json=f'{{"plan_id":{plan.id}}}',
        )
        session.add(job)
        session.commit()
        task_id = int(job.id)

    member = User(
        id=999,
        username="member",
        password_hash="unused",
        role="user",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: member
    client = TestClient(app)
    url = f"/api/tasks/{task_id}" + (f"/{path_suffix}" if path_suffix else "")
    response = getattr(client, method)(url, headers={"Origin": "http://testserver"})

    assert response.status_code == 403



@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [
        ("post", "pause"),
        ("post", "resume"),
        ("post", "cancel"),
        ("post", "retry"),
        ("delete", ""),
    ],
)
def test_member_cannot_manage_task_with_reserved_internal_operation(
    tmp_path: Path,
    method: str,
    path_suffix: str,
) -> None:
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
    )
    app = create_app(settings)
    service = app.state.service

    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="legacy-injected-plan",
            kind="custom",
            status="ready",
            expected_changes=1,
            metadata_json="{}",
        )
        session.add(plan)
        session.flush()
        session.add(
            BatchPlanItem(
                plan_id=plan.id,
                sequence=1,
                operation="hardlink_optimize",
                source_path=str(data / "source.bin"),
                target_path=None,
                keep_path=str(data / "keep.bin"),
                expected_size=0,
                expected_mtime_ns=0,
                expected_device=0,
                expected_inode=0,
                expected_hash=None,
                state="planned",
                metadata_json="{}",
            )
        )
        job = WorkJob(
            kind="batch-plan-execute",
            status="queued",
            state_json=f'{{"plan_id":{plan.id}}}',
        )
        session.add(job)
        session.commit()
        task_id = int(job.id)

    member = User(
        id=1000,
        username="member-reserved-item",
        password_hash="unused",
        role="user",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: member
    client = TestClient(app)
    url = f"/api/tasks/{task_id}" + (f"/{path_suffix}" if path_suffix else "")
    response = getattr(client, method)(url, headers={"Origin": "http://testserver"})

    assert response.status_code == 403
