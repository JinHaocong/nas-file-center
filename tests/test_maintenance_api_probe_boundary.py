from __future__ import annotations

import json

import pytest

from app.models import WorkJob
from app.service import StateConflictError
from test_storage_optimization_api import _client, _login
from test_storage_optimization_dedupe_plan import storage_dedupe_env, _seed_duplicate


def _reserve(service, unit):
    with service.SessionLocal() as session:
        job = WorkJob(
            kind="media-organizer-execute", status="failed",
            state_json=json.dumps({
                "execution_mode": "maintenance_window",
                "maintenance_window_confirmed": True,
                "unit": str(unit), "selection": str(unit), "preview_job_id": 1,
            }),
            checkpoint_json="{}",
        )
        session.add(job)
        session.flush()
        job.checkpoint_json = json.dumps({
            "schema_version": 1, "phase": "frozen", "frozen_job_id": job.id,
            "unit": str(unit), "execution_mode": "maintenance_window",
            "manifest_checksum": "a" * 64,
        })
        session.commit()


def test_api_storage_probe_cannot_write_during_unfinished_maintenance(tmp_path):
    client, data = _client(tmp_path)
    _login(client, "admin", "AdminPassword123!")
    _reserve(client.app.state.service, data)
    before = data.stat().st_ctime_ns
    response = client.post(
        "/api/storage-optimization/capabilities",
        json={"directory": str(data)},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 409, response.text
    assert data.stat().st_ctime_ns == before
    assert list(data.iterdir()) == []


def test_plan_validation_cannot_run_write_probes_during_maintenance(storage_dedupe_env):
    service, data = storage_dedupe_env
    _seed_duplicate(service, data)
    preview = service.get_dedupe_preview(900, scorer_config={}, storage_action="hardlink")
    plan = service.create_advanced_dedupe_plan(
        900, scorer_config={}, storage_action="hardlink",
        expected_preview_digest=preview["preview_digest"],
    )
    service.freeze_plan(plan["id"])
    _reserve(service, data)
    before = data.stat().st_ctime_ns
    with pytest.raises(StateConflictError, match="maintenance|Maintenance"):
        service.validate_plan(plan["id"])
    assert data.stat().st_ctime_ns == before
    assert sorted(p.name for p in data.iterdir()) == ["left.bin", "right.bin"]
