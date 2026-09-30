from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.execution.directory_transplant import move_directory_tree_noreplace
from app.models import QuarantineEntry, TaskLock, utcnow
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
