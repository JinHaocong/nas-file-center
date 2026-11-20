from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    DuplicateFile,
    DuplicateGroup,
    ScanJob,
    WorkJob,
    utcnow,
)
from app.tasks.recovery import acquire_worker_ownership
from app.worker import process_work_job


def _environment(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        quarantine_root=quarantine,
        allowed_roots_raw=str(data),
        protect_last_file=True,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
    )
    client = TestClient(create_app(settings))
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client, data, client.app.state.service


def _create_hardlink_plan(service, data: Path) -> int:
    keep = data / "keep.bin"
    source = data / "source.bin"
    keep.write_bytes(b"same-content" * 128)
    source.write_bytes(b"same-content" * 128)
    with service.SessionLocal() as session:
        session.add(ScanJob(
            id=900,
            name="api-worker-validation",
            mode="normal",
            roots_json=json.dumps([str(data)]),
            status="completed",
            started_at=utcnow(),
            finished_at=utcnow(),
            total_groups=1,
            total_files_in_groups=2,
            reclaimable_bytes=keep.stat().st_size,
        ))
        group = DuplicateGroup(
            scan_job_id=900,
            content_hash="candidate-discovery-hash",
            file_size=keep.stat().st_size,
            member_count=2,
        )
        session.add(group)
        session.flush()
        for path, mtime in ((keep, 1000), (source, 2000)):
            session.add(DuplicateFile(
                group_id=group.id,
                root_id=0,
                absolute_path=str(path),
                relative_path=path.name,
                top_level_dir=str(data),
                size=path.stat().st_size,
                mtime_ns=mtime,
                device=0,
                inode=0,
            ))
        session.commit()

    preview = service.get_dedupe_preview(
        900,
        scorer_config={},
        storage_action="hardlink",
    )
    created = service.create_advanced_dedupe_plan(
        900,
        scorer_config={},
        storage_action="hardlink",
        expected_preview_digest=preview["preview_digest"],
    )
    plan_id = int(created["id"])
    assert service.freeze_plan(plan_id).status == "frozen"
    # Revalidation of a previously-ready plan must also be serialized against
    # a second validation, execution enqueue and metadata deletion.
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        plan.status = "ready"
        session.commit()
    return plan_id


def test_plan_validation_api_only_enqueues_and_worker_runs_live_probes(
    tmp_path: Path,
    monkeypatch,
):
    client, data, service = _environment(tmp_path)
    plan_id = _create_hardlink_plan(service, data)

    import app.service as service_module

    real_hardlink = service_module.probe_hardlink_between
    real_publish = service_module.probe_hardlink_capability
    probe_calls = []

    def record_hardlink(*args, **kwargs):
        probe_calls.append("hardlink-between")
        return real_hardlink(*args, **kwargs)

    def record_publish(*args, **kwargs):
        probe_calls.append("hardlink-publish")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(service_module, "probe_hardlink_between", record_hardlink)
    monkeypatch.setattr(service_module, "probe_hardlink_capability", record_publish)

    response = client.post(
        f"/api/plans/{plan_id}/validate",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 202
    queued = response.json()
    assert queued["plan_id"] == plan_id
    assert queued["status"] == "queued"
    assert isinstance(queued["work_job_id"], int)
    assert probe_calls == []
    assert not any(path.name.startswith(".__nfc_") for path in data.iterdir())

    duplicate = client.post(
        f"/api/plans/{plan_id}/validate",
        headers={"Origin": "http://testserver"},
    )
    assert duplicate.status_code == 409
    execution = client.post(
        f"/api/plans/{plan_id}/execute",
        headers={"Origin": "http://testserver"},
    )
    assert execution.status_code == 409
    deletion = client.delete(
        f"/api/plans/{plan_id}",
        headers={"Origin": "http://testserver"},
    )
    assert deletion.status_code == 409

    worker_id = f"plan-validation-worker-{queued['work_job_id']}"
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    assert process_work_job(
        service.settings,
        queued["work_job_id"],
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=worker_id,
    ) is True
    assert "hardlink-between" in probe_calls
    assert "hardlink-publish" in probe_calls

    with service.SessionLocal() as session:
        task = session.get(WorkJob, queued["work_job_id"])
        plan = session.get(BatchPlan, plan_id)
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)
        )
        assert task is not None and task.status == "completed"
        assert plan is not None and plan.status == "ready"
        assert item is not None and item.state == "validated"
    assert not any(path.name.startswith(".__nfc_") for path in data.iterdir())
