"""Bounded archival of detached operations and proven terminal unlink epochs."""

from collections.abc import Callable, Iterator
from datetime import datetime
import json
from pathlib import Path

from sqlalchemy import and_, case, delete, func, insert, inspect, or_, select, text
from sqlalchemy.orm import Session

from app.maintenance.archive_files import write_history_archive
from app.maintenance.database import MaintenanceConflict
from app.models import OperationJournal as Journal
from app.maintenance.task_journal_cleanup import ORDINARY_OPERATIONS
from app.models import PendingTaskJournalDeletion, QuarantineEntry, QuarantineUnlinkEvidence
from app.quarantine.unlink_purge import (
    OPERATION_ID, SEMANTICS_VERSION, UnlinkJournalRecord, _CANONICAL_ROLES,
    _METADATA_ONLY_ORPHAN_MODE, _journal_epoch_terminal_purged,
    _positive_generation, pack_unlink_evidence,
)


_BATCH_SIZE = 1500


def _eligible(cutoff: datetime):
    # Legacy tables use INTEGER PRIMARY KEY without AUTOINCREMENT. Keeping the
    # highest live row prevents SQLite from reusing any archived journal ID.
    watermark = select(func.max(Journal.id)).correlate(None).scalar_subquery()
    return and_(
        Journal.id < watermark, Journal.created_at < cutoff,
        Journal.plan_id.is_(None), Journal.plan_item_id.is_(None), Journal.task_id.is_(None),
    )


def _object(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _complete_intent(row: UnlinkJournalRecord, intent: dict, item: dict, entry_id: int, generation: int) -> bool:
    after = _object(row.after_json)
    fields = ("object_type", "device", "inode", "size", "mtime_ns", "content_hash")
    if (
        intent.get("phase") != "unlink_intent"
        or intent.get("frozen_identity") != {key: item.get(key) for key in fields}
        or after.get("phase") != "unlinked"
        or after.get("entry_id") != entry_id
        or after.get("purge_semantics") != SEMANTICS_VERSION
    ):
        return False
    return all(
        checkpoint.get("active_attempt_generation", generation) == generation
        and checkpoint.get("role") == item["role"]
        and checkpoint.get("path") == item.get("path")
        for checkpoint in (intent, after)
    )


def _complete_epoch(records: list[tuple[UnlinkJournalRecord, dict]], entry_id: int) -> bool:
    authority = records[0][1]
    manifest = authority.get("manifest")
    if not isinstance(manifest, dict):
        return False
    generation = _positive_generation(manifest.get("active_attempt_generation"))
    if (
        generation is None
        or authority.get("active_attempt_generation", generation) != generation
        or manifest.get("selected_entry_id") != entry_id
        or manifest.get("purge_semantics") != SEMANTICS_VERSION
        or manifest.get("blockers") != []
    ):
        return False

    frozen = manifest.get("owned_paths")
    intents = records[1:-1]
    if not isinstance(frozen, list) or len(frozen) != len(intents):
        return False
    roles = tuple(item.get("role") for item in frozen if isinstance(item, dict))
    if len(roles) != len(frozen):
        return False
    if manifest.get("metadata_only_orphan") is True:
        absence = manifest.get("orphan_absence")
        if roles or not isinstance(absence, dict) or absence.get("mode") != _METADATA_ONLY_ORPHAN_MODE:
            return False
    elif roles not in (_CANONICAL_ROLES, ("public_view",)):
        return False
    if not all(_complete_intent(row, intent, item, entry_id, generation) for (row, intent), item in zip(intents, frozen)):
        return False
    return _journal_epoch_terminal_purged(records, entry_id=entry_id, attempt_generation=generation)


def _completed_groups(
    session: Session, cutoff: datetime, *, candidates: dict[int, int] | None = None,
) -> Iterator[tuple[int, list[int]]]:
    active = select(QuarantineEntry.id).where(or_(
        QuarantineEntry.state != "purged", QuarantineEntry.tx_phase.is_distinct_from("purged"),
    ))
    # Python and SQLite can interpret duplicate keys and nonstandard JSON differently.
    # Keep any row whose extracted entry ID cannot be reproduced by both parsers.
    sql_entry = case((func.json_valid(Journal.before_json), func.json_extract(Journal.before_json, "$.entry_id")))
    query = select(Journal.id, Journal.before_json, Journal.after_json, _eligible(cutoff), sql_entry).where(
        Journal.operation == OPERATION_ID,
    ).order_by(Journal.id.desc()).execution_options(yield_per=256)
    if candidates is not None:
        entry_ids = set(candidates.values())
        active = active.where(QuarantineEntry.id.in_(entry_ids))
        query = query.where(Journal.id.in_(candidates), sql_entry.in_(entry_ids))
    active_ids = set(session.scalars(active))
    has_compact = inspect(session.connection()).has_table(QuarantineUnlinkEvidence.__tablename__)
    pending: dict[int, list[tuple[UnlinkJournalRecord, dict]] | None] = {}
    # Walking backwards lets us verify the entire epoch at its authority,
    # including duplicate terminals or unexpected records after a terminal.
    for row_id, before, after, eligible, extracted_entry in session.execute(query):
        payload = _object(before)
        entry_id = payload.get("entry_id")
        # Legacy recovery compares IDs with Python equality: true or 1.0 can
        # shadow entry 1. Such a record invalidates its epoch and stays hot.
        if (not isinstance(entry_id, (float, int)) or not 0 < entry_id <= 2**63 - 1
                or (isinstance(entry_id, float) and not entry_id.is_integer()) or entry_id in active_ids):
            continue
        phase = payload.get("phase")
        recognized = (
            type(entry_id) is int and type(extracted_entry) is int and extracted_entry == entry_id
            and eligible and payload.get("purge_semantics") == SEMANTICS_VERSION
        )
        record = (UnlinkJournalRecord(row_id, before, after), payload)
        if phase == "authority":
            trailing = pending.pop(entry_id, None)
            if recognized and trailing:
                group = [record, *reversed(trailing)]
                if not _complete_epoch(group, entry_id):
                    continue
                ids = [row.id for row, _ in group]
                if has_compact and ids[-1] - ids[0] + 1 > len(ids):
                    # A truncated hot epoch cannot bridge an already moved incarnation.
                    compact = QuarantineUnlinkEvidence
                    if session.scalar(select(compact.id).where(
                        compact.entry_id == entry_id, compact.id.between(ids[0], ids[-1]),
                    ).limit(1)) is not None:
                        continue
                yield entry_id, ids
        elif recognized and phase == "terminal" and entry_id not in pending:
            pending[entry_id] = [record]
        elif recognized and phase == "unlink_intent" and (trailing := pending.get(entry_id)) and len(trailing) < 4:
            trailing.append(record)
        else:
            # Tombstone this incomplete/unknown epoch until its authority boundary.
            pending[entry_id] = None


def _ordinary(cutoff: datetime):
    return and_(Journal.operation.in_(ORDINARY_OPERATIONS), _eligible(cutoff),
                Journal.id.not_in(select(PendingTaskJournalDeletion.journal_id)))


def preview_operation_journal_archive(session_factory, cutoff: datetime) -> dict:
    """Count all eligible rows at one read-only database snapshot."""
    with session_factory() as session:
        session.execute(text("BEGIN"))
        count = session.scalar(select(func.count()).select_from(Journal).where(_ordinary(cutoff)))
        return {"rows": count + sum(len(ids) for _, ids in _completed_groups(session, cutoff))}


def _select_batch(session: Session, cutoff: datetime) -> tuple[list[int], dict[int, int]]:
    query = select(Journal.id).where(_ordinary(cutoff)).order_by(Journal.id).limit(_BATCH_SIZE)
    ordinary = list(session.scalars(query))
    remaining = _BATCH_SIZE - len(ordinary)
    entries: dict[int, int] = {}
    if remaining:
        for entry_id, group in _completed_groups(session, cutoff):
            if len(group) > remaining:
                break
            entries.update(dict.fromkeys(group, entry_id))
            remaining -= len(group)
            if remaining == 0:
                break
    return ordinary, entries


def _store_batch(session: Session, archive_dir: Path, ordinary: list[int], entries: dict[int, int]) -> dict:
    ids = [*ordinary, *entries]
    records = []
    evidence = []
    query = select(Journal.__table__).where(Journal.id.in_(ids)).order_by(Journal.id)
    for row in session.execute(query).mappings():
        record = {**row, "created_at": row.created_at.isoformat()}
        for field in ("id", "plan_id", "plan_item_id", "task_id", "user_id"):
            if record[field] is not None:
                record[field] = str(record[field])
        records.append(record)
        if row.id in entries:
            evidence.append({
                "id": row.id, "entry_id": entries[row.id],
                "payload": pack_unlink_evidence(row.before_json, row.after_json),
            })

    path = write_history_archive(archive_dir, "operation-journal", records)
    if evidence:
        QuarantineUnlinkEvidence.__table__.create(session.connection(), checkfirst=True)
        session.execute(insert(QuarantineUnlinkEvidence), evidence)
    session.execute(delete(Journal).where(Journal.id.in_(ids)))
    return {"rows": len(ids), "files": [str(path)]}


def archive_operation_journal(
    session_factory, archive_dir: Path, cutoff: datetime, *, fence: Callable[[Session], None] | None = None,
) -> dict:
    """Discover on a read snapshot and persist only a revalidated, bounded batch."""
    for _ in range(3):
        with session_factory() as session:
            connection = session.connection()
            connection.exec_driver_sql("BEGIN")
            version = connection.exec_driver_sql("PRAGMA data_version").scalar_one()
            ordinary, entries = _select_batch(session, cutoff)
            if not ordinary and not entries:
                return {"rows": 0, "files": []}

            # Keep the same physical connection: data_version is comparable only
            # there. A competing commit may add a new terminal or reuse an entry.
            # Retry discovery without holding a write lock when the snapshot changed.
            connection.exec_driver_sql("COMMIT")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            if connection.exec_driver_sql("PRAGMA data_version").scalar_one() != version:
                continue
            if fence is not None:
                fence(session)
            if ordinary:
                query = select(Journal.id).where(Journal.id.in_(ordinary), _ordinary(cutoff))
                ordinary = list(session.scalars(query))
            if entries:
                entries = {
                    row_id: entry_id
                    for entry_id, group in _completed_groups(session, cutoff, candidates=entries)
                    for row_id in group
                }
            if not ordinary and not entries:
                return {"rows": 0, "files": []}

            result = _store_batch(session, archive_dir, ordinary, entries)
            if fence is not None:
                fence(session)
            session.commit()
            return result
    raise MaintenanceConflict("操作流水正在更新，请稍后重试归档")
