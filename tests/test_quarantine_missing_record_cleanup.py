"""Synthetic missing-quarantine-record retirement safety and API tests.

The filesystem is pytest tmp_path only; never a NAS mount.
"""
from datetime import timedelta
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.password import hash_password
from app.main import create_app
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, User, WorkJob, utcnow
from app.quarantine import missing_record_cleanup
from tests.test_quarantine_terminal_record_cleanup import maintenance_env


def _record(env, name="missing.q", *, state="active", **attributes):
    path = env["trash"] / "manual-delete" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with env["service"].SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(env["data"] / name),
            quarantine_path=str(path),
            state=state,
            **attributes,
        )
        if state == "purging":
            entry.updated_at = utcnow() - timedelta(minutes=30)
        session.add(entry)
        session.commit()
        return int(entry.id), path


def _cleanup(env, entry_id, token="CLEANUP_MISSING_RECORD"):
    return env["admin"].delete(
        f"/api/quarantine/{entry_id}/missing-record?confirmation={token}"
    )


def _assert_retained(env, entry_id):
    with env["service"].SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is not None
        assert session.scalars(
            select(AuditEvent).where(
                AuditEvent.operation == "quarantine.missing_record_cleanup"
            )
        ).all() == []


def test_active_external_missing_payload_is_metadata_only_and_audited(maintenance_env, monkeypatch):
    env = maintenance_env
    entry_id, path = _record(env)
    sentinel = env["data"] / "non-quarantine-sentinel.txt"
    sentinel.write_text("UNCHANGED")
    # Any Python filesystem delete primitive is forbidden on this API.
    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata cleanup must not remove filesystem objects")
    monkeypatch.setattr(os, "unlink", forbidden)
    monkeypatch.setattr(os, "rmdir", forbidden)

    response = _cleanup(env, entry_id)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "ok", "deleted": True, "id": entry_id, "metadata_only": True
    }
    assert not path.exists()
    assert sentinel.read_text() == "UNCHANGED"
    with env["service"].SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is None
        event = session.scalar(select(AuditEvent).where(
            AuditEvent.operation == "quarantine.missing_record_cleanup"
        ))
        assert event is not None
        detail = json.loads(event.details_json)
        assert detail["quarantine_entry_id"] == entry_id
        assert detail["metadata_only"] is True
        assert detail["filesystem_mutations"] == 0
        assert detail["prior_state"] == "active"


def test_old_ordinary_purging_without_ongoing_work_can_retire(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env, state="purging")
    # Test process startup precedes synthetic legacy state insertion; emulate
    # a documented restart for this OLD transition explicitly.
    env["admin"].app.state.service._quarantine_service_started_at = utcnow()
    response = _cleanup(env, entry_id)
    assert response.status_code == 200, response.text
    with env["service"].SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is None
        event = session.scalar(select(AuditEvent).where(
            AuditEvent.operation == "quarantine.missing_record_cleanup"
        ))
        assert json.loads(event.details_json)["prior_state"] == "purging"


def test_recent_purging_must_not_be_assumed_interrupted(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env, state="purging")
    with env["service"].SessionLocal() as session:
        row = session.get(QuarantineEntry, entry_id)
        row.updated_at = utcnow()
        session.commit()
    assert _cleanup(env, entry_id).status_code == 409
    _assert_retained(env, entry_id)


@pytest.mark.parametrize("attribute,value", [
    ("tx_token", "frozen-id"),
    ("tx_phase", "purging"),
    ("transaction_mode", "compat_transactional"),
    ("authoritative_anchor_path", "/unused/anchor"),
    ("active_attempt_generation", 1),
    ("quarantine_device", 123),
    ("quarantine_inode", 456),
    ("restore_target_path", "/unused/restore"),
])
def test_transactional_metadata_never_bypassed(maintenance_env, attribute, value):
    env = maintenance_env
    entry_id, _ = _record(env, **{attribute: value})
    response = _cleanup(env, entry_id)
    assert response.status_code == 409
    assert "transactional" in response.text
    _assert_retained(env, entry_id)


@pytest.mark.parametrize("with_evidence", [False, True])
def test_tx_namespace_even_empty_is_preserved(maintenance_env, with_evidence):
    env = maintenance_env
    entry_id, _ = _record(env)
    namespace = env["trash"] / ".tx" / f"entry-{entry_id}"
    namespace.mkdir(parents=True)
    if with_evidence:
        (namespace / "destroy-intent.json").write_text("evidence")
    assert _cleanup(env, entry_id).status_code == 409
    assert namespace.exists()
    _assert_retained(env, entry_id)


def test_payload_or_replacement_still_exists(maintenance_env):
    env = maintenance_env
    entry_id, path = _record(env)
    path.write_bytes(b"replaced external payload")
    assert _cleanup(env, entry_id).status_code == 409
    assert path.read_bytes() == b"replaced external payload"
    _assert_retained(env, entry_id)


def test_symlink_leaf_and_symlink_parent_fail_closed(maintenance_env):
    env = maintenance_env
    entry_id, leaf = _record(env)
    outside = env["data"] / "target.txt"
    outside.write_text("remain")
    leaf.symlink_to(outside)
    assert _cleanup(env, entry_id).status_code == 409
    leaf.unlink()
    parent = leaf.parent
    parent.rmdir()
    parent.symlink_to(env["data"], target_is_directory=True)
    assert _cleanup(env, entry_id).status_code == 409
    assert outside.read_text() == "remain"
    _assert_retained(env, entry_id)


def test_missing_or_unavailable_quarantine_root_is_not_proof(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env)
    env["trash"].rmdir() if not list(env["trash"].iterdir()) else None
    # A path under a missing/altered mount must not be treated as safely gone.
    root = env["trash"]
    env["admin"].app.state.service.settings.quarantine_root = env["data"] / "unmounted-trash"
    assert _cleanup(env, entry_id).status_code == 409
    _assert_retained(env, entry_id)


def test_permission_error_is_not_translated_to_missing(maintenance_env, monkeypatch):
    env = maintenance_env
    entry_id, _ = _record(env)
    original_open = missing_record_cleanup.os.open
    def inaccessible(path, flags, *args, **kwargs):
        if path == "manual-delete":
            raise PermissionError(13, "permission denied")
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(missing_record_cleanup.os, "open", inaccessible)
    response = _cleanup(env, entry_id)
    assert response.status_code == 409
    _assert_retained(env, entry_id)


def test_active_batch_job_blocks_missing_record_retirement(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env)
    with env["service"].SessionLocal() as session:
        session.add(WorkJob(kind="batch-plan-execute", status="running", state_json="{}"))
        session.commit()
    assert _cleanup(env, entry_id).status_code == 409
    _assert_retained(env, entry_id)


def test_unresolved_plan_item_blocks_missing_record_retirement(maintenance_env):
    env = maintenance_env
    entry_id, path = _record(env)
    with env["service"].SessionLocal() as session:
        plan = BatchPlan(name="pending synthetic quarantine plan", kind="quarantine-bulk-purge", status="draft")
        session.add(plan)
        session.flush()
        session.add(BatchPlanItem(
            plan_id=plan.id, sequence=1, operation="quarantine_purge",
            source_path=str(path), state="planned",
        ))
        session.commit()
    assert _cleanup(env, entry_id).status_code == 409
    _assert_retained(env, entry_id)


def test_missing_payload_reappears_at_final_check(maintenance_env, monkeypatch):
    env = maintenance_env
    entry_id, path = _record(env)
    original = missing_record_cleanup.require_absent_beneath_quarantine_root
    seen = [0]
    def race(root, candidate, *, label):
        if label == "quarantine payload":
            seen[0] += 1
            if seen[0] == 2:
                path.write_text("externally replaced")
        return original(root, candidate, label=label)
    monkeypatch.setattr(missing_record_cleanup, "require_absent_beneath_quarantine_root", race)
    assert _cleanup(env, entry_id).status_code == 409
    assert path.read_text() == "externally replaced"
    _assert_retained(env, entry_id)


def test_api_requires_admin_and_exact_confirmation(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env)
    app = env["admin"].app
    anonymous = TestClient(app)
    assert anonymous.delete(
        f"/api/quarantine/{entry_id}/missing-record?confirmation=CLEANUP_MISSING_RECORD"
    ).status_code in (401, 403)

    with env["service"].SessionLocal() as session:
        session.add(User(username="missing-record-user", role="user",
                         password_hash=hash_password("RegularPassword123!")))
        session.commit()
    regular = TestClient(app)
    assert regular.post("/api/auth/login",
        json={"username": "missing-record-user", "password": "RegularPassword123!"},
        headers={"Origin": "http://testserver"}).status_code == 200
    assert regular.delete(
        f"/api/quarantine/{entry_id}/missing-record?confirmation=CLEANUP_MISSING_RECORD"
    ).status_code == 403
    assert _cleanup(env, entry_id, token="DELETE_RECORD").status_code == 400
    _assert_retained(env, entry_id)
