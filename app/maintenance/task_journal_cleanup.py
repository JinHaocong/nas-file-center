"""Permanent cleanup of journal rows whose owning task was explicitly deleted."""

from sqlalchemy import case, delete, func, insert, select, true, union_all, update
from sqlalchemy.orm import Session

from app.models import BatchPlan, BatchPlanItem, OperationJournal as Journal, PendingTaskJournalDeletion as Pending


ORDINARY_OPERATIONS = ("move", "rename", "touch", "quarantine", "rmdir_empty")
JOURNAL_WATERMARK = "_internal_rowid_watermark"


def remember_task_journals(session: Session, task_ids) -> None:
    """Capture ownership before ON DELETE SET NULL removes the only proof of it."""
    # Quarantined directories may have no separate quarantine-entry record.
    # Keep any explicit recovery reference, including those from legacy jobs.
    payload = case((func.json_valid(Journal.after_json), Journal.after_json), else_="null")
    ordinary = select(Journal.id).where(
        Journal.task_id.in_(task_ids), Journal.operation.in_(ORDINARY_OPERATIONS),
        func.json_type(payload) == "object",
        func.json_extract(payload, "$.quarantine_path").is_(None),
        func.json_extract(payload, "$.quarantine_entry_id").is_(None),
        func.coalesce(func.json_extract(payload, "$.preserved"), 0) == 0,
    )
    session.execute(insert(Pending).prefix_with("OR IGNORE").from_select(["journal_id"], ordinary))


def _undo_journal_ids():
    # The plan summary and item-level provenance can survive independently in
    # older records. Build their ID set once per statement rather than per row.
    metadata = case((func.json_valid(BatchPlan.metadata_json), BatchPlan.metadata_json), else_="{}")
    ids = func.json_each(metadata, "$.source_journal_ids").table_valued("value")
    summary = select(ids.c.value).select_from(BatchPlan).join(ids, true()).where(
        BatchPlan.kind == "undo", ids.c.value.is_not(None),
    )
    item_metadata = case((func.json_valid(BatchPlanItem.metadata_json), BatchPlanItem.metadata_json), else_="{}")
    item_id = func.coalesce(func.json_extract(item_metadata, "$.undo.source_journal_id"),
                            func.json_extract(item_metadata, "$.source_journal_id"))
    items = select(item_id).join(BatchPlan, BatchPlan.id == BatchPlanItem.plan_id).where(
        BatchPlan.kind == "undo", item_id.is_not(None),
    )
    return union_all(summary, items)


def purge_released_task_journals(session: Session) -> None:
    """Called in the task/plan deletion transaction, after its foreign keys detach."""
    if session.scalar(select(Pending.journal_id).limit(1)) is None:
        return

    released = (
        Journal.id.in_(select(Pending.journal_id)), Journal.task_id.is_(None),
        Journal.plan_id.is_(None), Journal.plan_item_id.is_(None), Journal.id.not_in(_undo_journal_ids()),
    )
    high = session.scalar(select(func.max(Journal.id)))
    # Legacy SQLite allocates rowids from the highest live row. Remove its business
    # data in place so archives and unlink evidence can still use their original IDs.
    result = session.execute(update(Journal).where(Journal.id == high, *released).values(
        operation=JOURNAL_WATERMARK, sequence=0, user_id=None, before_json="{}", after_json="{}",
        metadata_before_json="{}", metadata_after_json="{}", created_at=func.current_timestamp(),
    ).execution_options(synchronize_session=False))
    if result.rowcount:
        session.execute(delete(Pending).where(Pending.journal_id == high))
    session.execute(delete(Journal).where(
        Journal.id < high, *released,
    ).execution_options(synchronize_session=False))
    session.execute(delete(Journal).where(
        Journal.id < high, Journal.operation == JOURNAL_WATERMARK,
    ).execution_options(synchronize_session=False))
