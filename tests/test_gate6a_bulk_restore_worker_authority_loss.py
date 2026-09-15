from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.quarantine.reconcile import reconcile_quarantine_transaction
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler


def _service(tmp_path: Path):
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
    return app.state.service


def _make_restoring_entry(service, *, name: str) -> tuple[int, Path, Path, Path]:
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    original = data / f"{name}.txt"
    payload = f"payload-{name}".encode()

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / f"pending-{name}.txt"),
            state="restoring",
            tx_phase="restoring",
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
        public_view = trash / f"{name}.q-{entry.id}.txt"
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


def _make_plan(service, entries: list[tuple[int, Path, Path, Path]]) -> tuple[int, list[int], list[Path]]:
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="quarantine-bulk-restore",
            kind="quarantine-bulk-restore",
            status="executing",
            expected_changes=len(entries),
            metadata_json=json.dumps(
                {
                    "action": "restore",
                    "entry_ids": [entry_id for entry_id, *_ in entries],
                    "conflict_policy": "rename",
                    "preview_digest": "a" * 64,
                },
                sort_keys=True,
            ),
        )
        session.add(plan)
        session.flush()

        item_ids: list[int] = []
        targets: list[Path] = []
        for sequence, (entry_id, _anchor, public_view, original) in enumerate(entries, start=1):
            target = original.with_name(f"{original.stem}.restored-{entry_id}{original.suffix}")
            item = BatchPlanItem(
                plan_id=plan.id,
                sequence=sequence,
                operation="restore",
                source_path=str(public_view),
                target_path=str(target),
                keep_path=None,
                state="executing",
                metadata_json=json.dumps(
                    {
                        "quarantine_entry_id": entry_id,
                        "conflict_policy": "rename",
                        "preview_digest": "a" * 64,
                    },
                    sort_keys=True,
                ),
            )
            session.add(item)
            session.flush()
            item_ids.append(int(item.id))
            targets.append(target)
        session.commit()
        return int(plan.id), item_ids, targets


def _set_metadata(service, item_id: int, mode: str) -> None:
    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        if mode == "malformed":
            item.metadata_json = "{malformed-json"
        else:
            meta = json.loads(item.metadata_json or "{}")
            if mode == "missing":
                meta.pop("quarantine_entry_id", None)
            elif mode == "invalid":
                meta["quarantine_entry_id"] = "not-an-entry-id"
            else:
                raise AssertionError(mode)
            item.metadata_json = json.dumps(meta, sort_keys=True)
        session.commit()


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
        context = JobContext(service.engine, service.SessionLocal, job_id, worker_id)
        BatchPlanExecuteHandler().run(job, context, service.settings)


@pytest.mark.parametrize("mode", ["malformed", "missing", "invalid"])
def test_worker_authority_loss_fails_closed_and_terminalizes_with_truthful_audit(
    tmp_path: Path,
    monkeypatch,
    mode: str,
) -> None:
    service = _service(tmp_path)
    entry = _make_restoring_entry(service, name=f"worker-authority-{mode}")
    entry_id, _anchor, public_view, original = entry
    plan_id, item_ids, targets = _make_plan(service, [entry])
    item_id = item_ids[0]
    frozen_target = targets[0]
    _set_metadata(service, item_id, mode)

    worker_id = f"worker-authority-{mode}"
    job_id = _prepare_worker(service, plan_id, worker_id)

    from app.quarantine.capability import MutationCapability
    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    # A restart must not surface a raw metadata exception or fall back to historical X.
    _run_worker(service, job_id, worker_id)

    assert not original.exists()
    assert not frozen_target.exists()
    assert public_view.exists()

    with service.SessionLocal() as session:
        qentry = session.get(QuarantineEntry, entry_id)
        item = session.get(BatchPlanItem, item_id)
        assert qentry is not None and item is not None
        assert (qentry.state, qentry.tx_phase) == ("conflict", "conflict")
        assert qentry.last_error and "authority" in qentry.last_error.lower()
        assert item.state == "failed"
        assert item.reason and "authority" in item.reason.lower()

        audits = session.query(AuditEvent).filter_by(operation="restore").all()
        matching = []
        for event in audits:
            details = json.loads(event.details_json or "{}")
            if details.get("plan_id") == plan_id and details.get("item_id") == item_id:
                matching.append((event, details))
        assert len(matching) == 1
        event, details = matching[0]
        assert event.result == "failed"
        assert details["quarantine_entry_id"] == entry_id
        assert details["target"] == str(frozen_target)
        assert details["conflict_policy"] == "rename"
        assert "authority" in str(details["reason"]).lower()


def test_unreadable_gate6a_item_does_not_poison_unrelated_healthy_restore_recovery(tmp_path: Path) -> None:
    service = _service(tmp_path)
    damaged = _make_restoring_entry(service, name="damaged-binding")
    healthy = _make_restoring_entry(service, name="healthy-binding")
    plan_id, item_ids, targets = _make_plan(service, [damaged, healthy])
    _set_metadata(service, item_ids[0], "malformed")

    worker_id = "worker-scope-unreadable-binding"
    _prepare_worker(service, plan_id, worker_id)

    healthy_id, healthy_anchor, healthy_public, healthy_original = healthy
    healthy_target = targets[1]
    reconcile_quarantine_transaction(
        service.SessionLocal,
        healthy_id,
        worker_id=worker_id,
        quarantine_root=service.settings.quarantine_root,
        allowed_roots=service.settings.allowed_roots,
    )

    assert not healthy_original.exists()
    assert healthy_target.exists()
    assert healthy_target.read_bytes() == healthy_anchor.read_bytes()
    assert not healthy_public.exists()
    with service.SessionLocal() as session:
        qentry = session.get(QuarantineEntry, healthy_id)
        assert qentry is not None
        assert (qentry.state, qentry.tx_phase) == ("restored", "restored")
