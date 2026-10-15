"""Synthetic archive channel preflight tests: no NAS, task, or output writes."""
from __future__ import annotations

from types import SimpleNamespace
import zipfile

from fastapi import HTTPException
import pytest

from app.archive_recovery import router as recovery_router


@pytest.mark.parametrize("channel_ready", [False, True])
def test_preflight_reports_api_side_tmpfs_readiness(tmp_path, monkeypatch, channel_ready):
    archive = tmp_path / "harmless.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("example.txt", "demo")
    monkeypatch.setattr(recovery_router, "qualified_source", lambda request, raw: archive)
    monkeypatch.setattr(recovery_router, "tmpfs_available", lambda: channel_ready)
    request = SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(allow_mutation=True))
    ))
    outcome = recovery_router.check_archive(request, recovery_router.RecoveryRequest(source=str(archive)))
    assert outcome["format"] == "zip"
    assert outcome["password_channel_available"] is channel_ready
    assert outcome["dependency_available"] is True


def test_password_start_blocks_before_creating_output_or_job(tmp_path, monkeypatch):
    archive = tmp_path / "protected.7z"
    archive.write_bytes(b"synthetic")
    monkeypatch.setattr(recovery_router, "qualified_source", lambda request, raw: archive)
    monkeypatch.setattr(recovery_router, "detect_format", lambda source: "7z")
    monkeypatch.setattr(recovery_router, "tmpfs_available", lambda: False)
    request = SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(allow_mutation=True))
    ))
    with pytest.raises(HTTPException) as error:
        recovery_router.start_archive(request, recovery_router.RecoveryRequest(
            source=str(archive), password="synthetic-do-not-store"))
    assert error.value.status_code == 503
    assert str(error.value.detail).startswith("PASSWORD_CHANNEL_UNAVAILABLE")
    assert "synthetic-do-not-store" not in str(error.value.detail)
    assert list(tmp_path.iterdir()) == [archive]
