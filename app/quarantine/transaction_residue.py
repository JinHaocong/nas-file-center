from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import sessionmaker

from app.execution.directory_transplant import (
    _state_path,
    cleanup_directory_transplant_state,
    directory_transplant_reconciles_completed,
)
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, WorkJob
from app.tasks.recovery import assert_active_worker_lease


_ENTRY_DIR_RE = re.compile(r"^entry-(\d+)$")
_ITEM_DIR_RE = re.compile(r"^item-(\d+)(?:-.+)?$")
_ACTIVE_EXECUTION_STATUSES = ("queued", "running", "paused", "cancel_requested")
_TERMINAL_EMPTY_TX_STATES = {"purged"}


def _is_plain_directory(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _remove_directory_only_tree(root: Path) -> bool:
    """Remove a tree only when it contains directories and nothing else."""
    if not _is_plain_directory(root):
        return False

    directories: list[Path] = []
    try:
        for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            if not _is_plain_directory(current_path) or filenames:
                return False
            for dirname in dirnames:
                if not _is_plain_directory(current_path / dirname):
                    return False
            directories.append(current_path)
    except OSError:
        return False

    for directory in reversed(directories):
        try:
            os.rmdir(directory)
        except FileNotFoundError:
            continue
        except OSError:
            return False
    return not os.path.lexists(root)


def _linked_plan_id_expr():
    return func.cast(func.json_extract(WorkJob.state_json, "$.plan_id"), Integer)


def _has_active_execution_job(session, plan_id: int) -> bool:
    return (
        session.scalars(
            select(WorkJob.id)
            .where(
                WorkJob.kind == "batch-plan-execute",
                WorkJob.status.in_(_ACTIVE_EXECUTION_STATUSES),
                _linked_plan_id_expr() == int(plan_id),
            )
            .limit(1)
        ).first()
        is not None
    )


def _cleanup_quarantine_tx(
    quarantine_root: Path,
    session_factory: sessionmaker,
    worker_id: str,
) -> int:
    tx_root = quarantine_root / ".tx"
    if not _is_plain_directory(tx_root):
        return 0

    removed = 0
    try:
        children = sorted(tx_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return 0

    for child in children:
        match = _ENTRY_DIR_RE.fullmatch(child.name)
        if match is None or not _is_plain_directory(child):
            continue
        entry_id = int(match.group(1))

        with session_factory() as session:
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            if entry is not None and entry.state not in _TERMINAL_EMPTY_TX_STATES:
                continue

        if _remove_directory_only_tree(child):
            removed += 1

    try:
        tx_root.rmdir()
    except OSError:
        pass
    return removed


def _read_state_json(state_path: Path) -> dict | None:
    try:
        st = os.lstat(state_path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cleanup_utility_move_tx(
    quarantine_root: Path,
    session_factory: sessionmaker,
    worker_id: str,
) -> int:
    root = quarantine_root / ".utility-move-tx"
    if not _is_plain_directory(root):
        return 0

    removed = 0
    try:
        plan_dirs = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return 0

    for plan_dir in plan_dirs:
        if not plan_dir.name.isdigit() or not _is_plain_directory(plan_dir):
            continue
        plan_id = int(plan_dir.name)
        try:
            item_dirs = sorted(plan_dir.iterdir(), key=lambda path: path.name)
        except OSError:
            continue

        for item_dir in item_dirs:
            match = _ITEM_DIR_RE.fullmatch(item_dir.name)
            if match is None or not _is_plain_directory(item_dir):
                continue
            sequence = int(match.group(1))
            try:
                entries = list(item_dir.iterdir())
            except OSError:
                continue
            if len(entries) != 1 or entries[0].name != "state.json":
                continue

            state_path = entries[0]
            state = _read_state_json(state_path)
            if state is None:
                continue
            transaction_id = state.get("transaction_id")
            if transaction_id is not None and not isinstance(transaction_id, str):
                continue
            expected_state_path = _state_path(
                quarantine_root,
                str(plan_id),
                sequence,
                transaction_id,
            )
            if expected_state_path != state_path:
                continue

            source = state.get("source")
            target = state.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                continue

            with session_factory() as session:
                assert_active_worker_lease(session, worker_id)
                if _has_active_execution_job(session, plan_id):
                    continue
                plan = session.get(BatchPlan, plan_id)
                if plan is not None:
                    item = session.scalars(
                        select(BatchPlanItem).where(
                            BatchPlanItem.plan_id == plan_id,
                            BatchPlanItem.sequence == sequence,
                        )
                    ).first()
                    if (
                        item is None
                        or item.operation != "move"
                        or item.state != "completed"
                        or item.source_path != source
                        or item.target_path != target
                    ):
                        continue

            # A missing DB plan is not enough authority to delete recovery
            # metadata. Always require the transaction state plus current
            # filesystem identity to prove the MOVE reached its completed
            # namespace state.
            try:
                completed = directory_transplant_reconciles_completed(
                    quarantine_root,
                    plan_id,
                    sequence,
                    source=Path(source),
                    target=Path(target),
                    transaction_id=transaction_id,
                )
            except Exception:
                completed = False
            if not completed:
                continue

            try:
                cleanup_directory_transplant_state(
                    quarantine_root,
                    plan_id,
                    sequence,
                    transaction_id=transaction_id,
                )
            except OSError:
                continue
            if not state_path.exists():
                removed += 1

    try:
        root.rmdir()
    except OSError:
        pass
    return removed


def cleanup_terminal_transaction_residue(
    *,
    quarantine_root: Path | str,
    session_factory: sessionmaker,
    worker_id: str,
) -> dict[str, int]:
    """Retire terminal NFC transaction metadata without touching user payloads.

    The cleanup is deliberately conservative:
    - .tx: only directory-only trees whose DB owner is missing or terminal.
    - .utility-move-tx: only exact NFC state.json leaves with no unknown siblings;
      active plans are never touched, and live plans require a completed MOVE.
    - unknown files, symlinks, malformed metadata and active transactions remain.
    """
    root = Path(quarantine_root)
    with session_factory() as session:
        assert_active_worker_lease(session, worker_id)

    return {
        "quarantine_tx_dirs_removed": _cleanup_quarantine_tx(
            root,
            session_factory,
            worker_id,
        ),
        "utility_move_states_removed": _cleanup_utility_move_tx(
            root,
            session_factory,
            worker_id,
        ),
    }
