"""V1.6.2 optional NAS Worker identity gates; no media, Docker or root calls."""
import os

import pytest

from app import nas_compat_launcher as compat


def test_normal_worker_does_not_require_elevated_identity(monkeypatch):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_ENABLED", "false")
    monkeypatch.setattr(compat, "_uid", lambda *_: pytest.fail("normal mode inspected compat IDs"))
    compat.verify_optional_worker_runtime()


def test_unknown_enable_value_rejected(monkeypatch):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_ENABLED", "yes")
    with pytest.raises(PermissionError, match="unsupported enable"):
        compat.verify_optional_worker_runtime()


def test_optional_worker_refuses_missing_capability_even_with_valid_uid(monkeypatch):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_ENABLED", "true")
    monkeypatch.setenv("MEDIA_ORGANIZER_EXECUTION_MODE", "maintenance_window")
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_UID", "10002")
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_GID", "10000")
    monkeypatch.setattr(compat.os, "getresuid", lambda: (10002, 10002, 10002))
    monkeypatch.setattr(compat.os, "getresgid", lambda: (10000, 10000, 10000))
    monkeypatch.setattr(compat.os, "getgroups", lambda: [])
    monkeypatch.setattr(compat, "_status", lambda: {"NoNewPrivs": "1"})
    monkeypatch.setattr(compat, "_capsets", lambda: (0, 0, 0, 0, 0))
    with pytest.raises(PermissionError, match="capability set"):
        compat.verify_optional_worker_runtime()


@pytest.mark.parametrize("caps", [
    (2, 2, 0, 0xc2, 2),  # no effective DAC
    (2, 2, 2, 0xc2, 0),  # no ambient DAC
    (2, 2, 2, 0xffff, 2),  # extra bounding bits
    (2, 3, 2, 0xc2, 2),  # extra permitted bit
])
def test_optional_worker_rejects_incomplete_or_extra_caps(monkeypatch, caps):
    monkeypatch.setattr(compat.os, "getresuid", lambda: (10002, 10002, 10002))
    monkeypatch.setattr(compat.os, "getresgid", lambda: (10000, 10000, 10000))
    monkeypatch.setattr(compat.os, "getgroups", lambda: [])
    monkeypatch.setattr(compat, "_status", lambda: {"NoNewPrivs": "1"})
    monkeypatch.setattr(compat, "_capsets", lambda: caps)
    with pytest.raises(PermissionError, match="capability set"):
        compat.assert_nas_compat_worker_identity(10002, 10000)


def test_optional_worker_accepts_exact_nonroot_profile(monkeypatch):
    monkeypatch.setattr(compat.os, "getresuid", lambda: (10002, 10002, 10002))
    monkeypatch.setattr(compat.os, "getresgid", lambda: (10000, 10000, 10000))
    monkeypatch.setattr(compat.os, "getgroups", lambda: [])
    monkeypatch.setattr(compat, "_status", lambda: {"NoNewPrivs": "1"})
    monkeypatch.setattr(compat, "_capsets", lambda: (2, 2, 2, 0xc2, 2))
    compat.assert_nas_compat_worker_identity(10002, 10000)


def test_privileged_entrypoint_refuses_unapproved_mode(monkeypatch):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_ENABLED", "true")
    monkeypatch.setenv("MEDIA_ORGANIZER_EXECUTION_MODE", "strict")
    monkeypatch.setattr(compat, "_drop_to_worker", lambda *_: pytest.fail("unsafe handoff"))
    with pytest.raises(PermissionError, match="maintenance-window"):
        compat.main()


def test_privileged_entrypoint_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NFC_NAS_COMPAT_WORKER_ENABLED", raising=False)
    monkeypatch.setattr(compat, "_drop_to_worker", lambda *_: pytest.fail("unsafe handoff"))
    with pytest.raises(PermissionError, match="explicit opt-in"):
        compat.main()


@pytest.mark.parametrize("value", ["", "-1", "0", "root", "0:0", "١٠٠٠٢", "99999999999999999"])
def test_numeric_identity_must_be_positive_ascii_unprivileged(monkeypatch, value):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_UID", value)
    with pytest.raises(PermissionError, match="invalid"):
        compat._uid("NFC_NAS_COMPAT_WORKER_UID")


def test_enabled_worker_runtime_rejects_strict_even_if_capabilities_present(monkeypatch):
    monkeypatch.setenv("NFC_NAS_COMPAT_WORKER_ENABLED", "true")
    monkeypatch.setenv("MEDIA_ORGANIZER_EXECUTION_MODE", "strict")
    monkeypatch.setattr(compat, "_uid", lambda *_: pytest.fail("wrong mode inspected UID"))
    with pytest.raises(PermissionError, match="not maintenance-window mode"):
        compat.verify_optional_worker_runtime()
