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


def test_unlink_purge_terminal_audit_is_scoped_to_current_plan_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from datetime import timedelta

    from app.exceptions import StateConflictError
    from app.models import AuditEvent, BatchPlanItem, QuarantineEntry, utcnow
    import app.quarantine.bulk_unlink_terminal as bulk_terminal
    from app.quarantine.unlink_purge import OPERATION_ID, SEMANTICS_VERSION

    service, data_dir = _make_service(tmp_path)
    old_digest = "a" * 64
    new_digest = "b" * 64
    advisory = {
        "scope": "indexed_roots_only",
        "status": "verified_none",
        "hardlink_survivors": [],
        "stale_candidates": [],
        "out_of_scope_candidates": [],
        "same_content_scope": "indexed_roots_only",
        "same_content_status": "verified_none",
        "same_content_independent_copies": [],
        "diagnostics": [],
    }
    monkeypatch.setattr(
        bulk_terminal,
        "discover_unlink_purge_advisory",
        lambda _session, _entry, _manifest: dict(advisory),
    )

    def add_purged_entry(session, name: str) -> QuarantineEntry:
        entry = QuarantineEntry(
            original_path=str(data_dir / f"{name}-original.bin"),
            quarantine_path=str(data_dir / ".nas-file-center-trash" / f"{name}.bin"),
            state="purged",
            tx_phase="purged",
            active_attempt_generation=1,
            size=0,
            mtime_ns=0,
            device=0,
            inode=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()
        return entry

    def item_metadata(entry_id: int, digest: str) -> str:
        return json.dumps(
            {
                "quarantine_entry_id": entry_id,
                "preview_digest": digest,
                "purge_semantics": SEMANTICS_VERSION,
                "unlink_manifest": {
                    "purge_semantics": SEMANTICS_VERSION,
                    "selected_entry_id": entry_id,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    old_timestamp = utcnow() - timedelta(days=1)
    with service.SessionLocal() as session:
        old_entry = add_purged_entry(session, "old")
        old_plan = BatchPlan(
            name="old purge plan",
            kind="quarantine-bulk-purge",
            status="completed",
            created_at=old_timestamp,
        )
        session.add(old_plan)
        session.flush()
        old_item = BatchPlanItem(
            plan_id=old_plan.id,
            sequence=1,
            operation=OPERATION_ID,
            source_path=old_entry.quarantine_path,
            state="completed",
            metadata_json=item_metadata(old_entry.id, old_digest),
        )
        session.add(old_item)
        session.flush()
        old_plan_id = int(old_plan.id)
        old_item_id = int(old_item.id)
        old_event = AuditEvent(
            timestamp=old_timestamp,
            operation=OPERATION_ID,
            path=old_item.source_path,
            result="completed",
            details_json=json.dumps(
                {
                    "plan_id": old_plan_id,
                    "item_id": old_item_id,
                    "quarantine_entry_id": old_entry.id,
                    "preview_digest": old_digest,
                    "purge_semantics": SEMANTICS_VERSION,
                    "terminal_result": "purged",
                    "survivor_scope": advisory["scope"],
                    "survivor_status": advisory["status"],
                    "hardlink_survivor_paths": [],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        session.add(old_event)
        session.commit()
        old_event_id = int(old_event.id)

    service.delete_plan(old_plan_id)

    with service.SessionLocal() as session:
        new_entry = add_purged_entry(session, "new")
        new_plan = BatchPlan(
            name="new purge plan",
            kind="quarantine-bulk-purge",
            status="completed",
            created_at=utcnow(),
        )
        session.add(new_plan)
        session.flush()
        new_item = BatchPlanItem(
            plan_id=new_plan.id,
            sequence=1,
            operation=OPERATION_ID,
            source_path=new_entry.quarantine_path,
            state="completed",
            metadata_json=item_metadata(new_entry.id, new_digest),
        )
        session.add(new_item)
        session.flush()

        assert int(new_plan.id) == old_plan_id
        assert int(new_item.id) == old_item_id

        current_event = AuditEvent(
            operation=OPERATION_ID,
            path=new_item.source_path,
            result="completed",
            details_json=json.dumps(
                {
                    "plan_id": int(new_plan.id),
                    "item_id": int(new_item.id),
                    "task_id": 777,
                    "quarantine_entry_id": None,
                    "preview_digest": None,
                    "reason": "purged",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        session.add(current_event)
        session.commit()
        current_event_id = int(current_event.id)
        new_entry_id = int(new_entry.id)
        current_path = new_item.source_path

    bulk_terminal.finalize_bulk_unlink_terminal_audits(
        service.SessionLocal,
        plan_id=old_plan_id,
        task_id=777,
        worker_id=None,
    )

    with service.SessionLocal() as session:
        old_event = session.get(AuditEvent, old_event_id)
        current_event = session.get(AuditEvent, current_event_id)
        current_item = session.get(BatchPlanItem, old_item_id)
        assert old_event is not None
        assert current_event is not None
        assert current_item is not None

        old_details = json.loads(old_event.details_json)
        current_details = json.loads(current_event.details_json)
        current_metadata = json.loads(current_item.metadata_json)

        assert old_details["preview_digest"] == old_digest
        assert old_details["quarantine_entry_id"] != new_entry_id
        assert current_details["preview_digest"] == new_digest
        assert current_details["quarantine_entry_id"] == new_entry_id
        assert current_details["terminal_result"] == "purged"
        assert current_metadata["terminal_advisory"] == advisory

    # A second completed audit in the same plan generation is still corruption
    # and must remain fail-closed. The historical generation above is ignored;
    # this newly inserted current-generation duplicate must not be.
    with service.SessionLocal() as session:
        session.add(
            AuditEvent(
                operation=OPERATION_ID,
                path=current_path,
                result="completed",
                details_json=json.dumps(
                    {
                        "plan_id": old_plan_id,
                        "item_id": old_item_id,
                        "task_id": 778,
                        "quarantine_entry_id": new_entry_id,
                        "preview_digest": new_digest,
                        "reason": "purged",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
        session.commit()

    with pytest.raises(StateConflictError, match="UNLINK_PURGE_TERMINAL_AUDIT_DUPLICATE"):
        bulk_terminal.finalize_bulk_unlink_terminal_audits(
            service.SessionLocal,
            plan_id=old_plan_id,
            task_id=778,
            worker_id=None,
        )


def test_rename_preview_directory_scope_recurses_regular_files_without_renaming_directory(
    tmp_path: Path,
) -> None:
    from app.batch.rename import RenameRule

    service, data_dir = _make_service(tmp_path)
    scope = data_dir / "Album"
    nested = scope / "Disc 2"
    nested.mkdir(parents=True)
    first = scope / "track 01.flac"
    second = nested / "track 02.flac"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    preview = service.rename_preview(
        [str(scope)],
        RenameRule(prefix="REN-"),
    )

    assert {row["source"]: row["target"] for row in preview} == {
        str(first): str(scope / "REN-track 01.flac"),
        str(second): str(nested / "REN-track 02.flac"),
    }
    assert all(row["conflict"] is False for row in preview)
    assert all(row["source"] != str(scope) for row in preview)
    assert all(row["target"] != str(scope.with_name("REN-Album")) for row in preview)
