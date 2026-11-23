"""User-level media organizer acceptance using the actual Worker and filesystem."""
import errno
import json
import os
from itertools import accumulate
from pathlib import Path

import pytest
from sqlalchemy import event

from app.db import create_engine_and_session
from app.models import WorkJob
from app.tasks.recovery import acquire_worker_ownership, claim_next_job, recover_interrupted_jobs
from app.worker import process_work_job
from tests.test_media_package_execute_jobs import _fixture


def _run_next(settings, expected_id, *, trace_sql=None):
    engine, sessions = create_engine_and_session(settings.database_path)
    if trace_sql is not None:
        event.listen(engine, "connect", lambda conn, _: conn.set_trace_callback(trace_sql))
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


def test_batch_organizes_exact_same_name_wrappers_at_the_outer_work_in_one_pass(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else/合集"
    repeated_video = selection / "三层视频"
    works = {
        selection / "纯视频": {"clip.MP4": ("001.MP4", b"vids")},
        repeated_video: {"clip.MP4": ("001.MP4", b"deep")},
        selection / "图视频作品": {
            "cover.JPG": ("P [1 4B]/001.JPG", b"phot"),
            "clip.mp4": ("V [1 4B]/001.mp4", b"clip"),
        },
    }
    for work, files in works.items():
        inner = work / work.name
        if work == repeated_video:
            inner /= work.name
        inner.mkdir(parents=True)
        for source, (_, content) in files.items():
            (inner / source).write_bytes(content)

    preview = _preview(client, settings, selection)
    assert {(row["unit"], row["status"]) for row in preview["units"]} == {
        (str(work), "ready") for work in works
    }
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["success_count"] == len(works), report
    for work, files in works.items():
        assert not (work / work.name).exists()
        assert all((work / target).read_bytes() == content for target, content in files.values())
    assert _preview(client, settings, selection)["summary"]["already_organized_count"] == len(works)


def test_batch_scans_named_works_inside_numbered_volumes_in_place(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else/作品合集/网盘"
    works = [selection / "1/作品 EXVOL.01", selection / "2/春节特别期 [2P-6B]"]
    for work in works:
        work.mkdir(parents=True)
        (work / "cover.jpg").write_bytes(b"cover")

    preview = _preview(client, settings, selection)
    assert [(row["unit"], row["status"]) for row in preview["units"]] == [
        (str(work), "ready") for work in works
    ]
    assert preview["summary"]["blocked_count"] == 0

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"] == {"success_count": 2, "skipped_count": 0, "conflict_count": 0, "failed_count": 0}
    for work in works:
        assert (work / "001.jpg").read_bytes() == b"cover"
        assert list(work.parent.iterdir()) == [work]
    assert sorted(path.name for path in selection.iterdir()) == ["1", "2"]
    again = _preview(client, settings, selection)
    assert [(row["unit"], row["status"]) for row in again["units"]] == [
        (str(work), "already_organized") for work in works
    ]


def test_batch_promotes_numbered_photo_groups_and_numbers_each_group_independently(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else/下载目录"
    work = selection / "系列 [4P 4B]"
    files = {
        "图片/3/a.jpg": ("3/001.jpg", b"a"),
        "图片/3/b.JPG": ("3/002.JPG", b"b"),
        "图片/9/a.jpg": ("9/001.jpg", b"c"),
        "图片/12/a.jpg": ("12/001.jpg", b"d"),
    }
    for relative, (_, content) in files.items():
        path = work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    preview = _preview(client, settings, selection)
    assert [(row["unit"], row["status"], row["needed_moves"]) for row in preview["units"]] == [
        (str(work), "ready", 4),
    ]
    assert [group["name"] for group in preview["units"][0]["groups"]] == ["3", "9", "12"]
    assert {(move["source"], move["target"]) for move in preview["units"][0]["sample_moves"]} == {
        (str(work / before), str(work / after)) for before, (after, _) in files.items()
    }
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"]["success_count"] == 1, result
    assert sorted(entry.name for entry in work.iterdir()) == ["12", "3", "9"]
    assert all((work / after).read_bytes() == content for after, content in files.values())
    again = _preview(client, settings, selection)
    assert again["summary"]["ready_count"] == 0
    assert again["summary"]["blocked_count"] == 0


@pytest.mark.parametrize("boundary", ["occupied-target", "interrupted-cleanup"])
def test_numbered_photo_group_worker_respects_frozen_destinations(tmp_path, monkeypatch, boundary):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "Else/下载目录/系列 [2P 4B]"
    before = [work / "图片/3/cover.jpg", work / "图片/9/cover.jpg"]
    for path in before:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"ok")
    batch_id = _batch(client, _preview(client, settings, work))

    if boundary == "occupied-target":
        save_manifest = engine.save_frozen_manifest

        def occupy_target(path, manifest):
            save_manifest(path, manifest)
            (work / "3").mkdir()
            (work / "3/foreign.jpg").write_bytes(b"foreign")

        monkeypatch.setattr(engine, "save_frozen_manifest", occupy_target)
        assert _run_next(settings, batch_id)
        report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
        assert report["summary"]["conflict_count"] == 1, report
        assert (work / "3/foreign.jpg").read_bytes() == b"foreign"
        assert all(path.read_bytes() == b"ok" for path in before)
        assert not list(work.glob(".nfc-*"))
        return

    def stop_before_final_cleanup(*args, **kwargs):
        if not kwargs.get("only_under"):
            raise SystemExit("Worker stopped after publication before cleanup")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_remove_empty_sources", stop_before_final_cleanup)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    assert (work / "图片").is_dir() and (work / "3/001.jpg").read_bytes() == b"ok"

    db, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        db.dispose()
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["success_count"] == 1, report
    assert sorted(path.name for path in work.iterdir()) == ["3", "9"]


def test_batch_appends_an_only_child_video_without_moving_numbered_root_videos(tmp_path, monkeypatch):
    from app.batch import media_package_execution

    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2611/261123/AKS"
    video = author / "#AKs 11.19号 标题" / "001.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"nested")
    originals = {author / f"{index:03d}.mp4": bytes([index]) for index in range(1, 6)}
    for path, content in originals.items():
        path.write_bytes(content)
    destination = author / "006.mp4"

    preview = _preview(client, settings, author.parent)
    assert [(row["unit"], row["status"], row["needed_moves"]) for row in preview["units"]] == [
        (str(author), "ready", 1),
    ]
    assert [(move["source"], move["target"]) for move in preview["units"][0]["sample_moves"]] == [
        (str(video), str(destination)),
    ]
    assert video.read_bytes() == b"nested"
    staged_sources = []
    move_one = media_package_execution._move_one

    def record_move(row, **kwargs):
        staged_sources.append(row["source"])
        return move_one(row, **kwargs)

    monkeypatch.setattr(media_package_execution, "_move_one", record_move)
    job = _batch(client, preview)
    assert _run_next(settings, job)
    report = client.get(f"/api/media-organizer/batches/{job}").json()
    assert report["summary"]["success_count"] == 1, report
    assert staged_sources == [str(video)]
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert destination.read_bytes() == b"nested"
    assert not video.parent.exists()
    again = _preview(client, settings, author.parent)
    assert [(row["unit"], row["status"]) for row in again["units"]] == [
        (str(author), "already_organized"),
    ]


@pytest.mark.parametrize("interrupted", [None, "staging", "publication"])
def test_batch_appends_an_author_initials_wrapper_and_preserves_named_video_groups(
    tmp_path, monkeypatch, interrupted,
):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    month = settings.data_mount / "Else/2611"
    author = month / "261120/小可爱甜甜"
    wrapper = author / "xkatt"
    wrapper.mkdir(parents=True)
    kept = author / "001.mp4"
    kept.write_bytes(b"existing")
    sources = [wrapper / f"{index:03d}.mp4" for index in range(1, 6)]
    for index, path in enumerate(sources, 1):
        path.write_bytes(bytes([index]))

    other = month / "261103/小意"
    child = other / "小意裸舞"
    child.mkdir(parents=True)
    (other / "001.mp4").write_bytes(b"loose")
    for index in range(1, 3):
        (child / f"{index:03d}.mp4").write_bytes(b"named group")

    preview = _preview(client, settings, month)
    assert [(row["unit"], row["needed_moves"]) for row in preview["units"] if row["status"] == "ready"] == [
        (str(author), 5),
    ]
    staged = []
    move_one = engine._move_one

    def record_move(row, **kwargs):
        result = move_one(row, **kwargs)
        if result == "moved":
            staged.append(row["source"])
            if interrupted == "staging" and len(staged) == 1:
                raise SystemExit("Worker stopped after staging the first video")
        return result

    monkeypatch.setattr(engine, "_move_one", record_move)
    if interrupted == "publication":
        publish = engine._publish_flat_file

        def stop_after_first_publication(row, *args, **kwargs):
            result = publish(row, *args, **kwargs)
            if result == "published" and row["target_name"] == "002.mp4":
                raise SystemExit("Worker stopped after publishing the first video")
            return result

        monkeypatch.setattr(engine, "_publish_flat_file", stop_after_first_publication)
    batch_id = _batch(client, preview)
    if interrupted:
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
        assert kept.read_bytes() == b"existing"
        db, sessions = create_engine_and_session(settings.database_path)
        try:
            recovered = recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")
            assert recovered["recovered_requeued"] == 1
        finally:
            db.dispose()
    assert _run_next(settings, batch_id)
    summary = client.get(f"/api/media-organizer/batches/{batch_id}").json()["summary"]
    assert summary == {"success_count": 1, "skipped_count": 2, "conflict_count": 0, "failed_count": 0}
    assert staged == [str(path) for path in sources]
    assert kept.read_bytes() == b"existing"
    assert [(author / f"{index:03d}.mp4").read_bytes() for index in range(2, 7)] == [
        bytes([index]) for index in range(1, 6)
    ]
    assert not wrapper.exists()
    assert sorted(path.name for path in child.iterdir()) == ["001.mp4", "002.mp4"]
    assert _preview(client, settings, month)["summary"]["already_organized_count"] == 3


@pytest.mark.parametrize("phase", ["staging", "publication"])
def test_author_initials_resume_checks_all_videos_before_moving_more(tmp_path, monkeypatch, phase):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2611/261120/小可爱甜甜"
    wrapper = author / "xkatt"
    wrapper.mkdir(parents=True)
    (author / "001.mp4").write_bytes(b"keep")
    (wrapper / "001.mp4").write_bytes(b"first")
    (wrapper / "002.mp4").write_bytes(b"second")
    (wrapper / "003.mp4").write_bytes(b"third")
    batch_id = _batch(client, _preview(client, settings, author))
    real_move = engine._move_one

    def stop_after_first_staged_video(row, **kwargs):
        real_move(row, **kwargs)
        raise SystemExit("Worker stopped during staging")

    def stop_before_publication(*args, **kwargs):
        raise SystemExit("Worker stopped after marking the stage ready")

    with monkeypatch.context() as patch:
        if phase == "staging":
            patch.setattr(engine, "_move_one", stop_after_first_staged_video)
        else:
            patch.setattr(engine, "_publish_flat_file", stop_before_publication)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    if phase == "staging":
        missing = wrapper / "003.mp4"
        second = wrapper / "002.mp4"
    else:
        missing, = author.glob(".nfc-*/004.mp4")
        second, = author.glob(".nfc-*/003.mp4")
    missing.unlink()

    db, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        db.dispose()
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["conflict_count"] == 1, report
    assert not (author / "002.mp4").exists()
    staged, = author.glob(".nfc-*/002.mp4")
    assert staged.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert (author / "001.mp4").read_bytes() == b"keep"


@pytest.mark.parametrize("foreign_path", [None, "003.mp4", "002.mp4", "#AKS 标题/new.mp4"])
def test_appending_one_video_checks_its_scope_before_resuming_publication(tmp_path, monkeypatch, foreign_path):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2611/261123/AKS"
    video = author / "#AKS 标题" / "001.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"nested")
    kept = author / "001.mp4"
    kept.write_bytes(b"existing")
    inode = kept.stat().st_ino
    batch_id = _batch(client, _preview(client, settings, author))

    def stop_before_publication(*args, **kwargs):
        raise SystemExit("Worker stopped after staging the new video")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_publish_flat_file", stop_before_publication)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    assert kept.read_bytes() == b"existing"
    assert not (author / "002.mp4").exists()
    assert not video.exists()
    if foreign_path:
        (author / foreign_path).write_bytes(b"foreign")

    db, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        db.dispose()
    assert _run_next(settings, batch_id)
    summary = client.get(f"/api/media-organizer/batches/{batch_id}").json()["summary"]
    assert kept.stat().st_ino == inode and kept.read_bytes() == b"existing"
    if foreign_path:
        assert summary["conflict_count"] == 1
        assert (author / foreign_path).read_bytes() == b"foreign"
        assert (author / "002.mp4").exists() == (foreign_path == "002.mp4")
        staged, = author.glob(".nfc-*/002.mp4")
        assert staged.read_bytes() == b"nested"
    else:
        assert summary["success_count"] == 1
        assert (author / "002.mp4").read_bytes() == b"nested"
        assert {item.name for item in author.iterdir()} == {"001.mp4", "002.mp4"}


def test_append_refuses_an_occupied_target_before_staging(tmp_path, monkeypatch):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2611/261123/AKS"
    video = author / "#AKS 标题" / "001.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"nested")
    (author / "001.mp4").write_bytes(b"existing")
    batch_id = _batch(client, _preview(client, settings, author))
    save_manifest = engine.save_frozen_manifest

    def occupy_target(path, manifest):
        save_manifest(path, manifest)
        (author / "002.mp4").write_bytes(b"foreign")

    monkeypatch.setattr(engine, "save_frozen_manifest", occupy_target)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["conflict_count"] == 1, report
    assert (author / "001.mp4").read_bytes() == b"existing"
    assert (author / "002.mp4").read_bytes() == b"foreign"
    assert video.read_bytes() == b"nested"
    assert not list(author.glob(".nfc-*"))


def test_batch_flattens_the_whole_author_tree_around_one_mixed_numbered_folder(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2611/261123/作者A"
    files = {
        "1/a.mp4": b"numbered-folder-video",
        "1/子作品/clip.mp4": b"nested-work-video",
        "z-root.mp4": b"author-root-video",
        "其他作品/clip.mp4": b"sibling-work-video",
    }
    for name, content in files.items():
        path = author / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    preview = _preview(client, settings, author.parent.parent)
    assert [(row["unit"], row["status"], row["needed_moves"]) for row in preview["units"]] == [
        (str(author), "ready", 4),
    ]
    assert all((author / name).read_bytes() == content for name, content in files.items())
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"] == {"success_count": 1, "conflict_count": 0, "failed_count": 0, "skipped_count": 0}
    assert {path.name: path.read_bytes() for path in author.iterdir()} == {
        f"{index:03d}.mp4": content for index, content in enumerate(files.values(), 1)
    }
    again = _preview(client, settings, author.parent.parent)
    assert [(row["unit"], row["status"]) for row in again["units"]] == [
        (str(author), "already_organized"),
    ]


@pytest.mark.parametrize("after_freeze", [False, True])
def test_whole_author_batch_leaves_files_in_place_if_a_numbered_sibling_appears(
    tmp_path, monkeypatch, after_freeze,
):
    from app.batch import media_package_execution

    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2611/261123/作者A"
    sources = [author / name for name in ("root.mp4", "1/clip.mp4", "1/子作品/nested.mp4")]
    for path in sources:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original")
    preview = _preview(client, settings, author)
    assert [row["unit"] for row in preview["units"]] == [str(author)]
    if after_freeze:
        save_manifest = media_package_execution.save_frozen_manifest

        def add_folder_after_saving(path, manifest):
            save_manifest(path, manifest)
            (author / "02").mkdir()

        monkeypatch.setattr(media_package_execution, "save_frozen_manifest", add_folder_after_saving)
    else:
        (author / "02").mkdir()

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    report = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert report["summary"]["conflict_count"] == 1
    assert all(path.read_bytes() == b"original" for path in sources)
    assert not (author / "001.mp4").exists()


def test_batch_preserves_ambiguous_loose_files_and_organizes_confirmed_units(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else album"
    author = selection / "2602" / "260216" / "作者A"
    named_work = author / "NO.001"
    work = selection / "作品B"
    mixed_wrapper = work / "P"
    nested_work = mixed_wrapper / "NO.002"
    volumes = selection / "两卷合集"

    kept = {
        author / "随手拍.mp4": b"author level media",
        author / "归属不明.jpg": b"an unrelated author level picture",
    }
    moved = {
        named_work / "封面.jpg": (named_work / "001.jpg", b"named work cover"),
        mixed_wrapper / "散图.jpg": (mixed_wrapper / "001.jpg", b"local picture"),
        nested_work / "封面.webp": (nested_work / "001.webp", b"nested work cover"),
        work / "videos" / "片段.mp4": (work / "001.mp4", b"work clip"),
        volumes / "01" / "a.jpg": (volumes / "01" / "001.jpg", b"first cover"),
        volumes / "01" / "b.PNG": (volumes / "01" / "002.PNG", b"first page"),
        volumes / "02" / "a.jpg": (volumes / "02" / "001.jpg", b"second cover"),
    }
    inputs = kept | {source: content for source, (_, content) in moved.items()}
    for path, content in inputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    expected_ready = {named_work, mixed_wrapper, nested_work, work, volumes / "01", volumes / "02"}
    expected_blocked = {author}
    preview = _preview(client, settings, selection)
    assert {Path(row["unit"]) for row in preview["units"] if row["status"] == "ready"} == expected_ready
    assert {Path(row["unit"]) for row in preview["units"] if row["status"] == "blocked"} == expected_blocked

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert {Path(item["unit"]) for item in result["items"] if item["status"] == "success"} == expected_ready
    assert {Path(item["unit"]) for item in result["items"] if item["status"] == "conflict"} == expected_blocked
    assert result["summary"]["failed_count"] == 0
    for path, content in kept.items():
        assert path.read_bytes() == content
    for source, (destination, content) in moved.items():
        assert destination.read_bytes() == content
        assert not source.exists()
    assert not (work / "videos").exists()

    rescan = _preview(client, settings, selection)
    assert (rescan["summary"]["needed_moves"], rescan["summary"]["renamed_count"]) == (0, 0)
    assert {Path(row["unit"]) for row in rescan["units"] if row["status"] == "already_organized"} == expected_ready
    assert {Path(row["unit"]) for row in rescan["units"] if row["status"] == "blocked"} == expected_blocked


def test_batch_organizes_numbered_siblings_and_local_media_without_crossing_boundaries(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else album"
    download = selection / "下载目录"
    author = selection / "2602" / "260216" / "作者A"
    titled_work = author / "NO.001"
    photo_container = selection / "时间难考证" / "照片"
    titled_photos = photo_container / "今日份自拍"
    unknown = selection / "新建文件夹"

    kept = {
        author / "videos" / "001.mp4": b"separate old wrapper",
    }
    moved = {
        unknown / "散图.jpg": (unknown / "P [1 5B]/001.jpg", b"photo"),
        unknown / "片段.mp4": (unknown / "V [1 4B]/001.mp4", b"clip"),
        download / "recap.mp4": (download / "001.mp4", b"parent video"),
        download / "1" / "clip.mp4": (download / "1" / "001.mp4", b"first package"),
        download / "2" / "clip.mp4": (download / "2" / "001.mp4", b"second package"),
        titled_work / "封面.jpg": (titled_work / "001.jpg", b"titled work"),
        photo_container / "a.jpg": (photo_container / "001.jpg", b"local picture one"),
        photo_container / "b.PNG": (photo_container / "002.PNG", b"local picture two"),
        titled_photos / "a.jpg": (titled_photos / "001.jpg", b"titled subgroup"),
    }
    for path, content in (kept | {source: data for source, (_, data) in moved.items()}).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for position in range(201):
        (author / f"clip-{position:03d}.mp4").write_bytes(b"x")

    expected_ready = {download, download / "1", download / "2", author, unknown,
                      titled_work, photo_container, titled_photos}
    preview = _preview(client, settings, selection)
    assert {Path(row["unit"]) for row in preview["units"] if row["status"] == "ready"} == expected_ready
    author_preview = next(row for row in preview["units"] if row["unit"] == str(author))
    assert author_preview["totals"] == {"P": 0, "V": 201, "Other": 0}
    assert [group["count"] for group in author_preview["groups"]] == [200, 1]

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert {Path(item["unit"]) for item in result["items"] if item["status"] == "success"} == expected_ready
    assert result["summary"]["failed_count"] == 0
    for path, content in kept.items():
        assert path.read_bytes() == content
    for source, (destination, content) in moved.items():
        assert destination.read_bytes() == content
        assert not source.exists()
    assert len(list((author / "V [200 200B]").iterdir())) == 200
    assert (author / "V_1 [1 1B]" / "001.mp4").read_bytes() == b"x"

    rescan = _preview(client, settings, selection)
    assert (rescan["summary"]["needed_moves"], rescan["summary"]["renamed_count"]) == (0, 0)
    assert expected_ready <= {Path(row["unit"]) for row in rescan["units"]
                              if row["status"] == "already_organized"}
    assert rescan["summary"]["blocked_count"] == 0


def test_batch_organizes_default_named_photo_set_in_place_from_parent(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "2611" / "261104" / "作者A" / "260930"
    folder = selection / "新建文件夹"
    folder.mkdir(parents=True)
    for position in range(1, 16):
        (folder / f"原照片-{position:02d}.JPG").write_bytes(f"image-{position}".encode())

    preview = _preview(client, settings, selection)
    assert [(row["unit"], row["status"], row["total_files"]) for row in preview["units"]] == [
        (str(folder), "ready", 15),
    ]
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    assert list(selection.iterdir()) == [folder]
    assert sorted(path.name for path in folder.iterdir()) == [f"{position:03d}.JPG" for position in range(1, 16)]
    assert [(folder / f"{position:03d}.JPG").read_bytes() for position in range(1, 16)] == [
        f"image-{position}".encode() for position in range(1, 16)
    ]

    rescan = _preview(client, settings, selection)
    assert rescan["summary"]["blocked_count"] == 0
    assert rescan["summary"]["already_organized_count"] == 1
    assert rescan["summary"]["needed_moves"] == rescan["summary"]["renamed_count"] == 0


def test_batch_rechecks_author_loose_files_when_a_work_appears_after_preview(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else album"
    author = selection / "2602" / "260216" / "作者A"
    author.mkdir(parents=True)
    loose_video = author / "随手拍.mp4"
    loose_video.write_bytes(b"author level media")
    loose_picture = author / "散图.jpg"
    loose_picture.write_bytes(b"unassigned picture")

    preview = _preview(client, settings, selection)
    assert [(row["unit"], row["status"]) for row in preview["units"]] == [(str(author), "ready")]

    work_cover = author / "NO.001" / "封面.jpg"
    work_cover.parent.mkdir()
    work_cover.write_bytes(b"new work cover")
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert [(item["unit"], item["status"]) for item in result["items"]] == [(str(author), "conflict")]
    assert loose_video.read_bytes() == b"author level media"
    assert loose_picture.read_bytes() == b"unassigned picture"
    assert work_cover.read_bytes() == b"new work cover"
    assert not (author / "001.mp4").exists()


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


def test_batch_groups_consecutive_skip_transactions_and_keeps_result_order(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else album"
    units = [selection / f"NO.{index:03d}" for index in range(1, 114)]
    ready = {units[104], units[109]}
    for unit in units:
        unit.mkdir(parents=True)
        (unit / ("cover.JPG" if unit in ready else "001.JPG")).write_bytes(b"photo")

    preview = _preview(client, settings, selection)
    assert preview["summary"]["already_organized_count"] == 111
    assert preview["summary"]["ready_count"] == 2
    batch_id = _batch(client, preview)
    statements = []
    assert _run_next(settings, batch_id, trace_sql=statements.append)

    result_transactions = []
    results_in_transaction = 0
    for statement in statements:
        if statement.startswith("INSERT INTO task_events ") and "'media_organizer_unit_result'" in statement:
            results_in_transaction += 1
        elif statement == "COMMIT" and results_in_transaction:
            result_transactions.append(results_in_transaction)
            results_in_transaction = 0
    assert sum(result_transactions) == 113
    assert len(result_transactions) < 15
    assert max(result_transactions) <= 100
    assert {104, 105, 109, 110}.issubset(accumulate(result_transactions))

    route = f"/api/media-organizer/batches/{batch_id}"
    first_page = client.get(route, params={"page": 1, "page_size": 100}).json()
    last_page = client.get(route, params={"page": 2, "page_size": 100}).json()
    assert last_page["status"] == "completed"
    assert last_page["filtered_total"] == last_page["progress"]["current"] == last_page["progress"]["total"] == 113
    assert last_page["summary"] == {"success_count": 2, "skipped_count": 111, "conflict_count": 0, "failed_count": 0}
    assert [(row["unit"], row["status"]) for row in first_page["items"] + last_page["items"]] == [
        (str(unit), "success" if unit in ready else "skipped") for unit in units
    ]
    manifests = settings.reports_dir / "organizer-v1-executions" / batch_id
    assert {path.name for path in manifests.glob("*.json")} == {"104.json", "109.json"}


def test_resumed_batch_rejects_a_truncated_report_even_after_the_final_result(tmp_path, monkeypatch):
    from app.batch import media_organizer_jobs as jobs

    client, settings, _ = _fixture(tmp_path)
    unit = settings.data_mount / "NO.001"
    unit.mkdir()
    (unit / "cover.JPG").write_bytes(b"photo")
    preview = _preview(client, settings, unit)
    batch_id = _batch(client, preview)
    report_file = settings.reports_dir / "organizer-v1-previews" / preview["job_id"] / "units.jsonl"
    read_rows = jobs._rows

    def stop_at_eof(path):
        yield from read_rows(path)
        if path == report_file:
            raise SystemExit("Worker stopped before marking the batch complete")

    with monkeypatch.context() as patch:
        patch.setattr(jobs, "_rows", stop_at_eof)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    route = f"/api/media-organizer/batches/{batch_id}"
    assert client.get(route).json()["progress"]["current"] == 1
    report_file.write_text("", encoding="utf-8")

    db, sessions = create_engine_and_session(settings.database_path)
    try:
        assert recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")["recovered_requeued"] == 1
    finally:
        db.dispose()
    assert not _run_next(settings, batch_id)
    result = client.get(route).json()
    assert result["status"] == "failed"
    assert result["error"] == "目录预览报告不完整"
    assert result["summary"]["success_count"] == 1
    assert (unit / "001.JPG").read_bytes() == b"photo"


@pytest.mark.parametrize("phase", ["staging", "applied"])
def test_interrupted_worker_resumes_only_the_current_unit(tmp_path, monkeypatch, phase):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "Else album"
    first, skipped, second = selection / "NO.001", selection / "NO.002", selection / "NO.003"
    first.mkdir(parents=True)
    skipped.mkdir()
    second.mkdir()
    (first / "cover.webp").write_bytes(b"cover")
    (skipped / "001.JPG").write_bytes(b"photo")
    (second / "trailer.mp4").write_bytes(b"trailer")
    (second / "extra.mp4").write_bytes(b"extra")
    preview = _preview(client, settings, selection)
    batch_id = _batch(client, preview)
    move = engine._move_one
    execute = engine.execute_frozen_manifest

    def stop_while_staging(*args, **kwargs):
        result = move(*args, **kwargs)
        if args[0]["source"].startswith(str(second)):
            raise SystemExit("Worker stopped while staging")
        return result

    def stop_after_applying(manifest, **kwargs):
        result = execute(manifest, **kwargs)
        if manifest["package"] == str(second):
            raise SystemExit("Worker stopped before recording the result")
        return result

    with monkeypatch.context() as patch:
        if phase == "staging":
            patch.setattr(engine, "_move_one", stop_while_staging)
        else:
            patch.setattr(engine, "execute_frozen_manifest", stop_after_applying)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    result_path = f"/api/media-organizer/batches/{batch_id}"
    interrupted_result = client.get(result_path).json()
    assert interrupted_result["summary"]["success_count"] == 1
    assert interrupted_result["summary"]["skipped_count"] == 1
    assert interrupted_result["progress"]["current"] == 2
    inode = (first / "001.webp").stat().st_ino
    published_inodes = (
        {name: (second / name).stat().st_ino for name in ("001.mp4", "002.mp4")}
        if phase == "applied" else {}
    )
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
    assert [(row["unit"], row["status"]) for row in result["items"]] == [
        (str(first), "success"), (str(skipped), "skipped"), (str(second), "success"),
    ]
    assert (first / "001.webp").stat().st_ino == inode
    assert (second / "001.mp4").read_bytes() == b"extra"
    assert (second / "002.mp4").read_bytes() == b"trailer"
    assert all((second / name).stat().st_ino == inode for name, inode in published_inodes.items())


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
    assert preview["summary"]["totals"] == {"P": 2, "V": 2, "Other": 0}
    assert preview["summary"]["needs_assignment_count"] == 0
    assert {unit["unit"]: unit["organizer_mode"] for unit in preview["units"]} == {
        str(package): "luolcy", str(package.parent): "luolcy",
        str(work / "4K"): "semantic", str(work / "PT"): "semantic",
    }
    package_unit = next(unit for unit in preview["units"] if unit["unit"] == str(package))
    mapping = client.get(f"/api/media-organizer/previews/{preview['job_id']}/mappings/{package_unit['mapping_id']}")
    assert mapping.json()["moves"][0]["target"] == str(package / "001.JPG")
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"]["success_count"] == 4, result
    assert result["summary"]["skipped_count"] == 0, result
    assert (package / "001.JPG").read_bytes() == b"photo"
    assert (package.parent / "001.webp").read_bytes() == b"author"
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


def test_batch_promotes_same_name_work_buckets_without_rebuilding_them(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    selection = settings.data_mount / "作品"
    inner = selection / selection.name
    buckets = {"P [1 4B]": ("001.JPG", b"phot"), "V [1 4B]": ("001.MP4", b"clip")}
    for name, (filename, data) in buckets.items():
        bucket = inner / name
        bucket.mkdir(parents=True)
        (bucket / filename).write_bytes(data)
    original_ids = {name: (inner / name).stat().st_ino for name in buckets}

    preview = _preview(client, settings, selection)
    assert [(row["unit"], row["status"], row["renamed_count"]) for row in preview["units"]] == [
        (str(selection), "ready", 0),
    ]
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"]["success_count"] == 1
    assert not inner.exists()
    for name, (filename, data) in buckets.items():
        assert (selection / name).stat().st_ino == original_ids[name]
        assert (selection / name / filename).read_bytes() == data
    assert _preview(client, settings, selection)["summary"]["already_organized_count"] == 1


def test_batch_groups_leaf_photo_packs_and_author_date_categories(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    day = settings.data_mount / "261103"
    work = day / "圣诞雪饼带视频"
    author = day / "作者A"
    dated = author / "261103"
    kept = author / "260321/001.mp4"
    moved = {
        work / "图包/cover.JPG": (work / "P [1 4B]/001.JPG", b"phot"),
        work / "clip.mp4": (work / "V [1 4B]/001.mp4", b"clip"),
        dated / "图片/cover.jpg": (dated / "P [1 4B]/001.jpg", b"date"),
        dated / "视频/clip.MP4": (dated / "V [1 4B]/001.MP4", b"vids"),
    }
    for path, content in ({source: data for source, (_, data) in moved.items()}
                          | {kept: b"original batch"}).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    preview = _preview(client, settings, day)
    assert {row["unit"] for row in preview["units"] if row["status"] == "ready"} == {str(work), str(dated)}
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    result = client.get(f"/api/media-organizer/batches/{batch_id}").json()
    assert result["summary"] == {"success_count": 2, "skipped_count": 1, "conflict_count": 0, "failed_count": 0}
    for source, (destination, content) in moved.items():
        assert destination.read_bytes() == content
        assert not source.exists()
    assert not (work / "图包").exists()
    assert not (dated / "图片").exists()
    assert not (dated / "视频").exists()
    assert kept.read_bytes() == b"original batch"
    assert _preview(client, settings, day)["summary"]["already_organized_count"] == 3


@pytest.mark.parametrize(("relative", "moves"), [
    ("NO.017 粉红色制服", {
        "cover.jpg": ("P [1 4B]/001.jpg", b"phot"),
        "MOVIE/clip.MP4": ("V [1 4B]/001.MP4", b"clip"),
    }),
    ("NO.022 雷姆", {
        "IMG/cover.JPG": ("P [2 8B]/001.JPG", b"phot"),
        "P [1 4B]/001.jpg": ("P [2 8B]/002.jpg", b"prev"),
        "V [1 4B]/001.mp4": ("V [1 4B]/001.mp4", b"clip"),
    }),
    ("No.105 2024年09月 Fantia/03_2026_帖子", {
        "$1800_/cover.jpg": ("001.jpg", b"phot"),
    }),
    ("No.105 2024年09月 Fantia/17_1932_帖子", {
        "$1800_/cover.jpg": ("P [1 4B]/001.jpg", b"phot"),
        "$1800_🎬/clip.mp4": ("V [1 4B]/001.mp4", b"clip"),
    }),
    ("No.105 2024年09月 Fantia/27_1813_帖子", {
        "$1800_/cover.jpg": ("P [1 4B]/001.jpg", b"phot"),
        "$1800_🖤/clip.mp4": ("V [1 4B]/001.mp4", b"clip"),
    }),
    ("Fantia 合集/帖子标题", {
        "$2500_静止画/cover.JPG": ("P [1 4B]/001.JPG", b"phot"),
        "$2500_動画/clip.MP4": ("V [1 4B]/001.MP4", b"clip"),
    }),
    ("NO.180 千夏", {
        "GIF/motion.GiF": ("P [2 8B]/001.GiF", b"anim"),
        "P [1 4B]/001.jpg": ("P [2 8B]/002.jpg", b"phot"),
        "V [1 4B]/001.mp4": ("V [1 4B]/001.mp4", b"clip"),
    }),
    ("PoppaChan NO.032", {
        "P [1 4B]/001.jpg": ("P [2 8B]/001.jpg", b"phot"),
        "Selfies/cover.JPG": ("P [2 8B]/002.JPG", b"self"),
        "V [1 4B]/001.mp4": ("V [1 4B]/001.mp4", b"clip"),
    }),
    ("实体本补充 [1P 1V 8B]", {
        "cover.jpg": ("P [1 4B]/001.jpg", b"phot"),
        "sp/clip.MTS": ("V [1 4B]/001.MTS", b"clip"),
    }),
    ("作品 原版4K画质 [1P+2V／12B]", {
        "main.mp4": ("V [2 8B]/001.mp4", b"main"),
        "视图/cover.JPG": ("P [1 4B]/001.JPG", b"phot"),
        "视图/trailer.mp4": ("V [2 8B]/002.mp4", b"clip"),
    }),
    ("百度网盘/图片视频 [1P+2V 12B]", {
        "main.mp4": ("V [2 8B]/001.mp4", b"main"),
        "视图/P [1 4B]/001.JPG": ("P [1 4B]/001.JPG", b"phot"),
        "视图/V [1 4B]/001.mp4": ("V [2 8B]/002.mp4", b"clip"),
    }),
    ("作品 NO.059 [2P1V-12B]", {
        "P [1 4B]/001.jpg": ("P [2 8B]/002.jpg", b"phot"),
        "face/cover.JPG": ("P [2 8B]/001.JPG", b"face"),
        "V [1 4B]/001.mp4": ("V [1 4B]/001.mp4", b"clip"),
    }),
])
def test_batch_absorbs_confirmed_media_wrappers_into_their_work(tmp_path, relative, moves):
    client, settings, _ = _fixture(tmp_path)
    author = settings.data_mount / "Else/2611/261104/作者A"
    unit = author / relative
    for source, (_, payload) in moves.items():
        path = unit / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    preview = _preview(client, settings, author)
    assert [(row["unit"], row["status"]) for row in preview["units"]] == [(str(unit), "ready")]
    assert {Path(move["target"]).relative_to(unit).as_posix() for move in preview["units"][0]["sample_moves"]} == {
        destination for destination, _ in moves.values()
    }
    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    summary = client.get(f"/api/media-organizer/batches/{batch_id}").json()["summary"]
    assert summary == {"success_count": 1, "skipped_count": 0, "conflict_count": 0, "failed_count": 0}
    assert {path.relative_to(unit).as_posix(): path.read_bytes() for path in unit.rglob("*") if path.is_file()} == dict(
        moves.values()
    )
    final_parents = {Path(destination).parent for destination, _ in moves.values()}
    removed = {Path(source).parent for source in moves} - final_parents - {Path(".")}
    assert all(not (unit / folder).exists() for folder in removed)
    again = _preview(client, settings, author)
    assert [(row["unit"], row["status"]) for row in again["units"]] == [
        (str(unit), "already_organized"),
    ]


def test_fantia_pair_resume_rechecks_a_retargeted_quarantine_link(tmp_path, monkeypatch):
    from app.batch import media_package_execution as engine

    client, settings, _ = _fixture(tmp_path)
    post = settings.data_mount / "Else/2611/261109/作者A/Fantia 合集/帖子"
    photo = post / "$1800_/cover.jpg"
    video = post / "$1800_🎬/clip.mp4"
    for path, content in [(photo, b"phot"), (video, b"clip")]:
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    isolated = settings.data_mount / "isolated"
    isolated.mkdir()
    quarantine = settings.data_mount / "quarantine-link"
    quarantine.symlink_to(isolated, target_is_directory=True)
    settings.quarantine_root = quarantine
    batch_id = _batch(client, _preview(client, settings, post))
    real_move = engine._move_one

    def stop_after_first_stage(row, **kwargs):
        assert row["source"] == str(photo)
        real_move(row, **kwargs)
        raise SystemExit("Worker stopped before staging the video")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_move_one", stop_after_first_stage)
        with pytest.raises(SystemExit):
            _run_next(settings, batch_id)
    quarantine.unlink()
    quarantine.symlink_to(video.parent, target_is_directory=True)

    db, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(db, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        db.dispose()
    assert _run_next(settings, batch_id)
    summary = client.get(f"/api/media-organizer/batches/{batch_id}").json()["summary"]
    assert summary["conflict_count"] == 1, summary
    assert video.read_bytes() == b"clip"
    staged, = post.glob(".nfc-*/001.jpg")
    assert staged.read_bytes() == b"phot"


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
