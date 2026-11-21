"""Default-off and exact-identity tests for the simple NAS Root Worker profile."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import nas_compat_worker as compat


def _settings(enabled=True):
    return SimpleNamespace(
        nas_compat_root_worker_enabled=enabled,
        media_organizer_execution_mode="maintenance_window",
    )


def _root_profile(monkeypatch, *, caps=None, groups=None, uid=0, gid=10000, mode="maintenance_window"):
    monkeypatch.setenv("NFC_NAS_COMPAT_ROOT_WORKER_ENABLED", "true")
    monkeypatch.setenv("NFC_SHARED_CONFIG_GID", "10000")
    monkeypatch.setenv("MEDIA_ORGANIZER_EXECUTION_MODE", mode)
    monkeypatch.setattr(compat.os, "getresuid", lambda: (uid, uid, uid))
    monkeypatch.setattr(compat.os, "getresgid", lambda: (gid, gid, gid))
    monkeypatch.setattr(compat.os, "getgroups", lambda: [] if groups is None else groups)
    monkeypatch.setattr(compat, "_status", lambda: caps or {
        "CapInh": "0", "CapPrm": "2", "CapEff": "2",
        "CapBnd": "2", "CapAmb": "0", "NoNewPrivs": "1",
    })


def test_compatibility_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NFC_NAS_COMPAT_ROOT_WORKER_ENABLED", raising=False)
    assert not compat.is_nas_compat_root_worker(_settings(False))
    compat.verify_worker_runtime(_settings(False))


def test_exact_root_0_10000_dac_override_profile_is_accepted(monkeypatch):
    _root_profile(monkeypatch)
    assert compat.is_nas_compat_root_worker(_settings(True))
    compat.verify_worker_runtime(_settings(True))


@pytest.mark.parametrize("change", [
    {"CapEff": "0"},
    {"CapEff": "3"},
    {"CapPrm": "3"},
    {"CapBnd": "3"},
    {"CapInh": "2"},
    {"CapAmb": "2"},
    {"NoNewPrivs": "0"},
])
def test_any_capability_deviation_is_rejected(monkeypatch, change):
    caps = {"CapInh":"0","CapPrm":"2","CapEff":"2","CapBnd":"2","CapAmb":"0","NoNewPrivs":"1"}
    caps.update(change)
    _root_profile(monkeypatch, caps=caps)
    assert not compat.is_nas_compat_root_worker(_settings(True))
    with pytest.raises(PermissionError, match="0:10000"):
        compat.verify_worker_runtime(_settings(True))


@pytest.mark.parametrize("uid,gid,groups", [
    (10002, 10000, []),
    (0, 0, []),
    (0, 10000, [0]),
    (0, 10000, [10001]),
])
def test_wrong_uid_gid_or_supplementary_groups_are_rejected(monkeypatch, uid, gid, groups):
    _root_profile(monkeypatch, uid=uid, gid=gid, groups=groups)
    assert not compat.is_nas_compat_root_worker(_settings(True))


def test_root_worker_profile_requires_maintenance_window(monkeypatch):
    _root_profile(monkeypatch, mode="strict")
    assert not compat.is_nas_compat_root_worker(_settings(True))
    with pytest.raises(PermissionError):
        compat.verify_worker_runtime(_settings(True))


def test_api_cannot_enable_root_worker_profile(monkeypatch):
    _root_profile(monkeypatch)
    monkeypatch.setenv("NFC_NAS_COMPAT_ROOT_WORKER_ENABLED", "false")
    assert not compat.is_nas_compat_root_worker(_settings(True))


def test_docker_primary_gid_may_appear_in_supplementary_group_list(monkeypatch):
    _root_profile(monkeypatch, groups=[10000])
    assert compat.is_nas_compat_root_worker(_settings(True))
    compat.verify_worker_runtime(_settings(True))
