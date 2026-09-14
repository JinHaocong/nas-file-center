from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, utcnow
from app.tasks.handlers import _reconcile_executing_item


PREVIEW_DIGEST = "b12-preview-digest"


def _setup_case(tmp_path: Path, *, state: str, tx_phase: str):
    engine, SessionLocal = create_engine_and_session(tmp_path / f"b12-{state}.db")
    init_db(engine)
    data = tmp_path / f"data-{state}"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    settings = Settings(
        config_dir=tmp_path / f"config-{state}",
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        allow_mutation=True,
        allow_delete=True,
    )

    with SessionLocal() as session:
        plan = BatchPlan(name="b12", kind="quarantine-bulk-purge", status="executing")
        session.add(plan)
        session.flush()
        entry = QuarantineEntry(
            original_path=str(data / "source.bin"),
            quarantine_path=str(trash / "source.q.bin"),
            state=state,
            tx_phase=tx_phase,
            active_attempt_generation=2,
        )
        session.add(entry)
        session.flush()
        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="quarantine_purge",
            source_path=entry.quarantine_path,
            target_path=None,
            keep_path=None,
            state="executing",
            metadata_json=json.dumps(
                {
                    "quarantine_entry_id": entry.id,
                    "preview_digest": PREVIEW_DIGEST,
                    "execution": {"phase": "intent", "source_stat": {}, "metadata_before": {}},
                }
            ),
        )
        session.add(item)
        session.commit()
        return SessionLocal, settings, int(plan.id), int(item.id), int(entry.id)


def _matching_audits(session, *, result: str, plan_id: int, item_id: int, entry_id: int, phase: str):
    matches = []
    for event in session.scalars(
        select(AuditEvent).where(
            AuditEvent.operation == "quarantine_purge",
            AuditEvent.result == result,
        )
    ):
        details = json.loads(event.details_json or "{}")
        if (
            details.get("plan_id") == plan_id
            and details.get("item_id") == item_id
            and details.get("quarantine_entry_id") == entry_id
            and details.get("preview_digest") == PREVIEW_DIGEST
            and details.get("recovery_phase") == phase
        ):
            matches.append((event, details))
    return matches


def test_post_intent_reconciliation_emits_one_idempotent_recovery_audit(tmp_path: Path) -> None:
    SessionLocal, settings, plan_id, item_id, entry_id = _setup_case(
        tmp_path,
        state="purging",
        tx_phase="purging",
    )

    for _ in range(2):
        with SessionLocal() as session:
            item = session.get(BatchPlanItem, item_id)
            assert item is not None
            item.state = "executing"
            _reconcile_executing_item(
                session,
                item,
                plan_id,
                7001,
                None,
                settings,
                utcnow(),
                worker_id="worker-b12",
                pre_reconciled=True,
            )
            assert item.state == "planned"
            assert item.reason is None
            session.commit()

    with SessionLocal() as session:
        matches = _matching_audits(
            session,
            result="recovered",
            plan_id=plan_id,
            item_id=item_id,
            entry_id=entry_id,
            phase="post_intent",
        )
        assert len(matches) == 1
        assert "purging" in matches[0][1]["reason"]


def test_unexpected_purge_reconciliation_state_emits_bound_failure_audit(tmp_path: Path) -> None:
    SessionLocal, settings, plan_id, item_id, entry_id = _setup_case(
        tmp_path,
        state="conflict",
        tx_phase="conflict",
    )

    for _ in range(2):
        with SessionLocal() as session:
            item = session.get(BatchPlanItem, item_id)
            assert item is not None
            item.state = "executing"
            _reconcile_executing_item(
                session,
                item,
                plan_id,
                7002,
                None,
                settings,
                utcnow(),
                worker_id="worker-b12",
                pre_reconciled=True,
            )
            assert item.state == "failed"
            assert item.reason == (
                "reconciliation unexpected transactional purge state: state=conflict, tx_phase=conflict"
            )
            session.commit()

    with SessionLocal() as session:
        matches = _matching_audits(
            session,
            result="failed",
            plan_id=plan_id,
            item_id=item_id,
            entry_id=entry_id,
            phase="reconciliation_failed",
        )
        assert len(matches) == 1
        assert matches[0][1]["reason"] == (
            "reconciliation unexpected transactional purge state: state=conflict, tx_phase=conflict"
        )
