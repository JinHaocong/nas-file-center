from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.batch.rename import RenameRule
from app.config import Settings
from app.models import BatchPlanItem
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


def test_recursive_rename_directory_scope_does_not_follow_symlinks(tmp_path: Path) -> None:
    service, data_dir = _make_service(tmp_path)
    scope = data_dir / "Album"
    outside = data_dir / "Outside"
    scope.mkdir()
    outside.mkdir()

    inside_file = scope / "inside.txt"
    outside_file = outside / "outside.txt"
    inside_file.write_text("inside", encoding="utf-8")
    outside_file.write_text("outside", encoding="utf-8")

    linked_dir = scope / "linked-dir"
    linked_dir.symlink_to(outside, target_is_directory=True)
    linked_file = scope / "linked-file.txt"
    linked_file.symlink_to(outside_file)

    preview = service.rename_preview([str(scope)], RenameRule(prefix="REN-"))
    sources = {row["source"] for row in preview}

    assert sources == {str(inside_file)}
    assert str(linked_file) not in sources
    assert str(outside_file) not in sources


def test_recursive_rename_preview_children_become_plan_items(tmp_path: Path) -> None:
    service, data_dir = _make_service(tmp_path)
    scope = data_dir / "Album"
    nested = scope / "Disc 2"
    nested.mkdir(parents=True)
    first = scope / "track 01.flac"
    second = nested / "track 02.flac"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    preview = service.rename_preview([str(scope)], RenameRule(prefix="REN-"))
    assert preview
    assert all(row["conflict"] is False for row in preview)

    plan = service.create_plan(
        name="recursive rename plan",
        kind="rename",
        items=[
            {
                "operation": "rename",
                "source": row["source"],
                "target": row["target"],
            }
            for row in preview
        ],
    )

    with service.SessionLocal() as session:
        rows = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan.id)
                .order_by(BatchPlanItem.sequence)
            )
        )

    assert {row.source_path for row in rows} == {str(first), str(second)}
    assert {row.target_path for row in rows} == {
        str(scope / "REN-track 01.flac"),
        str(nested / "REN-track 02.flac"),
    }
    assert all(row.operation == "rename" for row in rows)
    assert all(row.source_path != str(scope) for row in rows)
