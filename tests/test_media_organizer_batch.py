"""User-level media organizer acceptance using the actual Worker and filesystem."""
import errno
import json
import os
from pathlib import Path

import pytest

from app.db import create_engine_and_session
from app.models import WorkJob
from app.tasks.recovery import acquire_worker_ownership, claim_next_job, recover_interrupted_jobs
from app.worker import process_work_job
from tests.test_media_package_execute_jobs import _fixture


def _run_next(settings, expected_id):
    engine, sessions = create_engine_and_session(settings.database_path)
    worker = "organizer-test-worker"
    try:
        assert acquire_worker_ownership(engine, sessions, worker)
        job_id = claim_next_job(engine, sessions, worker)
        assert str(job_id) == expected_id
        return process_work_job(settings, job_id, sessions, engine, worker)
    finally:
        engine.dispose()


def _preview(client, settings, selection):
    response = client.post("/api/media-organizer/previews", json={
        "selection": str(selection), "batch_flow": True,
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    assert isinstance(job_id, str)
    assert _run_next(settings, job_id)
    response = client.get(f"/api/media-organizer/previews/{job_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_new_preview_survives_removal_of_highest_unconfirmed_task(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "NO.001"
    selection.mkdir()
    (selection / "cover.jpg").write_bytes(b"cover")
    first = _preview(client, settings, selection)
    old_id = first["job_id"]
    artifact = settings.reports_dir / "organizer-v1-previews" / old_id / "summary.json"
    evidence = artifact.read_bytes()
    assert client.delete(f"/api/tasks/{old_id}").status_code == 200
    assert client.get(f"/api/tasks/{old_id}").status_code == 404

    second = _preview(client, settings, selection)
    assert second["job_id"] != old_id
    assert second["summary"] == first["summary"]
    assert artifact.read_bytes() == evidence


@pytest.mark.parametrize("subfolder", ["", "retained"])
def test_preview_rejects_direct_selection_inside_a_reserved_workspace(tmp_path, subfolder):
    client, settings, _ = _fixture(tmp_path)
    stage = settings.data_mount / "NO.001" / ".nfc-media-organizer-stage-35"
    selected = stage / subfolder
    selected.mkdir(parents=True)
    (selected / "frozen-item.jpg").write_bytes(b"unchanged")

    response = client.post("/api/media-organizer/previews", json={"selection": str(selected)})

    assert response.status_code == 409, response.text
    assert (selected / "frozen-item.jpg").read_bytes() == b"unchanged"


def test_old_frozen_history_does_not_block_new_recursive_batch(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "合集"
    first = selection / "A3594-53"
    second = selection / "A3594-54"
    (first / "P1").mkdir(parents=True)
    (first / "P1" / "cover.JPG").write_bytes(b"cover")
    second.mkdir()
    (second / "trailer.mp4").write_bytes(b"trailer")

    engine, sessions = create_engine_and_session(settings.database_path)
    try:
        with sessions.begin() as session:
            session.add(WorkJob(id=35, kind="media-organizer-execute", status="failed",
                                state_json=json.dumps({"unit": str(first)}),
                                checkpoint_json=json.dumps({
                                    "phase": "frozen", "frozen_job_id": 35,
                                    "manifest_checksum": "a" * 64, "_task_queue_dismissed": True,
                                })))
    finally:
        engine.dispose()

    preview = _preview(client, settings, selection)
    assert preview["summary"]["ready_count"] == 2
    assert "confirmation_tokens" not in preview
    assert (first / "P1" / "cover.JPG").exists()
    route = f"/api/media-organizer/previews/{preview['job_id']}/batches"
    created = client.post(route, json={})
    assert created.status_code == 200, created.text
    batch_id = created.json()["job_id"]
    assert client.post(route, json={}).json()["job_id"] == batch_id
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"] == {
        "success_count": 2, "skipped_count": 0, "conflict_count": 0, "failed_count": 0,
    }, report
    assert (first / "001.JPG").read_bytes() == b"cover"
    assert not (first / "P1").exists()
    assert (second / "001.mp4").read_bytes() == b"trailer"
    assert client.get(f"/api/media-organizer/previews/{preview['job_id']}").json()["batch_job_id"] == batch_id
    again = _preview(client, settings, selection)
    assert again["summary"]["already_organized_count"] == 2
    assert (again["summary"]["needed_moves"], again["summary"]["renamed_count"]) == (0, 0)


def _batch(client, preview):
    route = f"/api/media-organizer/previews/{preview['job_id']}/batches"
    response = client.post(route, json={})
    assert response.status_code == 200, response.text
    return response.json()["job_id"]


def test_preview_conflict_and_stale_unit_leave_unrelated_unit_executable(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else album"
    ambiguous = selection / "1"
    ambiguous.mkdir(parents=True)
    (ambiguous / "protected.jpg").write_bytes(b"protected")
    first, second = selection / "NO.001", selection / "NO.002"
    first.mkdir()
    second.mkdir()
    (first / "cover.JPG").write_bytes(b"cover")
    (second / "photo.JPG").write_bytes(b"photo")
    preview = _preview(client, settings, selection)
    assert preview["summary"]["ready_count"] == 2
    assert preview["summary"]["blocked_count"] == 1
    target = first / "001.JPG"
    target.write_bytes(b"foreign")
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert {item["unit"]: item["status"] for item in report["items"]} == {
        str(ambiguous): "conflict", str(first): "conflict", str(second): "success",
    }
    assert target.read_bytes() == b"foreign"
    assert (first / "cover.JPG").read_bytes() == b"cover"
    assert (ambiguous / "protected.jpg").read_bytes() == b"protected"
    assert (second / "001.JPG").read_bytes() == b"photo"


def test_interrupted_worker_resumes_only_the_current_unit(tmp_path, monkeypatch):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else album"
    first, second = selection / "NO.001", selection / "NO.002"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "cover.webp").write_bytes(b"cover")
    (second / "trailer.mp4").write_bytes(b"trailer")
    (second / "extra.mp4").write_bytes(b"extra")
    preview = _preview(client, settings, selection)
    batch_id = _batch(client, preview)
    move = engine._move_one

    def interrupted(*args, **kwargs):
        result = move(*args, **kwargs)
        if args[0]["source"].startswith(str(second)):
            raise SystemExit("Worker stopped while staging")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_move_one", interrupted)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    result_path = f"/api/media-organizer/batches/{batch_id}"
    assert client.get(result_path).json()["summary"]["success_count"] == 1
    inode = (first / "001.webp").stat().st_ino
    db, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        db.dispose()
    assert _run_next(settings, batch_id)
    result = client.get(result_path).json()
    assert result["status"] == "completed"
    assert result["summary"]["success_count"] == 2
    assert len(result["items"]) == 2
    assert (first / "001.webp").stat().st_ino == inode
    assert (second / "001.mp4").read_bytes() == b"extra"
    assert (second / "002.mp4").read_bytes() == b"trailer"


def test_fixed_luolcy_and_semantic_versions_are_separate_in_one_batch(tmp_path):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261122" / "作者" / "作品"
    photos = package / "任意下载目录" / "原图"
    photos.mkdir(parents=True)
    (photos / "name.JPG").write_bytes(b"photo")
    empty = package / "任意下载目录" / "原本为空"
    empty.mkdir()
    (package.parent / "作者封面.webp").write_bytes(b"author")
    work = root.parent / "作品 B"
    for version in ("4K", "PT"):
        (work / version).mkdir(parents=True)
        (work / version / "movie.mp4").write_bytes(version.encode())

    preview = _preview(client, settings, root.parent)
    assert preview["summary"]["totals"] == {"P": 1, "V": 2, "Other": 0}
    assert {unit["unit"]: unit["organizer_mode"] for unit in preview["units"]} == {
        str(package): "luolcy", str(work / "4K"): "semantic", str(work / "PT"): "semantic",
    }
    package_unit = next(unit for unit in preview["units"] if unit["unit"] == str(package))
    mapping = client.get(f"/api/media-organizer/previews/{preview['job_id']}/mappings/{package_unit['mapping_id']}")
    assert mapping.json()["moves"][0]["target"] == str(package / "001.JPG")
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"]["success_count"] == 3, result
    assert (package / "001.JPG").read_bytes() == b"photo"
    assert (package.parent / "作者封面.webp").read_bytes() == b"author"
    assert empty.is_dir()
    assert not photos.exists()
    for version in ("4K", "PT"):
        assert (work / version / "001.mp4").read_bytes() == version.encode()


@pytest.mark.parametrize("stop_at", ["staging", "publication"])
def test_restart_finishes_its_own_interrupted_fuse_hardlink(tmp_path, monkeypatch, stop_at):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    unit = settings.data_mount / "NO.001"
    unit.mkdir()
    (unit / "original.JPG").write_bytes(b"media")
    job = _batch(client, _preview(client, settings, unit))
    real_link = os.link

    def unsupported_rename(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "rename no-replace unsupported")

    def interrupted_link(*args, **kwargs):
        real_link(*args, **kwargs)
        target_fd = kwargs.get("dst_dir_fd")
        if target_fd is None:
            return
        target = Path(os.readlink(f"/proc/self/fd/{target_fd}"))
        writing_stage = target.name.startswith(".nfc-media_package-stage-")
        if writing_stage == (stop_at == "staging"):
            raise SystemExit("Worker stopped after the hardlink, before unlink")

    monkeypatch.setattr(engine, "rename_noreplace_at", unsupported_rename)
    with monkeypatch.context() as patch:
        patch.setattr(os, "link", interrupted_link)
        with pytest.raises(SystemExit):
            _run_next(settings, job)
    db, sessions = create_engine_and_session(settings.database_path)
    try:
        assert recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")["recovered_requeued"] == 1
    finally:
        db.dispose()
    assert _run_next(settings, job)
    report = client.get(f"/api/media-organizer/batches/{job}").json()
    assert report["summary"]["success_count"] == 1, report
    assert [(path.name, path.read_bytes()) for path in unit.iterdir()] == [("001.JPG", b"media")]


def test_grouped_batch_uses_sized_buckets_and_then_skips(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    unit = settings.data_mount / "NO.001"
    misplaced = unit / "videos"
    misplaced.mkdir(parents=True)
    for index in range(201):
        (misplaced / f"image-{index:03d}.JPG").write_bytes(b"x")
    (unit / "clip.mp4").write_bytes(b"clip")
    (unit / "clip.srt").write_bytes(b"subtitle")
    preview = _preview(client, settings, unit)
    assert preview["summary"]["file_count"] == 203
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    report = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert report["summary"]["success_count"] == 1, report
    assert set(path.name for path in unit.iterdir()) == {
        "P [200 200B]", "P_1 [1 1B]", "V [1 4B]", "Other [1 8B]",
    }
    assert len(list((unit / "P [200 200B]").iterdir())) == 200
    assert (unit / "P_1 [1 1B]" / "001.JPG").read_bytes() == b"x"
    assert (unit / "V [1 4B]" / "001.mp4").read_bytes() == b"clip"
    assert (unit / "Other [1 8B]" / "clip.srt").read_bytes() == b"subtitle"
    again = _preview(client, settings, unit)
    assert again["summary"]["already_organized_count"] == 1
    assert (again["summary"]["needed_moves"], again["summary"]["renamed_count"]) == (0, 0)
