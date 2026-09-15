from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import (
    AuditEvent,
    BatchPlanItem,
    IndexedPath,
    IndexRoot,
    QuarantineEntry,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.quarantine.unlink_purge import execute_journaled_unlink_purge
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler


OPERATION = "quarantine_unlink_purge"
SEMANTICS = "unlink_v1"


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


def _active_entry(client: TestClient):
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    indexed = data / "indexed"
    indexed.mkdir()
    payload = b"gate6a2-terminal-audit"
    external = indexed / "preview-survivor.bin"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "selected.bin"),
            quarantine_path=str(trash / "pending.bin"),
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
        public_view = trash / f"selected.q-{entry.id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        os.link(anchor, external)
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.size = st.st_size
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.mtime_ns = st.st_mtime_ns
        entry.device = st.st_dev
        entry.inode = st.st_ino

        root = IndexRoot(root=str(indexed))
        session.add(root)
        session.add(
            IndexedPath(
                root_key=str(indexed),
                absolute_path=str(external),
                relative_path=external.name,
                basename=external.name,
                stem=external.stem,
                suffix=external.suffix,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
                is_dir=False,
                scan_generation="gate6a2-terminal-audit",
            )
        )
        session.commit()
        entry_id = int(entry.id)

    return entry_id, indexed, anchor, captured, public_view, external, payload


def _draft_freeze_validate(client: TestClient, entry_id: int):
    service = client.app.state.service
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    digest = preview.json()["preview_digest"]

    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "confirmation": "DELETE",
            "expected_preview_digest": digest,
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        metadata = json.loads(item.metadata_json or "{}")
        assert item.operation == OPERATION
        assert metadata["purge_semantics"] == SEMANTICS
        assert metadata["preview_digest"] == digest
        return plan_id, int(item.id), digest, metadata["unlink_manifest"]


def _claim_worker_and_job(service, plan_id: int, worker_id: str) -> int:
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


def _claim_worker_only(service, worker_id: str) -> None:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()
        session.commit()


def _run_worker(service, job_id: int, worker_id: str) -> None:
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(service.engine, service.SessionLocal, job_id, worker_id)
        BatchPlanExecuteHandler().run(job, context, service.settings)


def _terminal_events(service, plan_id: int, item_id: int):
    matched = []
    with service.SessionLocal() as session:
        events = list(
            session.query(AuditEvent)
            .filter(AuditEvent.operation == OPERATION, AuditEvent.result == "completed")
            .all()
        )
        for event in events:
            details = json.loads(event.details_json or "{}")
            if details.get("plan_id") == plan_id and details.get("item_id") == item_id:
                matched.append((event, details))
    return matched


def _add_late_indexed_hardlink(service, indexed: Path, source: Path, entry_id: int) -> Path:
    late = indexed / "late-survivor.bin"
    os.link(source, late)
    st = late.stat(follow_symlinks=False)
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert (st.st_dev, st.st_ino) == (entry.device, entry.inode)
        session.add(
            IndexedPath(
                root_key=str(indexed),
                absolute_path=str(late),
                relative_path=late.name,
                basename=late.name,
                stem=late.stem,
                suffix=late.suffix,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
                is_dir=False,
                scan_generation="gate6a2-terminal-audit-late",
            )
        )
        session.commit()
    return late


def _assert_bound_terminal_audit(
    service,
    *,
    plan_id: int,
    item_id: int,
    entry_id: int,
    preview_digest: str,
    expected_survivors: list[Path],
) -> None:
    matched = _terminal_events(service, plan_id, item_id)
    assert len(matched) == 1
    _event, details = matched[0]
    assert details["plan_id"] == plan_id
    assert details["item_id"] == item_id
    assert details["quarantine_entry_id"] == entry_id
    assert details["preview_digest"] == preview_digest
    assert details["purge_semantics"] == SEMANTICS
    assert details["terminal_result"] == "purged"
    assert details["survivor_scope"] == "indexed_roots_only"
    assert details["survivor_status"] == "verified_found"
    assert details["hardlink_survivor_paths"] == sorted(str(p) for p in expected_survivors)

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        metadata = json.loads(item.metadata_json or "{}")
        advisory = metadata["terminal_advisory"]
        assert advisory["scope"] == "indexed_roots_only"
        assert advisory["status"] == "verified_found"
        assert advisory["hardlink_survivors"] == sorted(str(p) for p in expected_survivors)


def test_bulk_terminal_audit_uses_fresh_post_unlink_advisory_and_is_exactly_once(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, indexed, anchor, captured, public_view, external, payload = _active_entry(client)
    plan_id, item_id, digest, _manifest = _draft_freeze_validate(client, entry_id)

    # Advisory-only drift after Preview is intentionally not digest-bound. The
    # terminal audit must discover this new external hard link after unlink.
    late = _add_late_indexed_hardlink(service, indexed, external, entry_id)

    worker_id = "worker-gate6a2-terminal-audit"
    job_id = _claim_worker_and_job(service, plan_id, worker_id)
    _run_worker(service, job_id, worker_id)

    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()
    assert external.read_bytes() == payload
    assert late.read_bytes() == payload
    _assert_bound_terminal_audit(
        service,
        plan_id=plan_id,
        item_id=item_id,
        entry_id=entry_id,
        preview_digest=digest,
        expected_survivors=[external, late],
    )

    # Re-running an already completed plan must not create a second terminal
    # success event for the same frozen plan item.
    retry_worker = "worker-gate6a2-terminal-audit-retry"
    retry_job = _claim_worker_and_job(service, plan_id, retry_worker)
    _run_worker(service, retry_job, retry_worker)
    assert len(_terminal_events(service, plan_id, item_id)) == 1


def test_successor_worker_after_core_terminal_writes_one_bound_success_audit(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, _indexed, anchor, captured, public_view, external, payload = _active_entry(client)
    plan_id, item_id, digest, manifest = _draft_freeze_validate(client, entry_id)

    # Simulate a crash after the durable unlink core reached terminal purged but
    # before BatchPlan Phase-3 persisted its item result/audit.
    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        item.state = "executing"
        item.reason = None
        session.commit()

    old_worker = "worker-gate6a2-terminal-before-phase3"
    _claim_worker_only(service, old_worker)
    result = execute_journaled_unlink_purge(
        service.SessionLocal,
        entry_id=entry_id,
        quarantine_root=service.settings.quarantine_root,
        frozen_manifest=manifest,
        worker_id=old_worker,
    )
    assert result["already_terminal"] is False
    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()
    assert external.read_bytes() == payload
    assert _terminal_events(service, plan_id, item_id) == []

    successor = "worker-gate6a2-terminal-after-crash"
    successor_job = _claim_worker_and_job(service, plan_id, successor)
    _run_worker(service, successor_job, successor)

    _assert_bound_terminal_audit(
        service,
        plan_id=plan_id,
        item_id=item_id,
        entry_id=entry_id,
        preview_digest=digest,
        expected_survivors=[external],
    )

    second_retry = "worker-gate6a2-terminal-second-retry"
    second_job = _claim_worker_and_job(service, plan_id, second_retry)
    _run_worker(service, second_job, second_retry)
    assert len(_terminal_events(service, plan_id, item_id)) == 1
