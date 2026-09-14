from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    QuarantineEntry,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler, _reconcile_executing_item


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


def _active_entry(client: TestClient, label: str) -> tuple[int, Path, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = f"gate6a-authority-regression-{label}".encode()

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / f"{label}.bin"),
            quarantine_path=str(trash / f"pending-{label}.bin"),
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
        entry_id = int(entry.id)

        attempt = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured_source = attempt / "captured_source"
        public_view = trash / f"{label}.q-{entry_id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured_source)
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
        return entry_id, anchor, captured_source, public_view


def _generate_purge_plan(client: TestClient, entry_ids: list[int]) -> tuple[int, str]:
    service = client.app.state.service
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": entry_ids},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    digest = str(preview.json()["preview_digest"])
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": entry_ids,
            "confirmation": "DELETE",
            "expected_preview_digest": digest,
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    return plan_id, digest


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


def _assert_zeroized(paths: tuple[Path, Path, Path], expected_identity: tuple[int, int]) -> None:
    for path in paths:
        st = path.stat(follow_symlinks=False)
        assert st.st_size == 0
        assert (st.st_dev, st.st_ino) == expected_identity


def test_bulk_purge_source_replacement_is_item_local_failure_and_batch_continues(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    first = _active_entry(client, "replace-first")
    middle = _active_entry(client, "replace-middle")
    third = _active_entry(client, "replace-third")
    first_st = first[1].stat(follow_symlinks=False)
    middle_st = middle[1].stat(follow_symlinks=False)
    third_st = third[1].stat(follow_symlinks=False)
    middle_payload = middle[1].read_bytes()
    entry_ids = [first[0], middle[0], third[0]]

    plan_id, preview_digest = _generate_purge_plan(client, entry_ids)

    # Frozen source pathname replacement is intentionally handled by the purge
    # Capture -> Qualification protocol. It must fail only this selected item,
    # preserve the foreign replacement, and allow later selected items to run.
    os.unlink(middle[3])
    foreign_payload = b"foreign-replacement-must-survive"
    middle[3].write_bytes(foreign_payload)
    foreign_st = middle[3].stat(follow_symlinks=False)
    assert (foreign_st.st_dev, foreign_st.st_ino) != (middle_st.st_dev, middle_st.st_ino)

    worker_id = "worker-gate6a-source-replacement-partial"
    job_id = _prepare_worker(service, plan_id, worker_id)
    _run_worker(service, job_id, worker_id)

    _assert_zeroized(first[1:], (first_st.st_dev, first_st.st_ino))
    _assert_zeroized(third[1:], (third_st.st_dev, third_st.st_ino))
    assert middle[1].read_bytes() == middle_payload
    assert middle[2].read_bytes() == middle_payload
    assert middle[3].read_bytes() == foreign_payload

    with service.SessionLocal() as session:
        rows = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert [row.state for row in rows] == ["completed", "failed", "completed"]
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None and plan.status == "partial"

        first_entry = session.get(QuarantineEntry, first[0])
        middle_entry = session.get(QuarantineEntry, middle[0])
        third_entry = session.get(QuarantineEntry, third[0])
        assert first_entry is not None and first_entry.state == "purged"
        assert middle_entry is not None and middle_entry.state == "purging"
        assert third_entry is not None and third_entry.state == "purged"

        audits = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.operation == "quarantine_purge")
                .order_by(AuditEvent.id)
            )
        )
        selected = []
        for event in audits:
            details = json.loads(event.details_json or "{}")
            if details.get("quarantine_entry_id") in entry_ids and details.get("role") is None:
                selected.append((details.get("quarantine_entry_id"), event.result, details))
        assert [(entry_id, result) for entry_id, result, _ in selected] == [
            (first[0], "completed"),
            (middle[0], "failed"),
            (third[0], "completed"),
        ]
        middle_details = next(details for entry_id, _, details in selected if entry_id == middle[0])
        assert middle_details["preview_digest"] == preview_digest


def test_bulk_purge_execute_uses_frozen_manifest_not_mutable_draft_manifest(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, anchor, captured_source, public_view = _active_entry(client, "frozen-execute")
    frozen_st = anchor.stat(follow_symlinks=False)
    plan_id, _ = _generate_purge_plan(client, [entry_id])

    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        metadata = json.loads(item.metadata_json or "{}")
        frozen_manifest = metadata.get("frozen_purge_topology_manifest")
        assert isinstance(frozen_manifest, dict)
        assert len(frozen_manifest.get("aliases") or []) == 3
        metadata["purge_topology_manifest"] = {
            "selected_entry_id": entry_id,
            "aliases": [],
            "historical_conflict_entry_ids": [],
            "blocking_owner_entry_ids": [],
            "blockers": [],
        }
        item.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        session.commit()

    worker_id = "worker-gate6a-frozen-manifest-execute"
    job_id = _prepare_worker(service, plan_id, worker_id)
    _run_worker(service, job_id, worker_id)

    _assert_zeroized(
        (anchor, captured_source, public_view),
        (frozen_st.st_dev, frozen_st.st_ino),
    )
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert entry is not None and entry.state == "purged" and entry.tx_phase == "purged"
        assert item is not None and item.state == "completed"


def test_terminal_purge_recovery_audits_from_frozen_manifest_not_mutable_draft(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    selected_id, anchor, captured_source, public_view = _active_entry(client, "frozen-recovery")
    selected_st = anchor.stat(follow_symlinks=False)
    digest = hashlib.sha256(anchor.read_bytes()).hexdigest()
    trash = Path(service.settings.quarantine_root)
    data = Path(service.settings.data_mount)

    with service.SessionLocal() as session:
        historical = QuarantineEntry(
            original_path=str(data / "frozen-recovery-history.bin"),
            quarantine_path=str(trash / "frozen-recovery-history.q.bin"),
            state="conflict",
            tx_phase="conflict",
            authoritative_anchor_path=None,
            active_attempt_generation=1,
            size=selected_st.st_size,
            content_hash=digest,
            mtime_ns=selected_st.st_mtime_ns,
            device=selected_st.st_dev,
            inode=selected_st.st_ino,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(historical)
        session.flush()
        historical_id = int(historical.id)
        historical_attempt = trash / ".tx" / f"entry-{historical_id}" / "attempt-1"
        historical_attempt.mkdir(parents=True)
        historical_anchor = historical_attempt / "anchor"
        os.link(anchor, historical_anchor)

        selected = session.get(QuarantineEntry, selected_id)
        assert selected is not None
        selected.state = "purged"
        selected.tx_phase = "purged"
        selected.purged_at = utcnow()

        plan = BatchPlan(
            name="quarantine-bulk-purge",
            kind="quarantine-bulk-purge",
            status="executing",
            expected_changes=1,
            expected_reclaim_bytes=0,
            metadata_json=json.dumps({"action": "purge", "entry_ids": [selected_id]}),
        )
        session.add(plan)
        session.flush()
        preview_digest = "a" * 64
        frozen_manifest = {
            "selected_entry_id": selected_id,
            "aliases": [
                {
                    "role": "historical_conflict_candidate",
                    "owner_entry_id": historical_id,
                    "path": str(historical_anchor),
                }
            ],
            "historical_conflict_entry_ids": [historical_id],
            "blocking_owner_entry_ids": [],
            "blockers": [],
        }
        draft_manifest = {
            "selected_entry_id": selected_id,
            "aliases": [],
            "historical_conflict_entry_ids": [],
            "blocking_owner_entry_ids": [],
            "blockers": [],
        }
        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="quarantine_purge",
            source_path=str(public_view),
            target_path=None,
            keep_path=None,
            expected_size=selected_st.st_size,
            expected_mtime_ns=selected_st.st_mtime_ns,
            expected_device=selected_st.st_dev,
            expected_inode=selected_st.st_ino,
            expected_hash=digest,
            state="executing",
            metadata_json=json.dumps(
                {
                    "quarantine_entry_id": selected_id,
                    "preview_digest": preview_digest,
                    "purge_topology_manifest": draft_manifest,
                    "frozen_purge_topology_manifest": frozen_manifest,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        session.add(item)
        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": int(plan.id)}),
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(job)
        session.flush()
        plan_id = int(plan.id)
        item_id = int(item.id)
        job_id = int(job.id)
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        _reconcile_executing_item(
            session,
            item,
            plan_id,
            job_id,
            None,
            service.settings,
            utcnow(),
            pre_reconciled=True,
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None and item.state == "completed"
        audits = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.operation == "quarantine_purge", AuditEvent.result == "completed")
                .order_by(AuditEvent.id)
            )
        )
        historical_audits = []
        for event in audits:
            details = json.loads(event.details_json or "{}")
            if details.get("role") == "historical_conflict_candidate":
                historical_audits.append((event, details))
        assert len(historical_audits) == 1
        event, details = historical_audits[0]
        assert event.path == str(historical_anchor)
        assert details["quarantine_entry_id"] == selected_id
        assert details["linked_quarantine_entry_id"] == historical_id
        assert details["preview_digest"] == preview_digest
