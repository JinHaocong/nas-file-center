"""No original NAS access. Verify privilege only around approved WorkJobs."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import nas_compat_launcher as compat


def _settings(*, enabled=True):
    return SimpleNamespace(
        allowed_roots=[Path("/data")],
        allow_mutation=enabled, allow_delete=enabled,
        media_organizer_execution_enabled=enabled,
    )


def _job(kind, *, job_id=4, approved=True, status="running", mode="maintenance_window",
         unit="/data/collection"):
    state = {"execution_mode": mode}
    state["selection" if kind == "media-organizer-preview" else "unit"] = unit
    if approved:
        state.update(approved_job_id=job_id, confirmation="TEST_ONLY",
                     maintenance_window_confirmed=True)
    return SimpleNamespace(id=job_id, kind=kind, status=status,
                           state_json=json.dumps(state))


def _mock_parked(monkeypatch):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_ENABLED", "true")
    monkeypatch.setenv("MEDIA_ORGANIZER_EXECUTION_MODE", "maintenance_window")
    monkeypatch.setattr(compat, "verify_optional_worker_runtime", lambda: None)
    observed = []
    monkeypatch.setattr(compat, "_set_job_dac_effective", lambda enabled: observed.append(enabled))
    return observed


def test_ordinary_workjob_cannot_enable_effective_dac(monkeypatch):
    observed = _mock_parked(monkeypatch)
    with compat.scoped_nas_compat_job(_job("quarantine-restore"), _settings()):
        assert observed == []
    assert observed == []


def test_scoped_preview_revokes_effective_dac_after_success(monkeypatch):
    observed = _mock_parked(monkeypatch)
    with compat.scoped_nas_compat_job(
        _job("media-organizer-preview", approved=False), _settings(enabled=False),
    ):
        assert observed == [True]
    assert observed == [True, False]


def test_execution_handler_exception_still_revokes(monkeypatch):
    observed = _mock_parked(monkeypatch)
    with pytest.raises(RuntimeError, match="interrupted"):
        with compat.scoped_nas_compat_job(_job("media-organizer-execute"), _settings()):
            assert observed == [True]
            raise RuntimeError("interrupted")
    assert observed == [True, False]


@pytest.mark.parametrize("kind", ["media-organizer-execute", "media-organizer-cleanup"])
def test_unapproved_mutations_never_enable_dac(monkeypatch, kind):
    observed = _mock_parked(monkeypatch)
    for work,settings in (
        (_job(kind, approved=False), _settings()),
        (_job(kind), _settings(enabled=False)),
        (_job(kind, status="failed"), _settings()),
        (_job(kind, mode="strict"), _settings()),
        (_job(kind, unit="/etc/passwd"), _settings()),
        (_job(kind, unit="/data/../etc"), _settings()),
        (_job(kind, job_id=0), _settings()),
    ):
        with pytest.raises(PermissionError):
            with compat.scoped_nas_compat_job(work, settings):
                pytest.fail("unapproved mutation received capability")
    assert observed == []


def test_default_mode_does_not_inspect_media_scope(monkeypatch):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_ENABLED", "false")
    monkeypatch.setattr(compat, "_approved_media_job", lambda *_: pytest.fail("default mode inspected scope"))
    with compat.scoped_nas_compat_job(_job("media-organizer-execute", approved=False), _settings()):
        pass


def test_runtime_identity_phase_requirements(monkeypatch):
    monkeypatch.setattr(compat.os, "getresuid", lambda: (10002, 10002, 10002))
    monkeypatch.setattr(compat.os, "getresgid", lambda: (10000, 10000, 10000))
    monkeypatch.setattr(compat.os, "getgroups", lambda: [])
    monkeypatch.setattr(compat, "_status", lambda: {"NoNewPrivs": "1"})
    for phase,caps in (
        ("handoff", (2, 2, 2, 0xc2, 2)),
        ("parked", (0, 2, 0, 0xc2, 0)),
        ("scoped", (0, 2, 2, 0xc2, 0)),
    ):
        monkeypatch.setattr(compat, "_capsets", lambda caps=caps: caps)
        compat.assert_nas_compat_worker_identity(10002, 10000, phase=phase)
        for other in {"handoff", "parked", "scoped"} - {phase}:
            with pytest.raises(PermissionError, match="capability set"):
                compat.assert_nas_compat_worker_identity(10002, 10000, phase=other)


def test_uncertain_dac_enable_terminates_before_work(monkeypatch):
    _mock_parked(monkeypatch)
    monkeypatch.setattr(compat, "_set_job_dac_effective",
        lambda enabled: (_ for _ in ()).throw(PermissionError("post-capset uncertain")))
    monkeypatch.setattr(compat.os, "_exit",
        lambda code: (_ for _ in ()).throw(SystemExit(code)))
    with pytest.raises(SystemExit) as exited:
        with compat.scoped_nas_compat_job(_job("media-organizer-execute"), _settings()):
            pytest.fail("handler must not run after uncertain DAC enable")
    assert exited.value.code == 70


def test_normal_job_capability_leak_terminates_instead_of_logging(monkeypatch):
    _mock_parked(monkeypatch)
    checks = [None, PermissionError("ordinary job unexpectedly elevated")]
    def verify():
        item = checks.pop(0)
        if item is not None:
            raise item
    monkeypatch.setattr(compat, "verify_optional_worker_runtime", verify)
    monkeypatch.setattr(compat.os, "_exit",
        lambda code: (_ for _ in ()).throw(SystemExit(code)))
    with pytest.raises(SystemExit) as exited:
        with compat.scoped_nas_compat_job(_job("quarantine-restore"), _settings()):
            pass
    assert exited.value.code == 70
