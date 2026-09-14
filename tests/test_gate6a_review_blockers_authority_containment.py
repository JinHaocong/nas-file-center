from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
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


def _generate_restore_plan(client: TestClient, entry_ids: list[int], *, conflict_policy: str = "skip") -> int:
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": entry_ids, "conflict_policy": conflict_policy},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": entry_ids,
            "conflict_policy": conflict_policy,
            "expected_preview_digest": preview_body["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    return int(generated.json()["id"])


def test_forged_skip_marker_after_freeze_cannot_reclassify_new_foreign_occupant(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, _anchor, _public_view, original = _active_entry(client, "forged-skip.txt", b"payload")

    plan_id = _generate_restore_plan(client, [entry_id], conflict_policy="skip")
    assert service.freeze_plan(plan_id).status == "frozen"

    # Preview and Freeze both saw an empty destination.  Corrupt metadata after Freeze to
    # forge the marker, then introduce a foreign occupant.  Validate must fail closed;
    # the occupant is post-Freeze and must never be reinterpreted as a pre-existing skip.
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        metadata = json.loads(item.metadata_json or "{}")
        assert metadata.get("skip_preexisting_target") is not True
        metadata["skip_preexisting_target"] = True
        item.metadata_json = json.dumps(metadata, sort_keys=True)
        session.commit()

    foreign_payload = b"foreign-after-freeze"
    original.write_bytes(foreign_payload)
    validation = service.validate_plan(plan_id)

    assert validation["status"] != "ready"
    assert original.read_bytes() == foreign_payload
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "stale"
        assert item.reason and (
            "authority" in item.reason.lower()
            or "occupied" in item.reason.lower()
            or "binding" in item.reason.lower()
        )


def test_frozen_restore_rejects_source_path_cross_binding_even_with_skip_marker(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    first_id, _first_anchor, _first_public, first_original = _active_entry(client, "first.txt", b"first")
    _second_id, _second_anchor, second_public, _second_original = _active_entry(client, "second.txt", b"second")

    # Make the honest Preview produce a pre-existing skip authority for the first entry.
    first_original.write_bytes(b"foreign-preexisting")
    plan_id = _generate_restore_plan(client, [first_id], conflict_policy="skip")
    assert service.freeze_plan(plan_id).status == "frozen"

    # Cross-bind the frozen item source to another active qentry.  The qid remains the
    # first entry.  Lifecycle validation must prove source_path == qentry.quarantine_path.
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        metadata = json.loads(item.metadata_json or "{}")
        assert metadata.get("skip_preexisting_target") is True
        item.source_path = str(second_public)
        session.commit()

    validation = service.validate_plan(plan_id)
    assert validation["status"] != "ready"
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "stale"
        assert item.reason and ("source" in item.reason.lower() or "owner" in item.reason.lower() or "binding" in item.reason.lower())


def test_planned_malformed_restore_metadata_is_contained_and_healthy_sibling_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    bad = _active_entry(client, "bad-planned.txt", b"bad")
    good = _active_entry(client, "good-planned.txt", b"good")
    bad_id, _bad_anchor, bad_public, bad_original = bad
    good_id, good_anchor, good_public, good_original = good

    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="quarantine-bulk-restore",
            kind="quarantine-bulk-restore",
            status="ready",
            expected_changes=2,
            metadata_json=json.dumps(
                {
                    "action": "restore",
                    "entry_ids": [bad_id, good_id],
                    "conflict_policy": "rename",
                    "preview_digest": "b" * 64,
                },
                sort_keys=True,
            ),
        )
        session.add(plan)
        session.flush()

        for sequence, (entry_id, _anchor, public_view, original) in enumerate((bad, good), start=1):
            qentry = session.get(QuarantineEntry, entry_id)
            assert qentry is not None
            item = BatchPlanItem(
                plan_id=plan.id,
                sequence=sequence,
                operation="restore",
                source_path=str(public_view),
                target_path=str(original),
                keep_path=None,
                expected_size=qentry.size,
                expected_mtime_ns=qentry.mtime_ns,
                expected_device=qentry.device,
                expected_inode=qentry.inode,
                expected_hash=qentry.content_hash,
                state="planned",
                metadata_json=(
                    "{malformed-json"
                    if entry_id == bad_id
                    else json.dumps(
                        {
                            "quarantine_entry_id": entry_id,
                            "conflict_policy": "rename",
                            "preview_digest": "b" * 64,
                        },
                        sort_keys=True,
                    )
                ),
            )
            session.add(item)
        session.commit()
        plan_id = int(plan.id)

    worker_id = "worker-gate6a-planned-malformed-containment"
    job_id = _prepare_worker(service, plan_id, worker_id)

    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    # A malformed planned item must be terminalized per-item; it must not escape as a
    # JSONDecodeError and must not prevent the healthy sibling from executing.
    _run_worker(service, job_id, worker_id)

    assert not bad_original.exists()
    assert bad_public.exists()
    assert good_original.exists()
    assert good_original.read_bytes() == good_anchor.read_bytes()
    assert not good_public.exists()

    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).order_by(BatchPlanItem.sequence).all()
        assert [item.state for item in items] == ["failed", "completed"]
        assert items[0].reason and ("metadata" in items[0].reason.lower() or "authority" in items[0].reason.lower())

        bad_entry = session.get(QuarantineEntry, bad_id)
        good_entry = session.get(QuarantineEntry, good_id)
        assert bad_entry is not None and good_entry is not None
        assert (bad_entry.state, bad_entry.tx_phase) == ("active", "active")
        assert (good_entry.state, good_entry.tx_phase) == ("restored", "restored")

        audits = session.query(AuditEvent).filter_by(operation="restore").all()
        by_item: dict[int, list[AuditEvent]] = {}
        for event in audits:
            details = json.loads(event.details_json or "{}")
            item_id = details.get("item_id")
            if isinstance(item_id, int):
                by_item.setdefault(item_id, []).append(event)
        assert len(by_item.get(items[0].id, [])) == 1
        assert len(by_item.get(items[1].id, [])) == 1
        assert by_item[items[0].id][0].result == "failed"
        assert by_item[items[1].id][0].result == "completed"
