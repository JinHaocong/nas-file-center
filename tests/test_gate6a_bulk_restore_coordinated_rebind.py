from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    app = create_app(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=trash,
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
            allow_mutation=True,
            allow_delete=True,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client


def _active_entry(client: TestClient, name: str, payload: bytes) -> tuple[int, Path, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    original = data / name
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / f"pending-{name}"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=0,
            content_hash=None,
            mtime_ns=0,
            device=0,
            inode=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()
        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"{Path(name).stem}.q-{entry.id}{Path(name).suffix}"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)
        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.size = st.st_size
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.mtime_ns = st.st_mtime_ns
        entry.device = st.st_dev
        entry.inode = st.st_ino
        session.commit()
        return int(entry.id), anchor, public_view, original


def _generate_restore_plan(client: TestClient, entry_ids: list[int]) -> int:
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": entry_ids, "conflict_policy": "rename"},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": entry_ids,
            "conflict_policy": "rename",
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    return int(generated.json()["id"])


def _prepare_worker(service, plan_id: int, worker_id: str) -> int:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()
        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan_id}),
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(job)
        session.commit()
        return int(job.id)


def _run_worker(service, job_id: int, worker_id: str) -> None:
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        BatchPlanExecuteHandler().run(
            job,
            JobContext(service.engine, service.SessionLocal, job_id, worker_id),
            service.settings,
        )


def _compat(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )


def test_post_validate_qid_and_source_rebind_cannot_restore_unselected_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    service = client.app.state.service

    selected_id, _selected_anchor, selected_public, selected_original = _active_entry(
        client, "selected-a.txt", b"selected-a"
    )
    unselected_id, _unselected_anchor, unselected_public, unselected_original = _active_entry(
        client, "unselected-b.txt", b"unselected-b"
    )
    sibling_id, sibling_anchor, sibling_public, sibling_original = _active_entry(
        client, "healthy-c.txt", b"healthy-c"
    )

    plan_id = _generate_restore_plan(client, [selected_id, sibling_id])
    assert service.freeze_plan(plan_id).status == "frozen"
    validation = service.validate_plan(plan_id)
    assert validation["status"] == "ready"

    # Attack the exact post-Validate / pre-Execute boundary.  The item was frozen for A,
    # but mutable qid + source are coordinated to point at unselected B.  The frozen
    # expected_* identity and target remain A's authority.
    with service.SessionLocal() as session:
        items = (
            session.query(BatchPlanItem)
            .filter_by(plan_id=plan_id)
            .order_by(BatchPlanItem.sequence)
            .all()
        )
        attacked = next(item for item in items if item.source_path == str(selected_public))
        healthy = next(item for item in items if item.source_path == str(sibling_public))
        metadata = json.loads(attacked.metadata_json or "{}")
        assert metadata["quarantine_entry_id"] == selected_id
        assert attacked.target_path == str(selected_original)
        metadata["quarantine_entry_id"] = unselected_id
        attacked.metadata_json = json.dumps(metadata, sort_keys=True)
        attacked.source_path = str(unselected_public)
        attacked_id = int(attacked.id)
        healthy_id = int(healthy.id)
        session.commit()

    _compat(monkeypatch)
    _run_worker(service, _prepare_worker(service, plan_id, "worker-coordinated-rebind"), "worker-coordinated-rebind")

    assert not selected_original.exists()
    assert selected_public.exists()
    assert selected_public.read_bytes() == b"selected-a"
    assert not unselected_original.exists()
    assert unselected_public.exists()
    assert unselected_public.read_bytes() == b"unselected-b"
    assert sibling_original.exists()
    assert sibling_original.read_bytes() == sibling_anchor.read_bytes()
    assert not sibling_public.exists()

    with service.SessionLocal() as session:
        attacked = session.get(BatchPlanItem, attacked_id)
        healthy = session.get(BatchPlanItem, healthy_id)
        assert attacked is not None and healthy is not None
        assert attacked.state == "failed"
        assert attacked.reason and (
            "frozen" in attacked.reason.lower()
            or "identity" in attacked.reason.lower()
            or "authority" in attacked.reason.lower()
        )
        assert healthy.state == "completed"

        selected = session.get(QuarantineEntry, selected_id)
        unselected = session.get(QuarantineEntry, unselected_id)
        sibling = session.get(QuarantineEntry, sibling_id)
        assert selected is not None and unselected is not None and sibling is not None
        assert (selected.state, selected.tx_phase) == ("active", "active")
        assert (unselected.state, unselected.tx_phase) == ("active", "active")
        assert (sibling.state, sibling.tx_phase) == ("restored", "restored")

        audits = session.query(AuditEvent).filter_by(operation="restore").all()
        attacked_audits = []
        healthy_audits = []
        for event in audits:
            details = json.loads(event.details_json or "{}")
            if details.get("item_id") == attacked_id:
                attacked_audits.append((event, details))
            if details.get("item_id") == healthy_id:
                healthy_audits.append((event, details))

        assert len(attacked_audits) == 1
        assert attacked_audits[0][0].result == "failed"
        assert not any(
            event.result in {"completed", "skipped"}
            and details.get("quarantine_entry_id") == unselected_id
            for event, details in attacked_audits
        )
        assert len(healthy_audits) == 1
        assert healthy_audits[0][0].result == "completed"


def test_post_validate_target_rebind_cannot_change_frozen_restore_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    service = client.app.state.service

    selected_id, _selected_anchor, selected_public, selected_original = _active_entry(
        client, "target-a.txt", b"target-a"
    )
    sibling_id, sibling_anchor, sibling_public, sibling_original = _active_entry(
        client, "target-c.txt", b"target-c"
    )

    plan_id = _generate_restore_plan(client, [selected_id, sibling_id])
    assert service.freeze_plan(plan_id).status == "frozen"
    validation = service.validate_plan(plan_id)
    assert validation["status"] == "ready"

    forged_target = Path(service.settings.data_mount) / "forged-target.txt"
    with service.SessionLocal() as session:
        items = (
            session.query(BatchPlanItem)
            .filter_by(plan_id=plan_id)
            .order_by(BatchPlanItem.sequence)
            .all()
        )
        attacked = next(item for item in items if item.source_path == str(selected_public))
        healthy = next(item for item in items if item.source_path == str(sibling_public))
        assert attacked.target_path == str(selected_original)
        attacked.target_path = str(forged_target)
        attacked_id = int(attacked.id)
        healthy_id = int(healthy.id)
        session.commit()

    _compat(monkeypatch)
    _run_worker(service, _prepare_worker(service, plan_id, "worker-target-rebind"), "worker-target-rebind")

    assert not selected_original.exists()
    assert not forged_target.exists()
    assert selected_public.exists()
    assert selected_public.read_bytes() == b"target-a"
    assert sibling_original.exists()
    assert sibling_original.read_bytes() == sibling_anchor.read_bytes()
    assert not sibling_public.exists()

    with service.SessionLocal() as session:
        attacked = session.get(BatchPlanItem, attacked_id)
        healthy = session.get(BatchPlanItem, healthy_id)
        assert attacked is not None and healthy is not None
        assert attacked.state == "failed"
        assert attacked.reason and (
            "target" in attacked.reason.lower()
            or "frozen" in attacked.reason.lower()
            or "authority" in attacked.reason.lower()
        )
        assert healthy.state == "completed"

        selected = session.get(QuarantineEntry, selected_id)
        sibling = session.get(QuarantineEntry, sibling_id)
        assert selected is not None and sibling is not None
        assert (selected.state, selected.tx_phase) == ("active", "active")
        assert (sibling.state, sibling.tx_phase) == ("restored", "restored")

        audits = session.query(AuditEvent).filter_by(operation="restore").all()
        attacked_audits = []
        healthy_audits = []
        for event in audits:
            details = json.loads(event.details_json or "{}")
            if details.get("item_id") == attacked_id:
                attacked_audits.append((event, details))
            if details.get("item_id") == healthy_id:
                healthy_audits.append((event, details))

        assert len(attacked_audits) == 1
        assert attacked_audits[0][0].result == "failed"
        assert len(healthy_audits) == 1
        assert healthy_audits[0][0].result == "completed"
