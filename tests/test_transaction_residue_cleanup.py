from __future__ import annotations

from pathlib import Path
import json

import pytest

from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.execution.directory_transplant import move_directory_tree_noreplace
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.quarantine.transaction_residue import cleanup_terminal_transaction_residue


def _env(tmp_path: Path):
    db_path = tmp_path / "cleanup.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    quarantine_root = tmp_path / "trash"
    quarantine_root.mkdir()
    worker_id = "residue-cleanup-worker"
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow()))
        session.commit()
    return SessionLocal, quarantine_root, worker_id


def test_startup_cleanup_removes_orphaned_empty_quarantine_tx_tree(tmp_path: Path):
    SessionLocal, quarantine_root, worker_id = _env(tmp_path)
    orphan = quarantine_root / ".tx" / "entry-77"
    (orphan / "attempt-1").mkdir(parents=True)
    (orphan / "attempt-2" / "nested").mkdir(parents=True)

    stats = cleanup_terminal_transaction_residue(
        quarantine_root=quarantine_root,
        session_factory=SessionLocal,
        worker_id=worker_id,
    )

    assert stats["quarantine_tx_dirs_removed"] == 1
    assert not orphan.exists()
    assert not (quarantine_root / ".tx").exists()


def test_startup_cleanup_preserves_unknown_quarantine_tx_file(tmp_path: Path):
    SessionLocal, quarantine_root, worker_id = _env(tmp_path)
    orphan = quarantine_root / ".tx" / "entry-77" / "attempt-1"
    orphan.mkdir(parents=True)
    evidence = orphan / "unknown.bin"
    evidence.write_bytes(b"do-not-delete")

    stats = cleanup_terminal_transaction_residue(
        quarantine_root=quarantine_root,
        session_factory=SessionLocal,
        worker_id=worker_id,
    )

    assert stats["quarantine_tx_dirs_removed"] == 0
    assert evidence.read_bytes() == b"do-not-delete"


def test_startup_cleanup_removes_empty_terminal_quarantine_tx_tree(tmp_path: Path):
    SessionLocal, quarantine_root, worker_id = _env(tmp_path)
    with SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(tmp_path / "source.bin"),
            quarantine_path=str(quarantine_root / "source.q"),
            state="purged",
            tx_phase="purged",
        )
        session.add(entry)
        session.commit()
        entry_id = int(entry.id)

    tree = quarantine_root / ".tx" / f"entry-{entry_id}" / "attempt-1"
    tree.mkdir(parents=True)

    stats = cleanup_terminal_transaction_residue(
        quarantine_root=quarantine_root,
        session_factory=SessionLocal,
        worker_id=worker_id,
    )

    assert stats["quarantine_tx_dirs_removed"] == 1
    assert not tree.parent.exists()


def test_startup_cleanup_removes_orphaned_utility_move_state(tmp_path: Path):
    SessionLocal, quarantine_root, worker_id = _env(tmp_path)
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "payload.txt").write_text("payload", encoding="utf-8")

    move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine_root,
        plan_id="17",
        sequence=2,
        transaction_id="historical-complete",
    )
    state_root = quarantine_root / ".utility-move-tx"
    assert state_root.exists()

    stats = cleanup_terminal_transaction_residue(
        quarantine_root=quarantine_root,
        session_factory=SessionLocal,
        worker_id=worker_id,
    )

    assert stats["utility_move_states_removed"] == 1
    assert not state_root.exists()
    assert (target / "payload.txt").read_text(encoding="utf-8") == "payload"


def test_startup_cleanup_preserves_utility_move_state_with_unknown_sibling(tmp_path: Path):
    SessionLocal, quarantine_root, worker_id = _env(tmp_path)
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "payload.txt").write_text("payload", encoding="utf-8")

    move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine_root,
        plan_id="18",
        sequence=1,
        transaction_id="historical-with-foreign",
    )
    item_dir = next((quarantine_root / ".utility-move-tx" / "18").iterdir())
    foreign = item_dir / "unexpected.bin"
    foreign.write_bytes(b"preserve")

    stats = cleanup_terminal_transaction_residue(
        quarantine_root=quarantine_root,
        session_factory=SessionLocal,
        worker_id=worker_id,
    )

    assert stats["utility_move_states_removed"] == 0
    assert foreign.read_bytes() == b"preserve"
    assert (item_dir / "state.json").exists()


@pytest.mark.parametrize("target_state", ["deleted", "moved", "replaced"])
def test_cleanup_completed_move_after_target_changes(tmp_path: Path, target_state: str):
    """Committed transaction identity permits metadata retirement after later operations."""
    factory, root, worker = _env(tmp_path)
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    move_directory_tree_noreplace(
        source, target, quarantine_root=root, plan_id="17", sequence=1,
        transaction_id="completed-move",
    )
    with factory() as session:
        session.add(BatchPlan(id=17, name="move", kind="utility", status="completed"))
        session.flush()
        session.add(BatchPlanItem(
            plan_id=17, sequence=1, operation="move", state="completed",
            source_path=str(source), target_path=str(target),
            metadata_json=json.dumps({"execution": {
                "directory_move_transaction_id": "completed-move",
            }}),
        ))
        session.commit()
    if target_state == "moved":
        target.rename(tmp_path / "later-target")
    else:
        target.rmdir()
        if target_state == "replaced":
            target.mkdir()
            (target / "foreign.txt").write_text("keep")

    stats = cleanup_terminal_transaction_residue(
        quarantine_root=root, session_factory=factory, worker_id=worker,
    )

    assert stats["utility_move_states_removed"] == 1
    assert not (root / ".utility-move-tx").exists()
    if target_state == "moved":
        assert (tmp_path / "later-target").is_dir()
    if target_state == "replaced":
        assert (target / "foreign.txt").read_text() == "keep"


@pytest.mark.parametrize("guard", [
    "active", "incomplete", "foreign_transaction", "legacy", "missing_plan", "malformed_metadata",
    "migrating", "invalid_json", "unknown_sibling",
])
def test_cleanup_preserves_unproven_move_after_target_deleted(tmp_path: Path, guard: str):
    """Absence of a target alone must never authorize removal of recovery metadata."""
    factory, root, worker = _env(tmp_path)
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    transaction_id = None if guard == "legacy" else "completed-move"
    move_directory_tree_noreplace(
        source, target, quarantine_root=root, plan_id="17", sequence=1,
        transaction_id=transaction_id,
    )
    state_path = next(root.rglob("state.json"))
    if guard == "migrating":
        state = json.loads(state_path.read_text())
        state["phase"] = "migrating"
        state_path.write_text(json.dumps(state))
    if guard == "unknown_sibling":
        (state_path.parent / "unknown.bin").write_bytes(b"keep")
    target.rmdir()
    metadata_json = json.dumps({"execution": {
        "directory_move_transaction_id": "different" if guard == "foreign_transaction" else transaction_id,
    }})
    if guard in {"malformed_metadata", "invalid_json"}:
        metadata_json = "[]" if guard == "malformed_metadata" else "{broken"
    with factory() as session:
        if guard != "missing_plan":
            session.add(BatchPlan(id=17, name="move", kind="utility", status="completed"))
            session.flush()
            session.add(BatchPlanItem(
                plan_id=17, sequence=1, operation="move",
                state="running" if guard == "incomplete" else "completed",
                source_path=str(source), target_path=str(target),
                metadata_json=metadata_json,
            ))
        if guard == "active":
            session.add(WorkJob(kind="batch-plan-execute", status="running", state_json='{"plan_id":17}'))
        session.commit()
    stats = cleanup_terminal_transaction_residue(
        quarantine_root=root, session_factory=factory, worker_id=worker,
    )
    assert stats["utility_move_states_removed"] == 0
    assert len(list((root / ".utility-move-tx").rglob("state.json"))) == 1
    if guard == "unknown_sibling":
        assert (state_path.parent / "unknown.bin").read_bytes() == b"keep"


@pytest.mark.parametrize("lease_kept", [True, False])
def test_worker_retires_residue_created_during_job(tmp_path: Path, monkeypatch, lease_kept: bool):
    """Cleanup must run after jobs, but not after losing worker authority."""
    import threading

    from app.config import Settings
    from app import worker

    settings = Settings(
        config_dir=tmp_path / "config", quarantine_root=tmp_path / "trash",
        allow_mutation=True, allow_delete=True,
    )
    settings.config_dir.mkdir()
    settings.quarantine_root.mkdir()
    engine, factory = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    with factory() as session:
        session.add(WorkJob(kind="test-residue", status="queued"))
        session.commit()
    stop = threading.Event()
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    (source / "payload.txt").write_text("keep")

    def process_job(*args, **kwargs):
        """Leave real completed MOVE metadata after startup maintenance has run."""
        move_directory_tree_noreplace(
            source, target, quarantine_root=settings.quarantine_root,
            plan_id="17", sequence=1, transaction_id="job-move",
        )
        stop.set()
        return lease_kept

    monkeypatch.setattr(worker, "process_work_job", process_job)
    monkeypatch.setattr(worker.signal, "signal", lambda *args: None)
    worker.worker_loop(settings, stop_event=stop, poll_seconds=0.01, heartbeat_interval=0.01)

    states = list(settings.quarantine_root.rglob("state.json"))
    assert len(states) == (0 if lease_kept else 1)
    assert (target / "payload.txt").read_text() == "keep"
