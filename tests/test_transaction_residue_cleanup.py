from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import text

from app.db import create_engine_and_session, init_db
from app.models import QuarantineEntry, TaskLock, utcnow
from app.tasks.recovery import acquire_worker_ownership
from app.transaction_residue import (
    cleanup_completed_utility_move_residue,
    cleanup_empty_quarantine_tx_residue,
)


def _db(tmp_path: Path):
    db_path = tmp_path / "residue.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    assert acquire_worker_ownership(engine, SessionLocal, worker_id="cleanup-worker")
    return SessionLocal


def test_orphaned_empty_quarantine_tx_tree_is_removed(tmp_path: Path) -> None:
    SessionLocal = _db(tmp_path)
    root = tmp_path / "trash"
    attempt = root / ".tx" / "entry-41" / "attempt-3" / "purge"
    attempt.mkdir(parents=True)

    stats = cleanup_empty_quarantine_tx_residue(
        SessionLocal,
        root,
        worker_id="cleanup-worker",
    )

    assert stats["removed_entry_namespaces"] == 1
    assert not (root / ".tx").exists()


def test_active_quarantine_entry_keeps_empty_tx_tree(tmp_path: Path) -> None:
    SessionLocal = _db(tmp_path)
    root = tmp_path / "trash"
    entry_root = root / ".tx" / "entry-7"
    (entry_root / "attempt-1").mkdir(parents=True)

    with SessionLocal() as session:
        session.add(
            QuarantineEntry(
                id=7,
                original_path=str(tmp_path / "source.bin"),
                quarantine_path=str(root / "payload.q-7.bin"),
                state="active",
                tx_phase="active",
            )
        )
        session.commit()

    stats = cleanup_empty_quarantine_tx_residue(
        SessionLocal,
        root,
        worker_id="cleanup-worker",
    )

    assert stats["removed_entry_namespaces"] == 0
    assert entry_root.is_dir()


def test_orphaned_quarantine_tx_tree_with_file_is_preserved(tmp_path: Path) -> None:
    SessionLocal = _db(tmp_path)
    root = tmp_path / "trash"
    entry_root = root / ".tx" / "entry-99"
    entry_root.mkdir(parents=True)
    (entry_root / "unknown.bin").write_bytes(b"do-not-delete")

    stats = cleanup_empty_quarantine_tx_residue(
        SessionLocal,
        root,
        worker_id="cleanup-worker",
    )

    assert stats["removed_entry_namespaces"] == 0
    assert stats["skipped_namespaces"] >= 1
    assert (entry_root / "unknown.bin").read_bytes() == b"do-not-delete"


def _write_transplant_state(item_dir: Path, source: Path, target: Path, *, phase: str) -> None:
    item_dir.mkdir(parents=True)
    target.mkdir(parents=True)
    st = os.lstat(target)
    (item_dir / "state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "phase": phase,
                "source": str(source),
                "target": str(target),
                "created_dirs": {"": [int(st.st_dev), int(st.st_ino)]},
            }
        ),
        encoding="utf-8",
    )


def test_completed_utility_move_state_is_removed(tmp_path: Path) -> None:
    SessionLocal = _db(tmp_path)
    root = tmp_path / "trash"
    source = tmp_path / "source-gone"
    target = tmp_path / "target"
    item_dir = root / ".utility-move-tx" / "plan-1" / "item-1"
    _write_transplant_state(item_dir, source, target, phase="transplanted")

    stats = cleanup_completed_utility_move_residue(
        SessionLocal,
        root,
        worker_id="cleanup-worker",
    )

    assert stats["removed_transactions"] == 1
    assert not (root / ".utility-move-tx").exists()
    assert target.is_dir()


def test_incomplete_utility_move_state_is_preserved(tmp_path: Path) -> None:
    SessionLocal = _db(tmp_path)
    root = tmp_path / "trash"
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    item_dir = root / ".utility-move-tx" / "plan-2" / "item-1"
    _write_transplant_state(item_dir, source, target, phase="migrating")

    stats = cleanup_completed_utility_move_residue(
        SessionLocal,
        root,
        worker_id="cleanup-worker",
    )

    assert stats["removed_transactions"] == 0
    assert stats["skipped_transactions"] >= 1
    assert (item_dir / "state.json").is_file()
