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
from app.config import Settings
from app.service import FileCenterService
from app.main import create_app
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, User, WorkJob, utcnow
from app.quarantine import missing_record_cleanup



@pytest.fixture
def maintenance_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    settings = Settings(
        config_dir=tmp_path / "config",
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    client = TestClient(create_app(settings))
    client.headers["Origin"] = "http://testserver"
    assert client.post("/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"}).status_code == 200
    return {"data": data, "trash": trash, "service": service, "admin": client}


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


def test_missing_payload_parent_is_not_proof_of_external_deletion(maintenance_env):
    """A missing parent may be an offline subtree or transient mount."""
    env = maintenance_env
    entry_id, path = _record(env)
    path.parent.rmdir()
    response = _cleanup(env, entry_id)
    assert response.status_code == 409
    assert "ancestor directory is missing" in response.text
    _assert_retained(env, entry_id)


def test_missing_or_unavailable_quarantine_root_is_not_proof(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env)
    # Simulate an unmounted/moved quarantine root (no payload deletion).
    env["trash"].rename(env["data"] / ".detached-trash")
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
    def race(root, candidate, *, label, require_intact_parent=False):
        if label == "quarantine payload":
            seen[0] += 1
            if seen[0] == 2:
                path.write_text("externally replaced")
        return original(
            root, candidate, label=label,
            require_intact_parent=require_intact_parent,
        )
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


def test_transactional_recovery_diagnostic_reports_missing_payload_and_retained_tx(maintenance_env, monkeypatch):
    """A manually removed public payload does NOT override frozen evidence."""
    env = maintenance_env
    entry_id, path = _record(
        env, state="purging", tx_phase="purging",
        transaction_mode="cross_storage_transactional",
        active_attempt_generation=2,
    )
    tx_dir = env["trash"] / ".tx" / f"entry-{entry_id}"
    tx_dir.mkdir(parents=True)
    (tx_dir / "frozen-evidence").write_text("DO NOT TOUCH")

    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only diagnosis must not remove filesystem evidence")
    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", forbidden)
        patch.setattr(os, "rmdir", forbidden)
        response = env["admin"].get(f"/api/quarantine/{entry_id}/recovery-diagnostic")
    assert response.status_code == 200, response.text
    fields = response.json()
    assert fields["state"] == "purging"
    assert fields["tx_phase"] == "purging"
    assert fields["transaction_mode"] == "cross_storage_transactional"
    assert fields["active_attempt_generation"] == 2
    assert fields["payload_path_observation"] == "absent"
    assert fields["transaction_evidence_observation"] == "present"
    assert fields["observation_is_cleanup_authority"] is False
    assert tx_dir.joinpath("frozen-evidence").read_text() == "DO NOT TOUCH"
    assert not path.exists()
    _assert_retained(env, entry_id)
    assert _cleanup(env, entry_id).status_code == 409
    _assert_retained(env, entry_id)


def test_transactional_recovery_diagnostic_observations_distinguish_present_and_missing(maintenance_env):
    env = maintenance_env
    entry_id, path = _record(env, state="purging", tx_phase="purging",
                             transaction_mode="cross_storage_transactional")
    path.write_text("present quarantine bytes")
    evidence = env["trash"] / ".tx" / f"entry-{entry_id}"
    result = env["admin"].get(f"/api/quarantine/{entry_id}/recovery-diagnostic")
    assert result.status_code == 200
    assert result.json()["payload_path_observation"] == "present"
    assert result.json()["transaction_evidence_observation"] == "absent"
    assert path.read_text() == "present quarantine bytes"

    evidence.mkdir(parents=True)
    result = env["admin"].get(f"/api/quarantine/{entry_id}/recovery-diagnostic")
    assert result.json()["transaction_evidence_observation"] == "present"
    _assert_retained(env, entry_id)


def test_transactional_recovery_diagnostic_fails_closed_on_unknown_mount(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env, state="purging", tx_phase="purging",
                          transaction_mode="cross_storage_transactional")
    offline_root = env["data"] / "temporarily-offline"
    env["trash"].rename(offline_root)
    try:
        response = env["admin"].get(f"/api/quarantine/{entry_id}/recovery-diagnostic")
        assert response.status_code == 200
        assert response.json()["payload_path_observation"] == "indeterminate"
        assert response.json()["transaction_evidence_observation"] == "indeterminate"
        _assert_retained(env, entry_id)
    finally:
        offline_root.rename(env["trash"])


def test_transactional_recovery_diagnostic_nofollow_symlink_paths(maintenance_env):
    env = maintenance_env
    entry_id, path = _record(
        env, state="purging", tx_phase="purging",
        transaction_mode="cross_storage_transactional",
    )
    safe_target = env["data"] / "outside.txt"
    safe_target.write_text("leave unchanged")
    path.symlink_to(safe_target)
    response = env["admin"].get(f"/api/quarantine/{entry_id}/recovery-diagnostic")
    assert response.status_code == 200
    assert response.json()["payload_path_observation"] == "present"
    assert safe_target.read_text() == "leave unchanged"

    path.unlink()
    path.parent.rmdir()
    path.parent.symlink_to(env["data"], target_is_directory=True)
    response = env["admin"].get(f"/api/quarantine/{entry_id}/recovery-diagnostic")
    assert response.status_code == 200
    assert response.json()["payload_path_observation"] == "indeterminate"
    assert safe_target.read_text() == "leave unchanged"
    _assert_retained(env, entry_id)


def test_transactional_recovery_diagnostic_requires_admin(maintenance_env):
    env = maintenance_env
    entry_id, _ = _record(env, state="purging", tx_phase="purging")
    app = env["admin"].app
    anonymous = TestClient(app)
    assert anonymous.get(f"/api/quarantine/{entry_id}/recovery-diagnostic").status_code in (401, 403)
    with env["service"].SessionLocal() as session:
        session.add(User(
            username="diagnostic-regular", role="user",
            password_hash=hash_password("RegularPassword123!"),
        ))
        session.commit()
    regular = TestClient(app)
    assert regular.post(
        "/api/auth/login",
        json={"username": "diagnostic-regular", "password": "RegularPassword123!"},
        headers={"Origin": "http://testserver"},
    ).status_code == 200
    assert regular.get(f"/api/quarantine/{entry_id}/recovery-diagnostic").status_code == 403
    _assert_retained(env, entry_id)


# Distinct high-friction manual-retirement endpoint. Public payload deletion
# does not itself finalize cross-storage transactions.
def _orphan_tx(env, entry_id, token=None):
    return env["admin"].delete(
        f"/api/quarantine/{entry_id}/orphan-transaction-record?"
        f"confirmation={token or ('RETIRE_ORPHAN_TX_' + str(entry_id))}"
    )


def _frozen_orphan(env, *, device=None, **attrs):
    attributes = dict(
        state="purging", tx_phase="purging",
        transaction_mode="cross_storage_transactional",
        active_attempt_generation=2,
        quarantine_device=int(env["trash"].stat().st_dev) if device is None else device,
        quarantine_inode=44556,
    )
    attributes.update(attrs)
    entry_id, path = _record(env, name="orphan.q", **attributes)
    return entry_id, path


def test_orphan_purging_with_manually_missing_parent_is_db_only_and_audited(maintenance_env, monkeypatch):
    env = maintenance_env
    entry_id, path = _frozen_orphan(env)
    path.parent.rmdir()  # NAS operator removed the entire leaf directory
    sentinel = env["data"] / "original-untouched"
    sentinel.write_text("no filesystem mutation")
    app = env["admin"].app
    app.state.service._quarantine_service_started_at = utcnow()

    def forbidden(*args, **kwargs):
        raise AssertionError("Orphan retirement must never remove filesystem objects")
    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", forbidden)
        patch.setattr(os, "rmdir", forbidden)
        response = _orphan_tx(env, entry_id)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "ok", "deleted": True, "id": entry_id,
        "metadata_only": True, "transaction_finalized": False,
    }
    assert sentinel.read_text() == "no filesystem mutation"
    assert not path.parent.exists()
    with env["service"].SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is None
        event = session.scalar(select(AuditEvent).where(
            AuditEvent.operation == "quarantine.orphan_transaction_record_retire"
        ))
        assert event is not None
        payload = json.loads(event.details_json)
        assert payload["quarantine_entry_id"] == entry_id
        assert payload["prior_tx_phase"] == "purging"
        assert payload["prior_transaction_mode"] == "cross_storage_transactional"
        assert payload["prior_generation"] == 2
        assert payload["filesystem_mutations"] == 0
        assert payload["transaction_finalized"] is False


@pytest.mark.parametrize("variant", [
    "tx_present", "tx_empty", "payload_present", "symlink_leaf",
    "symlink_parent", "missing_mount", "device_mismatch",
    "device_unrecorded", "active_job", "pending_plan", "anchor_outside",
    "restore_authority", "recent_transition", "wrong_mode",
])
def test_orphan_manual_retirement_fails_closed(maintenance_env, variant):
    env = maintenance_env
    entry_id, path = _frozen_orphan(env)
    original_trash = env["trash"]
    outside = env["data"] / "sentinel"
    outside.write_text("untouched")
    detached = None

    if variant == "tx_present" or variant == "tx_empty":
        tx_dir = original_trash / ".tx" / f"entry-{entry_id}"
        tx_dir.mkdir(parents=True)
        if variant == "tx_present":
            (tx_dir / "frozen-intent").write_text("retain")
    elif variant == "payload_present":
        path.write_text("do not delete")
    elif variant == "symlink_leaf":
        path.symlink_to(outside)
    elif variant == "symlink_parent":
        path.parent.rmdir()
        path.parent.symlink_to(env["data"], target_is_directory=True)
    elif variant == "missing_mount":
        detached = env["data"] / "detached-trash"
        original_trash.rename(detached)
    elif variant in {"device_mismatch", "device_unrecorded", "anchor_outside", "restore_authority", "recent_transition", "wrong_mode"}:
        with env["service"].SessionLocal() as session:
            row = session.get(QuarantineEntry, entry_id)
            if variant == "device_mismatch":
                row.quarantine_device = int(original_trash.stat().st_dev) + 1
            elif variant == "device_unrecorded":
                row.quarantine_device = None
            elif variant == "anchor_outside":
                row.authoritative_anchor_path = str(outside)
            elif variant == "restore_authority":
                row.restore_target_path = str(outside)
            elif variant == "recent_transition":
                row.updated_at = utcnow()
            elif variant == "wrong_mode":
                row.transaction_mode = "other"
            session.commit()
    elif variant == "active_job":
        with env["service"].SessionLocal() as session:
            session.add(WorkJob(kind="batch-plan-execute", status="running", state_json="{}"))
            session.commit()
    elif variant == "pending_plan":
        with env["service"].SessionLocal() as session:
            plan = BatchPlan(name="frozen cleanup", kind="quarantine-bulk-purge", status="draft")
            session.add(plan)
            session.flush()
            session.add(BatchPlanItem(plan_id=plan.id, sequence=1,
                operation="quarantine_purge", source_path=str(path), state="planned"))
            session.commit()

    try:
        response = _orphan_tx(env, entry_id)
        assert response.status_code == 409, (variant, response.status_code, response.text)
        with env["service"].SessionLocal() as session:
            assert session.get(QuarantineEntry, entry_id) is not None
            assert session.scalar(select(AuditEvent).where(
                AuditEvent.operation == "quarantine.orphan_transaction_record_retire"
            )) is None
        assert outside.read_text() == "untouched"
    finally:
        if detached:
            detached.rename(original_trash)


def test_orphan_old_missing_record_endpoint_is_still_blocked(maintenance_env):
    env = maintenance_env
    entry_id, _ = _frozen_orphan(env)
    assert _cleanup(env, entry_id).status_code == 409
    response = _orphan_tx(env, entry_id, token="CLEANUP_MISSING_RECORD")
    assert response.status_code == 400
    _assert_retained(env, entry_id)


def test_orphan_repeat_check_rejects_external_payload_reappearance(maintenance_env, monkeypatch):
    env = maintenance_env
    entry_id, path = _frozen_orphan(env)
    original = missing_record_cleanup.require_absent_beneath_quarantine_root
    seen = [0]
    def race(root, candidate, *, label, require_intact_parent=False, expected_root_device=None):
        if label == "orphan quarantine payload":
            seen[0] += 1
            if seen[0] == 2:
                path.write_text("reappeared")
        return original(
            root, candidate, label=label, require_intact_parent=require_intact_parent,
            expected_root_device=expected_root_device,
        )
    monkeypatch.setattr(missing_record_cleanup, "require_absent_beneath_quarantine_root", race)
    response = _orphan_tx(env, entry_id)
    assert response.status_code == 409
    assert path.read_text() == "reappeared"
    _assert_retained(env, entry_id)


def test_orphan_retirement_endpoint_admin_only(maintenance_env):
    env = maintenance_env
    entry_id, _ = _frozen_orphan(env)
    anonymous = TestClient(env["admin"].app)
    assert anonymous.delete(
        f"/api/quarantine/{entry_id}/orphan-transaction-record?confirmation=RETIRE_ORPHAN_TX_{entry_id}"
    ).status_code in (401, 403)

    with env["service"].SessionLocal() as session:
        session.add(User(username="orphan-retire-user", role="user",
                         password_hash=hash_password("RegularPassword123!")))
        session.commit()
    regular = TestClient(env["admin"].app)
    assert regular.post("/api/auth/login",
        json={"username": "orphan-retire-user", "password": "RegularPassword123!"},
        headers={"Origin": "http://testserver"}).status_code == 200
    assert regular.delete(
        f"/api/quarantine/{entry_id}/orphan-transaction-record?confirmation=RETIRE_ORPHAN_TX_{entry_id}"
    ).status_code == 403
    _assert_retained(env, entry_id)


def test_owner_confirmed_two_incident_rows_are_db_only_and_audited(maintenance_env, monkeypatch):
    env = maintenance_env
    for entry_id in (1106, 884):
        with env["service"].SessionLocal() as session:
            record = QuarantineEntry(
                id=entry_id,
                original_path=str(env["data"] / f"old-{entry_id}"),
                quarantine_path=str(env["trash"] / f"old-{entry_id}"),
                state="purging", tx_phase="purging",
                transaction_mode="cross_storage_transactional",
                active_attempt_generation=2,
            )
            session.add(record)
            session.commit()
        sentinel = env["data"] / "sentinel"
        sentinel.write_text("unchanged")
        def forbidden(*args, **kwargs):
            raise AssertionError("DB-only cleanup must not remove filesystem objects")
        with monkeypatch.context() as patch:
            patch.setattr(os, "unlink", forbidden)
            patch.setattr(os, "rmdir", forbidden)
            response = env["admin"].delete(
                f"/api/quarantine/{entry_id}/owner-deleted-record?confirmation=FORGET_OWNER_DELETED_{entry_id}"
            )
        assert response.status_code == 200, response.text
        assert response.json()["transaction_finalized"] is False
        assert sentinel.read_text() == "unchanged"
        with env["service"].SessionLocal() as session:
            assert session.get(QuarantineEntry, entry_id) is None
            event = session.scalar(select(AuditEvent).where(
                AuditEvent.operation == "quarantine.owner_manual_record_forget",
                AuditEvent.details_json.like(f'%"quarantine_entry_id": {entry_id}%'),
            ))
            assert event is not None


def test_owner_confirmed_cleanup_denies_unlisted_ids_bad_confirmation_and_wrong_state(maintenance_env):
    env = maintenance_env
    id_other, _ = _record(env, state="purging", tx_phase="purging",
                          transaction_mode="cross_storage_transactional")
    assert env["admin"].delete(
        f"/api/quarantine/{id_other}/owner-deleted-record?confirmation=FORGET_OWNER_DELETED_{id_other}"
    ).status_code == 400
    with env["service"].SessionLocal() as session:
        row = QuarantineEntry(
            id=1106, original_path=str(env["data"] / "test1106"),
            quarantine_path=str(env["trash"] / "test1106"), state="active",
        )
        session.add(row)
        session.commit()
    assert env["admin"].delete(
        "/api/quarantine/1106/owner-deleted-record?confirmation=WRONG"
    ).status_code == 400
    assert env["admin"].delete(
        "/api/quarantine/1106/owner-deleted-record?confirmation=FORGET_OWNER_DELETED_1106"
    ).status_code == 409
    with env["service"].SessionLocal() as session:
        assert session.get(QuarantineEntry, 1106) is not None
        assert session.get(QuarantineEntry, id_other) is not None


def test_owner_confirmed_cleanup_is_admin_only(maintenance_env):
    env = maintenance_env
    anonymous = TestClient(env["admin"].app)
    assert anonymous.delete(
        "/api/quarantine/1106/owner-deleted-record?confirmation=FORGET_OWNER_DELETED_1106"
    ).status_code in (401, 403)
