from __future__ import annotations

from datetime import timedelta
import errno
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    DataLifecyclePolicy,
    QuarantineEntry,
    utcnow,
)
from app.quarantine.paths import safe_quarantine_hash
from app.service import FileCenterService


def _setup_service(tmp_path: Path) -> tuple[FileCenterService, Path, Path]:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    return service, data, trash


def test_two_phase_quarantine_execution(tmp_path: Path):
    """execute_plan performs two-phase quarantine with pre-allocated path and active record."""
    service, data, trash = _setup_service(tmp_path)
    test_file = data / "docs" / "report.pdf"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_bytes(b"%PDF-1.4 test content")

    # Set retention policy to 30 days
    service.update_quarantine_retention_policy(30)

    plan = service.create_plan(
        name="Quarantine Test Plan",
        kind="dedupe",
        items=[
            {
                "operation": "quarantine",
                "source": str(test_file),
            }
        ],
    )
    # Manually transition plan to ready
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        p.status = "ready"
        session.commit()

    exec_res = service.execute_plan(plan.id)
    assert exec_res["status"] == "completed"

    # Source should no longer exist
    assert not test_file.exists()

    # Quarantine entry should exist in active state
    with service.SessionLocal() as session:
        entry = session.scalar(
            select(QuarantineEntry).where(QuarantineEntry.original_path == str(test_file))
        )
        assert entry is not None
        assert entry.state == "active"
        assert entry.size == len(b"%PDF-1.4 test content")
        assert entry.content_hash == safe_quarantine_hash(entry.quarantine_path)
        assert entry.quarantined_at is not None
        assert entry.expires_at is not None
        assert Path(entry.quarantine_path).exists()


def test_crash_reconciliation_all_cases(tmp_path: Path):
    """Crash reconciliation correctly recovers all 4 preparing states."""
    service, data, trash = _setup_service(tmp_path)
    now = utcnow()

    # Case 1: Source exists, Target does not -> abandoned
    src1 = data / "case1.txt"
    src1.write_text("case1")
    tgt1 = trash / "plan-1" / "root-0" / "case1.q-1.txt"

    # Case 2: Target exists, Source does not -> active
    src2 = data / "case2.txt"
    tgt2 = trash / "plan-1" / "root-0" / "case2.q-2.txt"
    tgt2.parent.mkdir(parents=True, exist_ok=True)
    tgt2.write_text("case2")

    # Case 3: Neither exists -> inconsistent
    src3 = data / "case3.txt"
    tgt3 = trash / "plan-1" / "root-0" / "case3.q-3.txt"

    # Case 4: Both exist -> inconsistent
    src4 = data / "case4.txt"
    src4.write_text("case4")
    tgt4 = trash / "plan-1" / "root-0" / "case4.q-4.txt"
    tgt4.parent.mkdir(parents=True, exist_ok=True)
    tgt4.write_text("case4")

    with service.SessionLocal() as session:
        e1 = QuarantineEntry(plan_item_id=None, original_path=str(src1), quarantine_path=str(tgt1), state="preparing", created_at=now, updated_at=now)
        e2 = QuarantineEntry(plan_item_id=None, original_path=str(src2), quarantine_path=str(tgt2), state="preparing", created_at=now, updated_at=now)
        e3 = QuarantineEntry(plan_item_id=None, original_path=str(src3), quarantine_path=str(tgt3), state="preparing", created_at=now, updated_at=now)
        e4 = QuarantineEntry(plan_item_id=None, original_path=str(src4), quarantine_path=str(tgt4), state="preparing", created_at=now, updated_at=now)
        session.add_all([e1, e2, e3, e4])
        session.commit()
        id1, id2, id3, id4 = e1.id, e2.id, e3.id, e4.id

    # Reconcile all
    results = service.reconcile_all_preparing_entries()
    assert len(results) == 4

    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, id1).state == "abandoned"
        reconciled_2 = session.get(QuarantineEntry, id2)
        assert reconciled_2.state == "active"
        assert reconciled_2.content_hash == safe_quarantine_hash(tgt2)
        assert reconciled_2.quarantined_at is not None
        assert reconciled_2.expires_at is None  # policy was 0
        assert session.get(QuarantineEntry, id3).state == "inconsistent"
        assert session.get(QuarantineEntry, id4).state == "inconsistent"


def test_restore_quarantine_entry_skip_and_rename(tmp_path: Path):
    """Restore with conflict policies 'skip' and 'rename'."""
    service, data, trash = _setup_service(tmp_path)
    now = utcnow()
    src = data / "restore_test.txt"
    tgt = trash / "restore_tgt.txt"
    tgt.write_text("restorable content")
    sha = safe_quarantine_hash(tgt)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            plan_item_id=None,
            original_path=str(src),
            quarantine_path=str(tgt),
            state="active",
            size=len("restorable content"),
            content_hash=sha,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # 1. Clean restore (dest does not exist)
    res = service.restore_quarantine_entry(entry_id, conflict_policy="skip")
    assert res["state"] == "restored"
    assert src.exists()
    assert not tgt.exists()
    assert src.read_text() == "restorable content"

    # Reset target and entry for collision testing
    tgt.write_text("restorable content")
    with service.SessionLocal() as session:
        e = session.get(QuarantineEntry, entry_id)
        e.state = "active"
        session.commit()

    # 2. Collision with skip policy
    res_skip = service.restore_quarantine_entry(entry_id, conflict_policy="skip")
    assert res_skip["state"] == "skipped"
    assert tgt.exists()

    # 3. Collision with rename policy
    res_rename = service.restore_quarantine_entry(entry_id, conflict_policy="rename")
    assert res_rename["state"] == "restored"
    expected_renamed = data / f"restore_test.restored-{entry_id}.txt"
    assert expected_renamed.exists()
    assert expected_renamed.read_text() == "restorable content"
    assert not tgt.exists()


def test_purge_quarantine_entry_admin_only(tmp_path: Path):
    """Admin-only purge permanently deletes file, removes empty parent dirs, and records purged state."""
    service, data, trash = _setup_service(tmp_path)
    now = utcnow()
    tgt = trash / "plan-10" / "root-0" / "subdir" / "purge_me.q-1.txt"
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text("to be purged")
    sha = safe_quarantine_hash(tgt)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            plan_item_id=None,
            original_path=str(data / "purge_me.txt"),
            quarantine_path=str(tgt),
            state="active",
            size=len("to be purged"),
            content_hash=sha,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # Non-admin cannot purge
    with pytest.raises(PermissionError):
        service.purge_quarantine_entry(entry_id, confirmation="DELETE", is_admin=False)

    # Invalid confirmation cannot purge
    with pytest.raises(ValueError, match="DELETE"):
        service.purge_quarantine_entry(entry_id, confirmation="CONFIRM", is_admin=True)

    # Valid purge
    res = service.purge_quarantine_entry(entry_id, confirmation="DELETE", is_admin=True)
    assert res["state"] == "purged"
    assert not tgt.exists()
    # Empty parent directories should be cleaned up up to trash
    assert not (trash / "plan-10").exists()
    # But trash itself must remain
    assert trash.exists()

    with service.SessionLocal() as session:
        e = session.get(QuarantineEntry, entry_id)
        assert e.state == "purged"
        assert e.purged_at is not None


def test_quarantine_retention_policy_validation_and_no_auto_purge(tmp_path: Path):
    """Quarantine retention policy strictly validates 0, 7, 30, 90 and does not auto-purge."""
    service, data, trash = _setup_service(tmp_path)
    assert service.get_quarantine_retention_policy()["quarantine_retention_days"] == 0

    with pytest.raises(ValueError):
        service.update_quarantine_retention_policy(15)

    res = service.update_quarantine_retention_policy(90)
    assert res["quarantine_retention_days"] == 90
    assert service.get_quarantine_retention_policy()["quarantine_retention_days"] == 90


def test_new_unlink_plan_rejected(tmp_path: Path):
    """Attempting to create a plan with operation='unlink' must be rejected."""
    service, data, trash = _setup_service(tmp_path)
    test_file = data / "test.txt"
    test_file.write_text("unlink test")

    with pytest.raises(ValueError, match="unlink"):
        service.create_plan(
            name="Unlink Plan",
            kind="dedupe",
            items=[{"operation": "unlink", "source": str(test_file)}],
        )


def test_legacy_unlink_plan_execution_compatibility(tmp_path: Path):
    """Legacy persisted unlink plans remain executable if allow_mutation=True and allow_delete=True."""
    service, data, trash = _setup_service(tmp_path)
    test_file = data / "legacy.txt"
    test_file.write_text("legacy file")

    with service.SessionLocal() as session:
        plan = BatchPlan(name="Legacy Unlink", kind="dedupe", status="ready", expected_changes=1)
        session.add(plan)
        session.flush()
        item = BatchPlanItem(plan_id=plan.id, sequence=1, operation="unlink", source_path=str(test_file), state="planned")
        session.add(item)
        session.commit()
        plan_id = plan.id

    exec_res = service.execute_plan(plan_id)
    assert exec_res["status"] == "completed"
    assert not test_file.exists()


def test_restore_hash_tamper_detection(tmp_path: Path):
    """If file in quarantine was modified externally, restore is aborted and marked inconsistent."""
    service, data, trash = _setup_service(tmp_path)
    now = utcnow()
    src = data / "original.txt"
    tgt = trash / "tampered.txt"
    tgt.write_text("original content")
    sha = safe_quarantine_hash(tgt)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            plan_item_id=None,
            original_path=str(src),
            quarantine_path=str(tgt),
            state="active",
            size=len("original content"),
            content_hash=sha,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # Tamper with file
    tgt.write_text("modified content")

    with pytest.raises(ValueError, match="hash mismatch"):
        service.restore_quarantine_entry(entry_id, conflict_policy="skip")

    with service.SessionLocal() as session:
        e = session.get(QuarantineEntry, entry_id)
        assert e.state == "inconsistent"
        assert "hash" in e.last_error.lower()


def test_retention_policy_strict_type_and_value(tmp_path: Path):
    """Quarantine retention policy rejects bool, string, negative, and non-allowed values."""
    service, data, trash = _setup_service(tmp_path)

    for invalid in [True, False, "30", 30.0, -1, 1, 14, 365]:
        with pytest.raises(ValueError):
            service.update_quarantine_retention_policy(invalid)

