from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.execution.directory_transplant import (
    cleanup_directory_transplant_state,
    directory_transplant_reconciles_completed,
    move_directory_tree_noreplace,
)


def _write_legacy_stale_state(
    quarantine_root: Path,
    *,
    plan_id: str,
    sequence: int,
    source: Path,
    target: Path,
) -> Path:
    state_path = (
        quarantine_root
        / ".utility-move-tx"
        / plan_id
        / f"item-{sequence}"
        / "state.json"
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "token": "historical-plan-instance",
                "phase": "initializing",
                "source": str(source),
                "target": str(target),
                "source_device": 1,
                "source_inode": 1,
                "created_dirs": {},
                "published_symlinks": {},
            }
        ),
        encoding="utf-8",
    )
    return state_path


def test_new_transaction_namespace_ignores_reused_plan_id_legacy_state(tmp_path: Path):
    root = tmp_path / "root"
    quarantine = tmp_path / "quarantine"
    source = root / "B" / "C"
    target = root / "C"
    source.mkdir(parents=True)
    quarantine.mkdir()
    (source / "payload.txt").write_text("payload", encoding="utf-8")

    stale_state = _write_legacy_stale_state(
        quarantine,
        plan_id="1",
        sequence=1,
        source=source,
        target=target,
    )

    # A database rebuild can legitimately reuse BatchPlan #1 while the NAS
    # still contains historical NFC-owned transaction metadata. The fresh
    # transaction identity must keep that history from becoming authority over
    # this frozen item.
    move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine,
        plan_id="1",
        sequence=1,
        transaction_id="current-plan-instance",
    )

    assert stale_state.exists()
    assert not source.exists()
    assert (target / "payload.txt").read_text(encoding="utf-8") == "payload"

    current_state = (
        quarantine
        / ".utility-move-tx"
        / "1"
        / "item-1-current-plan-instance"
        / "state.json"
    )
    assert current_state.exists()
    payload = json.loads(current_state.read_text(encoding="utf-8"))
    assert payload["transaction_id"] == "current-plan-instance"
    assert payload["phase"] == "transplanted"

    cleanup_directory_transplant_state(
        quarantine,
        "1",
        1,
        transaction_id="current-plan-instance",
    )
    assert not current_state.exists()
    assert stale_state.exists()


def test_same_transaction_id_reconciles_completed_directory_move(tmp_path: Path):
    root = tmp_path / "root"
    quarantine = tmp_path / "quarantine"
    source = root / "B" / "C"
    target = root / "C"
    source.mkdir(parents=True)
    quarantine.mkdir()
    (source / "payload.txt").write_text("payload", encoding="utf-8")

    transaction_id = "worker-restart-stable"
    move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine,
        plan_id="7",
        sequence=3,
        transaction_id=transaction_id,
    )

    assert directory_transplant_reconciles_completed(
        quarantine,
        "7",
        3,
        source=source,
        target=target,
        transaction_id=transaction_id,
    )

    # Simulate worker retry after the filesystem move completed but before the
    # database item was finalized. This must be idempotent and must not produce
    # an EEXIST mismatch.
    move_directory_tree_noreplace(
        source,
        target,
        quarantine_root=quarantine,
        plan_id="7",
        sequence=3,
        transaction_id=transaction_id,
    )
    assert (target / "payload.txt").read_text(encoding="utf-8") == "payload"

    with pytest.raises(FileNotFoundError):
        move_directory_tree_noreplace(
            source,
            target,
            quarantine_root=quarantine,
            plan_id="7",
            sequence=3,
            transaction_id="different-plan-instance",
        )
