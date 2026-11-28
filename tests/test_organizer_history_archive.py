import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.batch.media_organizer_jobs import get_batch
from app.batch.organizer_report_cleanup import BATCH, FLOW, KEY, RESULT, archived_result
from app.db import create_engine_and_session
from app.models import Base, TaskEvent, WorkJob, utcnow


@pytest.fixture
def history(tmp_path):
    engine, factory = create_engine_and_session(tmp_path / "db")
    Base.metadata.create_all(engine)
    settings = SimpleNamespace(config_dir=tmp_path, reports_dir=tmp_path / "reports",
                               history_archives_dir=tmp_path / "history-archives")
    yield factory, settings, tmp_path / "history-archives", utcnow()
    engine.dispose()


def _seed(factory, cutoff, statuses=("success", "skipped", "success", "skipped", "success"), **changes):
    attrs = dict(kind=BATCH, status="completed", progress_current=len(statuses), progress_total=len(statuses),
                 state_json=json.dumps({"selection": "/library", "organizer_flow": FLOW, "preview_job_id": "9"}),
                 checkpoint_json=json.dumps({"_task_queue_dismissed": True, "organizer_report_reclaimed_bytes": 0}),
                 finished_at=cutoff - timedelta(days=2))
    with factory.begin() as session:
        job = WorkJob(**(attrs | changes))
        session.add(job)
        session.flush()
        for ordinal, status in enumerate(statuses):
            session.add(TaskEvent(job_id=job.id, event_type=RESULT, message="done",
                                  context_json=json.dumps({"status": status, "ordinal": ordinal})))
        session.add(TaskEvent(job_id=job.id, event_type="task_completed", message="done"))
        return job.id


def test_partial_and_complete_archives_preserve_each_filtered_page(history, monkeypatch):
    from app.maintenance import organizer

    factory, settings, archive, cutoff = history
    job_id = _seed(factory, cutoff)
    monkeypatch.setattr(organizer, "CHUNK_SIZE", 2)

    def pages():
        return [get_batch(factory, settings, job_id, page=p, page_size=2, status_filter=status)
                for status in ("all", "success", "skipped", "failed") for p in (1, 2, 3)]

    original = pages()
    for remaining in (5, 3, 1):
        assert organizer.preview_task_event_archive(factory, cutoff) == {"rows": remaining, "jobs": 1}
        result = organizer.archive_task_events(factory, archive, cutoff)
        assert result["rows"] == min(remaining, 2) and len(result["files"]) == 1
        for before, after in zip(original, pages()):
            assert after.pop("results_archived") is True and before == after
    assert organizer.archive_task_events(factory, archive, cutoff) == {"rows": 0, "files": []}
    with factory() as session:
        assert list(session.scalars(select(TaskEvent.event_type))) == ["task_completed"]
        assert archived_result(session.get(WorkJob, job_id)) == original[0]["summary"]


def test_protects_jobs_with_incomplete_evidence(history):
    from app.maintenance import organizer

    factory, _, archive, cutoff = history
    for changes in ({"status": "running"}, {"error_text": "error"}, {"finished_at": cutoff},
                    {"progress_current": 1}, {"checkpoint_json": '{"_task_queue_dismissed":true}'},
                    {"checkpoint_json": '{"organizer_report_reclaimed_bytes":42}'}):
        _seed(factory, cutoff, **changes)
    for marker in ("pending", "retained"):
        _seed(factory, cutoff, checkpoint_json=json.dumps({"_task_queue_dismissed": True,
              "organizer_report_reclaimed_bytes": 3, KEY: {"status": marker}}))
    for status in ("failed", "conflict"):
        _seed(factory, cutoff, statuses=("success", status))
    assert organizer.preview_task_event_archive(factory, cutoff) == {"rows": 0, "jobs": 0}
    assert organizer.archive_task_events(factory, archive, cutoff) == {"rows": 0, "files": []}
    assert not archive.exists()


def test_fence_after_archive_publication_rolls_back_and_reuses_file(history):
    from app.maintenance import organizer

    factory, _, archive, cutoff = history
    _seed(factory, cutoff)
    def fence(session):
        if archive.exists():
            raise RuntimeError("lost lease")

    with pytest.raises(RuntimeError, match="lost lease"):
        organizer.archive_task_events(factory, archive, cutoff, fence=fence)
    published, = archive.iterdir()
    assert organizer.preview_task_event_archive(factory, cutoff)["rows"] == 5
    assert organizer.archive_task_events(factory, archive, cutoff)["rows"] == 5
    assert list(archive.iterdir()) == [published]


def test_older_batch_with_invalid_checkpoint_remains_readable(history):
    from app.maintenance import organizer

    factory, settings, _, cutoff = history
    job_id = _seed(factory, cutoff, checkpoint_json="invalid")
    detail = get_batch(factory, settings, job_id, page=1, page_size=2)
    assert detail["filtered_total"] == 5
    assert organizer.preview_task_event_archive(factory, cutoff)["jobs"] == 0


def test_reader_keeps_snapshot_when_archive_commits_between_queries(history, monkeypatch):
    from app.batch import media_organizer_jobs
    from app.maintenance import organizer

    factory, settings, archive, cutoff = history
    job_id = _seed(factory, cutoff)
    read_job = media_organizer_jobs._job

    def archive_after_job_read(*args):
        metadata = read_job(*args)
        assert organizer.archive_task_events(factory, archive, cutoff)["rows"] == 5
        return metadata

    monkeypatch.setattr(media_organizer_jobs, "_job", archive_after_job_read)
    detail = get_batch(factory, settings, job_id, page=1, page_size=5)
    assert detail["filtered_total"] == 5
    assert [item["ordinal"] for item in detail["items"]] == list(range(5))


def test_batch_endpoint_reports_unavailable_archive_without_losing_summary(tmp_path):
    from pathlib import Path

    from tests.test_media_package_execute_jobs import _fixture

    from app.maintenance import organizer

    client, settings, _ = _fixture(tmp_path)
    factory = client.app.state.service.SessionLocal
    cutoff = utcnow()
    job_id = _seed(factory, cutoff)
    result = organizer.archive_task_events(factory, settings.history_archives_dir, cutoff)
    Path(result["files"][0]).unlink()

    response = client.get(f"/api/media-organizer/batches/{job_id}")
    assert response.status_code == 503
    assert "history-archives" in response.json()["detail"]
    empty_page = client.get(f"/api/media-organizer/batches/{job_id}?page=10")
    assert empty_page.status_code == 200
    assert empty_page.json()["summary"]["success_count"] == 3
