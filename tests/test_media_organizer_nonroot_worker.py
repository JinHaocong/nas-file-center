"""V1.6 Worker privilege isolation is a hard gate, not an operator checkbox."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.batch import media_organizer_execute_jobs as execution


def _enabled():
    return SimpleNamespace(
        media_organizer_execution_enabled=True,
        allow_mutation=True,
        allow_delete=True,
        media_organizer_namespace_quiescence_ack=True,
    )


def _job():
    return SimpleNamespace(
        id=1,
        state_json=json.dumps({"preview_job_id": 1, "unit": "/data/unit"}),
    )


def test_root_worker_is_rejected_before_any_manifest_or_media_access(monkeypatch):
    monkeypatch.setattr(execution.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        execution, "_literal_unit",
        lambda *_args: pytest.fail("root worker attempted to resolve a media path"),
    )
    with pytest.raises(PermissionError, match="dedicated non-root Worker"):
        execution.MediaOrganizerExecuteHandler().run(
            _job(), SimpleNamespace(worker_id="test-lease"), _enabled()
        )


def test_unprivileged_worker_proceeds_to_frozen_manifest_checks(monkeypatch):
    monkeypatch.setattr(execution.os, "geteuid", lambda: 10001)

    def expected_next_stage(*_args):
        raise RuntimeError("reached unit validation without mutating files")

    monkeypatch.setattr(execution, "_literal_unit", expected_next_stage)
    with pytest.raises(RuntimeError, match="reached unit validation"):
        execution.MediaOrganizerExecuteHandler().run(
            _job(), SimpleNamespace(worker_id="test-lease"), _enabled()
        )


def test_unacknowledged_namespace_still_fails_closed_for_nonroot_worker(monkeypatch):
    monkeypatch.setattr(execution.os, "geteuid", lambda: 10001)
    settings = _enabled()
    settings.media_organizer_namespace_quiescence_ack = False
    with pytest.raises(ValueError, match="NAMESPACE_QUIESCENCE_ACK"):
        execution.MediaOrganizerExecuteHandler().run(
            _job(), SimpleNamespace(worker_id="test-lease"), settings
        )


def test_worker_lease_is_still_mandatory_after_root_guard(monkeypatch):
    monkeypatch.setattr(execution.os, "geteuid", lambda: 10001)
    with pytest.raises(PermissionError, match="exclusive Worker lease"):
        execution.MediaOrganizerExecuteHandler().run(
            _job(), SimpleNamespace(worker_id=None), _enabled()
        )
