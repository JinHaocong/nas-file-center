"""Smart organizer report cleanup through the actual task and Worker interfaces."""

from datetime import timedelta

from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_organizer_split_work import put_files
from tests.test_media_package_execute_jobs import _fixture


def _cleanup(client, settings):
    from app.batch.organizer_report_cleanup import process_pending_reports

    process_pending_reports(client.app.state.service.SessionLocal, settings, lambda: None)


def test_deleting_an_unconfirmed_preview_releases_reports_without_reusing_its_id(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    put_files(work, {"cover.jpg": b"photo"})
    preview = _preview(client, settings, work)["job_id"]
    report = settings.reports_dir / "organizer-v1-previews" / preview
    size = sum(path.stat().st_size for path in report.iterdir())

    response = client.delete(f"/api/tasks/{preview}")
    assert response.status_code == 200, response.text
    assert response.json()["report_cleanup"] == {"queued_count": 1, "retained_count": 0}
    assert client.post(f"/api/media-organizer/previews/{preview}/batches", json={}).status_code == 404
    _cleanup(client, settings)
    assert not report.exists() and (work / "cover.jpg").read_bytes() == b"photo"
    assert client.get(f"/api/tasks/{preview}").status_code == 404
    assert _preview(client, settings, work)["job_id"] != preview
    inventory = client.get("/api/tasks/organizer-reports").json()
    assert inventory["reclaimed_bytes"] == size
    assert any(row["job_id"] == preview and row["status"] == "released" for row in inventory["items"])


def test_clearing_history_releases_closed_batch_and_keeps_its_summary(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    put_files(work, {"cover.jpg": b"photo", "clip.mp4": b"film"})
    preview = _preview(client, settings, work)
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    original = client.get(f"/api/media-organizer/batches/{batch}").json()["summary"]
    assert original["success_count"] == 1

    cleared = client.post("/api/tasks/clear-history", json={"statuses": ["completed"]})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["report_cleanup"]["queued_count"] == 1
    _cleanup(client, settings)
    assert not (settings.reports_dir / "organizer-v1-previews" / preview["job_id"]).exists()
    assert not (settings.reports_dir / "organizer-v1-executions" / batch).exists()
    archived = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert archived["summary"] == original and archived["items"] == []
    assert (work / "P [1 5B]/001.jpg").read_bytes() == b"photo"


def test_terminal_batch_with_a_unit_conflict_keeps_recovery_reports(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    put_files(work, {"cover.jpg": b"photo"})
    preview = _preview(client, settings, work)
    batch = _batch(client, preview)
    put_files(work, {"001.jpg": b"occupied"})
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["status"] == "completed" and result["summary"]["conflict_count"] == 1
    response = client.delete(f"/api/tasks/{batch}")
    assert response.status_code == 200, response.text
    assert response.json()["report_cleanup"] == {"queued_count": 0, "retained_count": 1}
    _cleanup(client, settings)
    report = settings.reports_dir / "organizer-v1-previews" / preview["job_id"] / "units.jsonl"
    assert report.is_file() and (work / "cover.jpg").read_bytes() == b"photo"


def test_successful_archive_lift_can_reclaim_reports_after_paths_changed(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "old"
    put_files(archive / "old/作品甲", {"cover.jpg": b"photo"})
    put_files(archive / "old/作品乙", {"clip.mp4": b"video"})
    preview = _preview(client, settings, archive)
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    assert client.get(f"/api/media-organizer/batches/{batch}").json()["summary"]["success_count"] == 3
    assert client.delete(f"/api/tasks/{batch}").status_code == 200
    _cleanup(client, settings)
    assert not (settings.reports_dir / "organizer-v1-executions" / batch).exists()
    assert (archive / "作品甲/001.jpg").read_bytes() == b"photo"
    assert (archive / "作品乙/001.mp4").read_bytes() == b"video"


def test_referenced_preview_stays_readable_for_queued_batch(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    put_files(work, {"cover.jpg": b"photo"})
    preview = _preview(client, settings, work)
    batch = _batch(client, preview)

    response = client.delete(f"/api/tasks/{preview['job_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["report_cleanup"] == {"queued_count": 0, "retained_count": 1}
    _cleanup(client, settings)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["success_count"] == 1


def test_successful_batch_with_staging_residue_keeps_its_report(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    put_files(work, {"cover.jpg": b"photo"})
    preview = _preview(client, settings, work)
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    stage = work / f".nfc-media_package-stage-{batch}-root"
    put_files(stage, {"001.jpg": b"unfinished"})
    assert client.delete(f"/api/tasks/{batch}").status_code == 200
    _cleanup(client, settings)
    inventory = client.get("/api/tasks/organizer-reports").json()
    assert inventory["pending_count"] == 0 and inventory["reclaimed_bytes"] == 0
    assert any(row["job_id"] == batch and row["status"] == "retained" for row in inventory["items"])
    assert (settings.reports_dir / "organizer-v1-executions" / batch / "0.json").exists()
    assert (stage / "001.jpg").read_bytes() == b"unfinished"


def test_old_report_inventory_is_read_only_and_does_not_follow_links(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    reports = settings.reports_dir / "organizer-v1-previews"
    put_files(reports / "89", {"summary.json": b"old", "units.jsonl": b""})
    outside = tmp_path / "outside"
    put_files(outside, {"summary.json": b"untouched"})
    (reports / "90").symlink_to(outside, target_is_directory=True)
    before = {p.name for p in reports.iterdir()}
    response = client.get("/api/tasks/organizer-reports")
    assert response.status_code == 200, response.text
    inventory = response.json()
    assert inventory["read_only"] is True
    rows = {row["job_id"]: row for row in inventory["items"]}
    assert rows["89"]["status"] == "orphan" and rows["89"]["bytes"] == 3
    assert rows["90"]["status"] == "unknown" and rows["90"]["bytes"] == 0
    assert {p.name for p in reports.iterdir()} == before
    assert (outside / "summary.json").read_bytes() == b"untouched"


def test_worker_refuses_a_report_directory_replaced_after_delete_request(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    put_files(work, {"cover.jpg": b"photo"})
    preview = _preview(client, settings, work)["job_id"]
    path = settings.reports_dir / "organizer-v1-previews" / preview
    response = client.delete(f"/api/tasks/{preview}")
    assert response.json()["report_cleanup"]["queued_count"] == 1
    original = tmp_path / "original report"
    path.rename(original)
    put_files(path, {"summary.json": b"foreign", "units.jsonl": b"other report"})

    _cleanup(client, settings)
    assert (path / "summary.json").read_bytes() == b"foreign"
    assert (original / "summary.json").read_bytes() != b"foreign"
    assert client.get("/api/tasks/organizer-reports").json()["reclaimed_bytes"] == 0


def test_cleanup_can_resume_after_one_report_write_failure(tmp_path, monkeypatch):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "作品"
    put_files(work, {"cover.jpg": b"photo"})
    preview = _preview(client, settings, work)["job_id"]
    response = client.delete(f"/api/tasks/{preview}")
    assert response.status_code == 200, response.text
    assert response.json()["report_cleanup"]["queued_count"] == 1

    from app.batch import organizer_report_cleanup as reports

    unlink = reports.os.unlink
    count = 0

    def fail_once(path, *, dir_fd=None):
        nonlocal count
        if dir_fd is not None:
            count += 1
            if count == 2:
                raise PermissionError("simulated report write failure")
        return unlink(path, dir_fd=dir_fd)

    with monkeypatch.context() as patch:
        patch.setattr(reports.os, "unlink", fail_once)
        _cleanup(client, settings)
    pending = client.get("/api/tasks/organizer-reports").json()
    assert pending["pending_count"] == 1 and pending["reclaimed_bytes"] == 0
    retry_at = reports.utcnow() + timedelta(minutes=2)
    reports.process_pending_reports(client.app.state.service.SessionLocal, settings, lambda: None, now=retry_at)
    assert not (settings.reports_dir / "organizer-v1-previews" / preview).exists()
    assert client.get("/api/tasks/organizer-reports").json()["pending_count"] == 0
