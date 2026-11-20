"""Regression for namespace hold at the former final name-use boundaries.

Temporary fixtures use a synthetic issuer only to prepare retained originals.
The operation under test has no production custody grant. The injected
replacement would occur immediately before a real syscall if that hold failed.
"""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.batch import media_organizer_authority as authority
from app.batch import media_organizer_custody as custody
from app.batch import media_organizer_publish as publishing
from app.batch import media_organizer_finalize as finalizing
from tests.test_media_organizer_maintenance_authority import grouped, publish
from tests.test_media_organizer_grouped_worker_custody import _install_issuer


def _site(tmp_path):
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    unit = tmp_path / "media" / "unit"
    unit.mkdir(parents=True, mode=0o700)
    settings = SimpleNamespace(
        config_dir=config, reports_dir=config / "reports", allowed_roots=[unit.parent],
        quarantine_root=unit.parent / "trash", media_organizer_execution_mode="maintenance_window",
        allow_mutation=True, allow_delete=True, media_organizer_execution_enabled=True,
        media_organizer_namespace_quiescence_ack=True,
    )
    return settings, unit


def _contents(unit):
    return {
        str(path.relative_to(unit)): (path.stat().st_ino, path.read_bytes())
        for path in unit.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("kind", ["original", "wrapper"])
def test_cleanup_hold_prevents_late_replacement_mutation(tmp_path, monkeypatch, kind):
    settings, unit = _site(tmp_path)
    manifest, frozen, parents = grouped((settings, unit))
    with monkeypatch.context() as preparation_only:
        _install_issuer(preparation_only, tmp_path, allowed=True)
        plan = publish(authority, settings, unit, manifest, frozen, parents)
    before = _contents(unit)
    path = unit / "P1" / "image.jpg" if kind == "original" else unit / "P1"
    detached = tmp_path / "owned-detached"
    injected = []
    original_unlink, original_rmdir = os.unlink, os.rmdir

    def at_boundary(name, *, dir_fd=None):
        actual = original_unlink if kind == "original" else original_rmdir
        resolved = (Path(os.readlink(f"/proc/self/fd/{dir_fd}")) / name
                    if dir_fd is not None else Path(name))
        if resolved == path and not injected:
            path.rename(detached)
            if kind == "original":
                path.write_bytes(b"foreign-preserve")
            else:
                path.mkdir(mode=0o700)
            injected.append(path.stat().st_ino)
        return actual(name, dir_fd=dir_fd)

    monkeypatch.setattr(finalizing.os, "unlink" if kind == "original" else "rmdir", at_boundary)
    with pytest.raises(custody.NamespaceCustodyUnavailable, match="not proven"):
        with authority.acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
            finalizing.finish_deferred_cleanup(
                manifest, frozen_manifest_path=frozen, allowed_roots=settings.allowed_roots,
                confirmation=finalizing.cleanup_confirmation(9, str(unit), plan["plan_sha256"]),
                custody=session,
            )
    assert injected == [], "unproven custody reached a name-based destructive syscall"
    assert _contents(unit) == before
    assert not finalizing._journal_path(frozen).exists()
    assert path.exists()


def test_group_hold_prevents_adopting_an_unwitnessed_replacement(tmp_path, monkeypatch):
    settings, unit = _site(tmp_path)
    manifest, frozen, parents = grouped((settings, unit))
    before = _contents(unit)
    group = Path(manifest["groups"][0]["destination"])
    detached = tmp_path / "new-group-detached"
    actual_mkdir = os.mkdir
    injected = []

    def create_then_replace(name, mode=0o777, *, dir_fd=None):
        result = actual_mkdir(name, mode, dir_fd=dir_fd)
        if dir_fd is not None and str(name) == group.name and not injected:
            group.rename(detached)
            actual_mkdir(name, 0o700, dir_fd=dir_fd)
            injected.append(group.stat().st_ino)
        return result

    monkeypatch.setattr(publishing.os, "mkdir", create_then_replace)
    with pytest.raises(custody.NamespaceCustodyUnavailable, match="not proven"):
        publish(authority, settings, unit, manifest, frozen, parents)
    assert injected == [], "unproven custody reached group mkdir/open"
    assert _contents(unit) == before
    assert not group.exists()
    assert not (unit / manifest["stage_directory"]).exists()
