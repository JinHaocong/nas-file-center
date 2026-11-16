"""Regression for NAS long-name preservation and Worker-interrupted large Plans."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.batch.media_sort import preview_media_sort
from app.batch.media_sort_bulk_plan import create_media_sort_bulk_plan
from app.batch.media_sort_jobs import _paths
from app.batch.media_sort_resumable_plan import (
    INSERT_BATCH_SIZE,
    create_media_sort_resumable_plan,
)
from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, WorkJob
from app.path_safety import validate_mutation_destination
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.recovery import recover_interrupted_jobs
from app.worker import process_work_job


def make_settings(tmp_path):
    root = tmp_path / "data"
    config = tmp_path / "config"
    root.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=True, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    return settings, root


def login(settings):
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    return client


def test_same_long_source_name_can_move_into_new_pv_folder(monkeypatch, tmp_path):
    settings, root = make_settings(tmp_path)
    long_name = "江南" * 24 + "-full-title.mov"  # > synthetic cap, < native ext4 cap
    assert len(long_name.encode("utf-8")) > 80
    source = root / long_name
    source.write_bytes(b"movie")
    (root / "frame.jpg").write_bytes(b"photo")

    seen_pathconf: list[Path] = []

    def constrained_nas(path, key):
        assert key == "PC_NAME_MAX"
        seen_pathconf.append(Path(path))
        return 80  # Model a NAS mount reporting a conservative byte limit.

    monkeypatch.setattr(os, "pathconf", constrained_nas)
    target = root / "V" / long_name

    with pytest.raises(ValueError, match="目标文件名"):
        validate_mutation_destination(target, settings.allowed_roots)
    assert validate_mutation_destination(
        target, settings.allowed_roots, existing_media_source=source,
    ) == target
    assert seen_pathconf and all(path != root / "V" for path in seen_pathconf)
    assert root in seen_pathconf

    preview = preview_media_sort(
        root, allowed_roots=settings.allowed_roots,
        quarantine_root=settings.quarantine_root, smart_skip=False,
    )
    assert preview["count"] == 2
    assert preview["conflict_count"] == 0
    movie = next(row for row in preview["items"] if row["media_kind"] == "video")
    assert movie["target"] == str(target)
    assert not (root / "V").exists()

    payload = tmp_path / "preview.jsonl"
    with payload.open("w", encoding="utf-8") as stream:
        for row in preview["items"]:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    service = FileCenterService(settings)
    plan = create_media_sort_bulk_plan(
        service.SessionLocal, settings, items_file=payload,
        summary={
            "count": 2, "ready_count": 2, "conflict_count": 0,
            "recursive": False, "smart_skip": False,
        },
        preview_job_id=1,
    )
    assert plan.status == "draft"
    assert service.freeze_plan(plan.id).status == "frozen"
    assert service.validate_plan(plan.id)["status"] == "ready"
    job = service.enqueue_plan_execution(plan.id)
    assert process_work_job(settings, job["work_job_id"]) is True
    assert (root / "V" / long_name).read_bytes() == b"movie"
    assert (root / "P" / "frame.jpg").read_bytes() == b"photo"
    assert not source.exists()


def test_long_name_exception_rejects_other_target_and_symlink(monkeypatch, tmp_path):
    settings, root = make_settings(tmp_path)
    name = "media-" + "x" * 130 + ".mov"
    source = root / name
    source.write_bytes(b"video")
    monkeypatch.setattr(os, "pathconf", lambda *_: 80)

    targets = [
        root / "Other" / name,
        root / "V" / (name.replace("media-", "renamed-")),
        root / "sub" / "V" / name,
    ]
    for target in targets:
        with pytest.raises(ValueError, match="目标文件名"):
            validate_mutation_destination(
                target, settings.allowed_roots, existing_media_source=source,
            )
    outside = tmp_path / "outside" / "V" / name
    with pytest.raises(ValueError, match="outside configured roots"):
        validate_mutation_destination(
            outside, settings.allowed_roots, existing_media_source=source,
        )
    (root / "V").symlink_to(root)
    with pytest.raises(ValueError, match="目标文件名"):
        validate_mutation_destination(
            root / "V" / name, settings.allowed_roots, existing_media_source=source,
        )


class _SimulatedPowerLoss(BaseException):
    pass


def test_90k_style_plan_can_resume_after_crash_without_partial_draft(tmp_path):
    settings, root = make_settings(tmp_path)
    media_count = INSERT_BATCH_SIZE + 85
    for index in range(media_count):
        suffix = ".jpg" if index % 2 else ".mp4"
        (root / f"video_{index:05d}{suffix}").write_bytes(b"media")

    client = login(settings)
    queued = client.post("/api/media-sort/previews", json={
        "parent": str(root), "recursive": False, "smart_skip": False,
    })
    assert queued.status_code == 200, queued.text
    preview_id = queued.json()["job_id"]
    assert process_work_job(settings, preview_id) is True

    page = client.get(f"/api/media-sort/previews/{preview_id}")
    assert page.status_code == 200
    summary = page.json()["summary"]
    assert summary["ready_count"] == media_count

    result = client.post(f"/api/media-sort/previews/{preview_id}/plan")
    assert result.status_code == 200, result.text
    plan_job_id = result.json()["job_id"]
    service = FileCenterService(settings)
    items_file, _, _ = _paths(settings, preview_id)

    # Model an old Worker killed after committing 750 records but before its
    # final status/Plan publication; Python process crashes do not run cleanup.
    with service.SessionLocal() as session:
        job = session.get(WorkJob, plan_job_id)
        job.status = "running"
        session.commit()
    context = JobContext(service.engine, service.SessionLocal, plan_job_id)
    context.checkpoint(
        progress_total=media_count,
        checkpoint_data={"schema_version": 1, "kind": "media-sort-plan",
                         "preview_job_id": preview_id,
                         "resume_mode": "committed_plan_batches"},
    )

    def fail_after_first_commit(committed, total):
        if committed >= INSERT_BATCH_SIZE:
            raise _SimulatedPowerLoss("simulated Worker process crash")

    with pytest.raises(_SimulatedPowerLoss):
        create_media_sort_resumable_plan(
            service.SessionLocal, settings,
            job_id=plan_job_id, preview_job_id=preview_id,
            items_file=items_file, summary=summary,
            skip_conflicts=False, on_committed=fail_after_first_commit,
        )
    with service.SessionLocal() as session:
        stage = session.scalar(select(BatchPlan).where(BatchPlan.status == "building"))
        assert stage is not None
        stage_id = stage.id
        assert session.scalar(select(func.count(BatchPlanItem.id)).where(
            BatchPlanItem.plan_id == stage_id,
        )) == INSERT_BATCH_SIZE
        assert session.get(WorkJob, plan_job_id).status == "running"

    plans = client.get("/api/plans").json()
    assert all(entry["id"] != stage_id for entry in plans["items"])
    assert client.post(f"/api/plans/{stage_id}/freeze").status_code == 409
    assert client.post(f"/api/plans/{stage_id}/execute").status_code == 409

    recovered = recover_interrupted_jobs(service.engine, service.SessionLocal)
    assert recovered["recovered_requeued"] == 1
    with service.SessionLocal() as session:
        assert session.get(WorkJob, plan_job_id).status == "queued"

    assert process_work_job(settings, plan_job_id) is True
    generated = client.get(f"/api/media-sort/plan-jobs/{plan_job_id}").json()
    assert generated["status"] == "completed"
    assert generated["plan_id"] == stage_id
    assert generated["progress"]["current"] == media_count
    with service.SessionLocal() as session:
        stage = session.get(BatchPlan, stage_id)
        assert stage.status == "draft"
        rows = session.scalars(select(BatchPlanItem).where(
            BatchPlanItem.plan_id == stage_id,
        )).all()
        assert len(rows) == media_count
        assert sorted(row.sequence for row in rows) == list(range(1, media_count + 1))
        assert session.scalar(select(func.count(BatchPlan.id)).where(
            BatchPlan.kind == "media-sort",
        )) == 1

    assert client.post(f"/api/plans/{stage_id}/stage-tasks/freeze").status_code == 200
    assert all((root / f"video_{index:05d}{'.jpg' if index % 2 else '.mp4'}").exists()
               for index in range(media_count))


def test_resumed_plan_that_already_published_does_not_duplicate(tmp_path):
    settings, root = make_settings(tmp_path)
    (root / "a.jpg").write_bytes(b"a")
    (root / "b.mp4").write_bytes(b"b")
    client = login(settings)
    prev = client.post("/api/media-sort/previews", json={
        "parent": str(root), "recursive": False, "smart_skip": False,
    }).json()["job_id"]
    assert process_work_job(settings, prev)
    pending = client.post(f"/api/media-sort/previews/{prev}/plan").json()["job_id"]
    service = FileCenterService(settings)
    with service.SessionLocal() as session:
        job = session.get(WorkJob, pending)
        job.status = "running"
        session.commit()
    context = JobContext(service.engine, service.SessionLocal, pending)
    context.checkpoint(checkpoint_data={"schema_version": 1, "kind": "media-sort-plan"})
    items_file, _, _ = _paths(settings, prev)
    summary = client.get(f"/api/media-sort/previews/{prev}").json()["summary"]
    result_id = create_media_sort_resumable_plan(
        service.SessionLocal, settings, job_id=pending, preview_job_id=prev,
        items_file=items_file, summary=summary, skip_conflicts=False,
    )
    assert recover_interrupted_jobs(service.engine, service.SessionLocal)["recovered_requeued"] == 1
    assert process_work_job(settings, pending) is True
    with service.SessionLocal() as session:
        assert session.get(WorkJob, pending).status == "completed"
        assert session.scalar(select(func.count(BatchPlan.id))) == 1
        assert session.get(BatchPlan, result_id).status == "draft"
