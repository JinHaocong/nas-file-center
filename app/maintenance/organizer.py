"""Retire dismissed organizer logs and serve historical result archives."""

from collections import Counter
from datetime import datetime
from itertools import islice
import json
from pathlib import Path

from sqlalchemy import String, cast, delete, func, select, text

from app.batch.organizer_report_cleanup import (
    ARCHIVED_SUMMARY, BATCH, KEY, PREVIEW, RESULT, _has_references, _json_field, _object, archived_result,
    closed_result_counts, is_report_task, organizer_checkpoint, report_missing, report_reclaimed,
    report_state, report_task_filter,
)
from app.maintenance.archive_files import read_history_archive, write_history_archive
from app.models import TaskEvent, WorkJob

CHUNK_SIZE = 2000
STREAM = "organizer-task-events"
CHUNKS = "organizer_result_archives"

# Only event types emitted for ordinary queue activity are disposable. Historical
# recovery events and unrecognized event types may still be read by recovery code.
_ORDINARY = (RESULT, "queued", "started", "progress", "completed", "task_completed",
             "pause_requested", "paused", "resumed")
PURGE_THROUGH = "organizer_log_purge_through"


def _results(job_id):
    return (TaskEvent.job_id == job_id, TaskEvent.event_type == RESULT)


def _candidates(cutoff):
    return select(WorkJob).where(
        report_task_filter(), WorkJob.kind == BATCH, WorkJob.status == "completed",
        WorkJob.finished_at < cutoff, select(TaskEvent.id).where(*_results(WorkJob.id)).exists(),
    ).order_by(WorkJob.id)


def _cold_counts(chunks):
    counts = Counter()
    for chunk in chunks:
        counts.update(chunk["counts"])
    return counts


def _eligible(session, job):
    checkpoint = organizer_checkpoint(job)
    if (PURGE_THROUGH in checkpoint or checkpoint.get("_task_queue_dismissed") != 1 or not report_reclaimed(job)
            or report_state(job).get("status") not in (None, "released")):
        return None
    chunks = checkpoint.get(CHUNKS, [])
    counts = _cold_counts(chunks)
    summary = closed_result_counts(session, job, counts)
    if not summary or (chunks and summary != archived_result(job)):
        return None
    return checkpoint, summary, job.progress_total - sum(counts.values())


def _eligible_jobs(session, cutoff):
    for job in session.scalars(_candidates(cutoff).execution_options(yield_per=32)):
        details = _eligible(session, job)
        if details:
            yield job.id, details[2]


def preview_task_event_archive(session_factory, cutoff: datetime) -> dict:
    with session_factory() as session:
        session.execute(text("BEGIN"))
        jobs = rows = 0
        for _, count in _eligible_jobs(session, cutoff):
            jobs += 1
            rows += count
        return {"jobs": jobs, "rows": rows}


def _archive_row(event):
    return {"id": str(event.id), "job_id": str(event.job_id), "timestamp": event.timestamp.isoformat(),
            "level": event.level, "event_type": event.event_type, "message": event.message,
            "context_json": event.context_json}


def archive_task_events(session_factory, archive_dir: Path, cutoff: datetime, *, fence=None) -> dict:
    """Move one bounded, ordered prefix and publish its index in the deletion transaction."""
    empty = {"rows": 0, "files": []}
    with session_factory() as session:
        candidate = next(_eligible_jobs(session, cutoff), None)
    if candidate is None:
        return empty
    with session_factory.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        if fence:
            fence(session)
        job = session.scalar(_candidates(cutoff).where(WorkJob.id == candidate[0]))
        details = _eligible(session, job) if job else None
        if not details:
            return empty
        checkpoint, summary, _ = details
        events = session.scalars(select(TaskEvent).where(*_results(job.id)).order_by(TaskEvent.id).limit(CHUNK_SIZE))
        rows = [_archive_row(event) for event in events]
        counts = Counter(json.loads(row["context_json"])["status"] for row in rows)
        path = write_history_archive(archive_dir, STREAM, rows)
        if fence:
            fence(session)
        checkpoint[ARCHIVED_SUMMARY] = summary
        checkpoint.setdefault(CHUNKS, []).append({"file": path.name, "counts": dict(counts)})
        job.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
        # Rows form an ordered prefix under the writer lock, even when unrelated logs interleave.
        session.execute(delete(TaskEvent).where(*_results(job.id), TaskEvent.id <= rows[-1]["id"]))
    return {"rows": len(rows), "files": [str(path)]}


def archived_page(session, job, archive_dir, *, page, page_size, status_filter):
    """Read only the cold chunks intersecting this page, then its live suffix if needed."""
    checkpoint = organizer_checkpoint(job)
    if PURGE_THROUGH in checkpoint:
        return {"summary": archived_result(job), "items": [], "filtered_total": 0}
    chunks = checkpoint.get(CHUNKS)
    if not chunks:
        return None
    summary = archived_result(job)
    all_rows = status_filter == "all"
    offset = (page - 1) * page_size
    items = []
    for chunk in chunks:
        counts = chunk["counts"]
        size = sum(counts.values()) if all_rows else counts.get(status_filter, 0)
        if offset >= size:
            offset -= size
            continue
        rows = read_history_archive(archive_dir, STREAM, chunk["file"])
        contexts = (json.loads(row["context_json"]) for row in rows)
        matches = (ctx for ctx in contexts if all_rows or ctx["status"] == status_filter)
        items.extend(islice(matches, offset, offset + page_size - len(items)))
        offset = 0
        if len(items) == page_size:
            break
    if len(items) < page_size:
        query = select(TaskEvent.context_json).where(*_results(job.id))
        if not all_rows:
            query = query.where(func.json_extract(TaskEvent.context_json, "$.status") == status_filter)
        tail = session.scalars(query.order_by(TaskEvent.id).offset(offset).limit(page_size - len(items)))
        items.extend(json.loads(context) for context in tail)
    total = sum(summary.values()) if all_rows else summary.get(f"{status_filter}_count", 0)
    return {"summary": summary, "items": items, "filtered_total": total, "results_archived": True}

def _closed_report(job, settings):
    checkpoint = organizer_checkpoint(job)
    marker = report_state(job)
    return (is_report_task(job) and job.status == "completed" and job.finished_at is not None
            and not job.error_text and not job.error_code
            and job.progress_total >= 0 and job.progress_total == job.progress_current
            and (KEY not in checkpoint or marker.get("status") == "released")
            and report_missing(settings, job.kind, job.id))


def _batch_log_summary(session, job, preview, settings):
    state = _object(job.state_json)
    if (preview is None or preview.kind != PREVIEW or not _closed_report(preview, settings)
            or not state.get("selection") or state["selection"] != _object(preview.state_json).get("selection")
            or _has_references(session, preview.id, except_job=job.id)):
        return None
    checkpoint = organizer_checkpoint(job)
    if checkpoint.get(CHUNKS):
        return None
    if PURGE_THROUGH in checkpoint:
        return archived_result(job)
    return closed_result_counts(session, job)


def _log_proof(session, job, settings):
    if not _closed_report(job, settings) or organizer_checkpoint(job).get("_task_queue_dismissed") != 1:
        return None
    if job.kind == BATCH:
        preview_id = _object(job.state_json).get("preview_job_id")
        if type(preview_id) not in (int, str) or not str(preview_id).isascii() or not str(preview_id).isdecimal():
            return None
        return _batch_log_summary(session, job, session.get(WorkJob, preview_id), settings)
    if not _has_references(session, job.id):
        return {}
    # A paired preview can be retired once its sole consuming batch has proved
    # closure and captured its immutable event boundary. Other references stay hot.
    batch = session.scalar(select(WorkJob).where(
        report_task_filter(), WorkJob.kind == BATCH,
        cast(_json_field(WorkJob.state_json, "$.preview_job_id"), String) == str(job.id),
        _json_field(WorkJob.checkpoint_json, f"$.{PURGE_THROUGH}").is_not(None),
    ).limit(1))
    if batch and _closed_report(batch, settings) and _batch_log_summary(session, batch, job, settings):
        return {}
    return None


def _purge_candidates():
    through = _json_field(WorkJob.checkpoint_json, f"$.{PURGE_THROUGH}")
    events = select(TaskEvent.id).where(
        TaskEvent.job_id == WorkJob.id, TaskEvent.event_type.in_(_ORDINARY),
        through.is_(None) | (TaskEvent.id <= cast(through, TaskEvent.id.type)),
    )
    return select(WorkJob).where(
        report_task_filter(), WorkJob.status == "completed",
        _json_field(WorkJob.checkpoint_json, "$._task_queue_dismissed") == 1, events.exists(),
    ).order_by((WorkJob.kind == BATCH).desc(), WorkJob.id)


def purge_dismissed_organizer_logs(session_factory, settings, *, fence=None) -> dict:
    """Permanently retire one bounded prefix after the organizer has closed both reports."""
    with session_factory() as session:
        candidates = session.scalars(_purge_candidates().execution_options(yield_per=32))
        job_id = next((job.id for job in candidates if _log_proof(session, job, settings) is not None), None)
    if job_id is None:
        return {"rows": 0}
    with session_factory.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        if fence:
            fence(session)
        job = session.scalar(_purge_candidates().where(WorkJob.id == job_id))
        summary = _log_proof(session, job, settings) if job else None
        if summary is None:
            return {"rows": 0}
        checkpoint = organizer_checkpoint(job)
        ordinary = (TaskEvent.job_id == job_id, TaskEvent.event_type.in_(_ORDINARY))
        if PURGE_THROUGH not in checkpoint:
            # A durable upper bound both prevents deleting later evidence and
            # lets a large job continue after its result rows start disappearing.
            last_id = session.scalar(select(func.max(TaskEvent.id)).where(*ordinary))
            checkpoint[PURGE_THROUGH] = str(last_id)
            if job.kind == BATCH:
                checkpoint[ARCHIVED_SUMMARY] = summary
        ids = select(TaskEvent.id).where(
            *ordinary, TaskEvent.id <= checkpoint[PURGE_THROUGH],
        ).order_by(TaskEvent.id).limit(CHUNK_SIZE)
        removed = session.execute(delete(TaskEvent).where(TaskEvent.id.in_(ids))
                                  .execution_options(synchronize_session=False)).rowcount
        if session.scalar(ids.limit(1)) is None:
            # SQLite can reuse the highest removed ID after this commit. Close
            # the range permanently so newly appended logs will never match it.
            checkpoint[PURGE_THROUGH] = "0"
        job.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
        if fence:
            fence(session)
    return {"rows": removed}
