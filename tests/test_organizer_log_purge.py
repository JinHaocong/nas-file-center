import json

import pytest
from sqlalchemy import select

from app.batch.media_organizer_jobs import get_batch
from app.batch.organizer_report_cleanup import BATCH, FLOW, KEY, PREVIEW, RESULT
from app.maintenance import organizer
from app.models import TaskEvent, WorkJob
from tests.test_organizer_history_archive import _seed, history


def _pair(factory, cutoff, statuses=("success", "skipped"), *, marker=None, dismissed=True):
    checkpoint = {"_task_queue_dismissed": dismissed}
    if marker:
        checkpoint[KEY] = {"status": marker}
    with factory.begin() as session:
        preview = WorkJob(kind=PREVIEW, status="completed", progress_total=2, progress_current=2,
                          state_json=json.dumps({"organizer_flow": FLOW, "selection": "/library"}),
                          checkpoint_json=json.dumps(checkpoint), finished_at=cutoff)
        session.add(preview)
        session.flush()
        preview_id = preview.id
        session.add(TaskEvent(job_id=preview_id, event_type="completed", message="ok"))
    state = {"organizer_flow": FLOW, "selection": "/library", "preview_job_id": str(preview_id)}
    return preview_id, _seed(factory, cutoff, statuses, state_json=json.dumps(state),
                             checkpoint_json=json.dumps(checkpoint))


def _events(factory, job_id):
    with factory() as session:
        return list(session.scalars(select(TaskEvent.event_type).where(TaskEvent.job_id == job_id)
                                    .order_by(TaskEvent.id)))


def test_purge_is_bounded_resumable_and_preserves_summary_and_recovery(history, monkeypatch):
    factory, settings, archive, cutoff = history
    preview, batch = _pair(factory, cutoff)
    with factory.begin() as session:
        session.add(TaskEvent(job_id=batch, event_type="recovered_after_worker_restart", message="old evidence"))
    monkeypatch.setattr(organizer, "CHUNK_SIZE", 1)
    for _ in range(4):
        assert organizer.purge_dismissed_organizer_logs(factory, settings) == {"rows": 1}
        assert get_batch(factory, settings, batch, page=1, page_size=20)["summary"]["success_count"] == 1
    assert organizer.purge_dismissed_organizer_logs(factory, settings) == {"rows": 0}
    assert _events(factory, batch) == ["recovered_after_worker_restart"]
    assert _events(factory, preview) == []
    assert not archive.exists()


@pytest.mark.parametrize("reason", ["pending", "retained", "visible", "conflict", "failed", "preview_file",
                                    "execution_file", "active_reference"])
def test_both_reports_and_all_evidence_must_be_closed(history, reason):
    factory, settings, _, cutoff = history
    statuses = ("success", reason) if reason in ("failed", "conflict") else ("success",)
    preview, batch = _pair(factory, cutoff, statuses, dismissed=reason != "visible",
                           marker=reason if reason in ("pending", "retained") else None)
    if reason == "active_reference":
        _seed(factory, cutoff, status="running", state_json=json.dumps(
            {"organizer_flow": FLOW, "preview_job_id": str(preview)}))
    if reason in ("preview_file", "execution_file"):
        kind, job = ("organizer-v1-previews", preview) if reason == "preview_file" else ("organizer-v1-executions", batch)
        folder = settings.reports_dir / kind / str(job)
        folder.mkdir(parents=True)
        (folder / "retained").touch()
    assert organizer.purge_dismissed_organizer_logs(factory, settings) == {"rows": 0}
    assert RESULT in _events(factory, batch)


def test_fence_rolls_back_events_and_checkpoint(history):
    factory, settings, _, cutoff = history
    _, batch = _pair(factory, cutoff)
    calls = []
    def fence(session):
        calls.append(session)
        if len(calls) == 2:
            raise RuntimeError("lost lease")
    with pytest.raises(RuntimeError, match="lost lease"):
        organizer.purge_dismissed_organizer_logs(factory, settings, fence=fence)
    assert _events(factory, batch) == [RESULT, RESULT, "task_completed"]
    with factory() as session:
        assert json.loads(session.get(WorkJob, batch).checkpoint_json) == {"_task_queue_dismissed": True}


def test_previous_partial_archive_retains_its_reader_and_log_suffix(history, monkeypatch):
    factory, settings, archive, cutoff = history
    _, batch = _pair(factory, cutoff)
    with factory.begin() as session:
        job = session.get(WorkJob, batch)
        job.checkpoint_json = json.dumps({"_task_queue_dismissed": True, "organizer_report_reclaimed_bytes": 0})
    monkeypatch.setattr(organizer, "CHUNK_SIZE", 1)
    before = get_batch(factory, settings, batch, page=1, page_size=20)
    assert organizer.archive_task_events(factory, archive, cutoff)["rows"] == 1
    assert organizer.purge_dismissed_organizer_logs(factory, settings) == {"rows": 0}
    after = get_batch(factory, settings, batch, page=1, page_size=20)
    assert after.pop("results_archived") and after == before


def test_new_logs_are_retained_even_if_sqlite_reuses_a_purged_id(history):
    factory, settings, _, cutoff = history
    _, batch = _pair(factory, cutoff)
    assert organizer.purge_dismissed_organizer_logs(factory, settings)["rows"] == 3
    with factory.begin() as session:
        session.add(TaskEvent(job_id=batch, event_type="progress", message="new evidence"))
    organizer.purge_dismissed_organizer_logs(factory, settings)
    assert _events(factory, batch) == ["progress"]


def test_read_snapshot_is_consistent_during_purge(history, monkeypatch):
    from app.batch import media_organizer_jobs

    factory, settings, _, cutoff = history
    _, batch = _pair(factory, cutoff)
    original = media_organizer_jobs._job

    def purge_after_read(*args):
        result = original(*args)
        assert organizer.purge_dismissed_organizer_logs(factory, settings)["rows"] == 3
        return result

    monkeypatch.setattr(media_organizer_jobs, "_job", purge_after_read)
    assert get_batch(factory, settings, batch, page=1, page_size=20)["filtered_total"] == 2
