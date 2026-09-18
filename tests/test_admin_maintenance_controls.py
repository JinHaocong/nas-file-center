from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, BatchPlan, QuarantineEntry, User, Workflow, WorkflowRevision, utcnow
from app.service import FileCenterService


@pytest.fixture
def maintenance_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()

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

    with service.SessionLocal() as session:
        member = User(
            username="member",
            password_hash=hash_password("MemberPassword123!"),
            role="member",
            is_active=True,
        )
        session.add(member)
        session.commit()

    app = create_app(settings)

    def login(username: str, password: str) -> TestClient:
        client = TestClient(app)
        client.headers["Origin"] = "http://testserver"
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200
        return client

    return {
        "service": service,
        "data": data,
        "trash": trash,
        "admin": login("admin", "AdminPassword123!"),
        "member": login("member", "MemberPassword123!"),
    }


def _create_archived_workflow(env, *, archived: bool = True) -> tuple[int, int]:
    service = env["service"]
    with service.SessionLocal() as session:
        wf = Workflow(
            name="Archived cleanup target",
            description="maintenance fixture",
            current_revision=1,
            is_builtin=False,
            archived_at=utcnow() if archived else None,
        )
        session.add(wf)
        session.flush()
        session.add(
            WorkflowRevision(
                workflow_id=wf.id,
                revision=1,
                definition_json='{"schema_version":1,"mode":"file","steps":[]}',
                definition_sha256="a" * 64,
            )
        )
        session.commit()
        return int(wf.id), int(wf.current_revision)


def test_archived_workflow_permanent_delete_requires_admin_archive_confirmation_and_no_active_plan(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    member = env["member"]
    service = env["service"]

    active_id, active_rev = _create_archived_workflow(env, archived=False)
    response = admin.delete(
        f"/api/workflows/{active_id}/permanent?expected_current_revision={active_rev}&confirmation=DELETE"
    )
    assert response.status_code == 409

    workflow_id, revision = _create_archived_workflow(env, archived=True)

    assert member.delete(
        f"/api/workflows/{workflow_id}/permanent?expected_current_revision={revision}&confirmation=DELETE"
    ).status_code == 403

    bad_confirmation = admin.delete(
        f"/api/workflows/{workflow_id}/permanent?expected_current_revision={revision}&confirmation=NO"
    )
    assert bad_confirmation.status_code in (400, 422)

    with service.SessionLocal() as session:
        session.add(
            BatchPlan(
                name="still active",
                kind=f"workflow-{workflow_id}",
                status="ready",
                expected_changes=0,
                metadata_json=f'{{"source":"workflow","workflow_id":{workflow_id}}}',
            )
        )
        session.commit()

    blocked = admin.delete(
        f"/api/workflows/{workflow_id}/permanent?expected_current_revision={revision}&confirmation=DELETE"
    )
    assert blocked.status_code == 409

    with service.SessionLocal() as session:
        plan = session.scalar(select(BatchPlan).where(BatchPlan.kind == f"workflow-{workflow_id}"))
        assert plan is not None
        plan.status = "completed"
        session.commit()

    deleted = admin.delete(
        f"/api/workflows/{workflow_id}/permanent?expected_current_revision={revision}&confirmation=DELETE"
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    with service.SessionLocal() as session:
        assert session.get(Workflow, workflow_id) is None
        assert session.scalar(
            select(func.count(WorkflowRevision.id)).where(WorkflowRevision.workflow_id == workflow_id)
        ) == 0


def _seed_quarantine_entry(env, *, state: str, name: str, payload_exists: bool = False) -> int:
    service = env["service"]
    data = env["data"]
    trash = env["trash"]
    qpath = trash / f"{name}.q"
    if payload_exists:
        qpath.write_text("unexpected payload", encoding="utf-8")
    with service.SessionLocal() as session:
        row = QuarantineEntry(
            original_path=str(data / name),
            quarantine_path=str(qpath),
            state=state,
            size=0,
            content_hash=None,
            purged_at=utcnow() if state == "purged" else None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(row)
        session.commit()
        return int(row.id)


def test_quarantine_purged_record_delete_is_metadata_only_admin_and_payload_absence_guarded(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    member = env["member"]
    service = env["service"]

    purged_id = _seed_quarantine_entry(env, state="purged", name="gone.txt")
    assert member.delete(
        f"/api/quarantine/{purged_id}/record?confirmation=DELETE_RECORD"
    ).status_code == 403

    deleted = admin.delete(
        f"/api/quarantine/{purged_id}/record?confirmation=DELETE_RECORD"
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "ok", "deleted": True, "id": purged_id}

    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, purged_id) is None
        audit = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.operation == "quarantine.record_delete")
            .order_by(AuditEvent.id.desc())
        )
        assert audit is not None

    active_id = _seed_quarantine_entry(env, state="active", name="active.txt")
    blocked_active = admin.delete(
        f"/api/quarantine/{active_id}/record?confirmation=DELETE_RECORD"
    )
    assert blocked_active.status_code == 409

    reappeared_id = _seed_quarantine_entry(
        env,
        state="purged",
        name="reappeared.txt",
        payload_exists=True,
    )
    blocked_payload = admin.delete(
        f"/api/quarantine/{reappeared_id}/record?confirmation=DELETE_RECORD"
    )
    assert blocked_payload.status_code == 409
    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, reappeared_id) is not None


def test_quarantine_bulk_record_delete_is_explicit_all_or_nothing(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]

    first = _seed_quarantine_entry(env, state="purged", name="bulk-1")
    second = _seed_quarantine_entry(env, state="purged", name="bulk-2")
    active = _seed_quarantine_entry(env, state="active", name="bulk-active")

    rejected = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": [first, active], "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert rejected.status_code == 409
    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, first) is not None
        assert session.get(QuarantineEntry, active) is not None

    response = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": [first, second], "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    assert response.json()["deleted_ids"] == [first, second]
    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, first) is None
        assert session.get(QuarantineEntry, second) is None


def test_audit_history_clear_requires_admin_confirmation_and_keeps_one_self_audit(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    member = env["member"]
    service = env["service"]

    with service.SessionLocal() as session:
        session.add_all([
            AuditEvent(operation="fixture.one", result="ok"),
            AuditEvent(operation="fixture.two", result="ok"),
            AuditEvent(operation="fixture.three", result="ok"),
        ])
        session.commit()
        before = session.scalar(select(func.count(AuditEvent.id))) or 0
    assert before >= 3

    assert member.post(
        "/api/audit/clear",
        json={"confirmation": "CLEAR"},
        headers={"Origin": "http://testserver"},
    ).status_code == 403

    bad = admin.post(
        "/api/audit/clear",
        json={"confirmation": "NO"},
        headers={"Origin": "http://testserver"},
    )
    assert bad.status_code in (400, 422)

    cleared = admin.post(
        "/api/audit/clear",
        json={"confirmation": "CLEAR"},
        headers={"Origin": "http://testserver"},
    )
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["deleted_count"] >= 3
    assert body["remaining_count"] == 1

    with service.SessionLocal() as session:
        rows = list(session.scalars(select(AuditEvent).order_by(AuditEvent.id.asc())))
        assert len(rows) == 1
        assert rows[0].operation == "audit.clear"
