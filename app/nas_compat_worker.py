"""Opt-in NAS Worker profile: UID 0, shared GID 10000, DAC_OVERRIDE only.

The API never uses this profile and remains non-root with /data mounted read-only.
The Worker receives the one DAC capability needed to access mixed-owner NAS
files. No SETUID/SETGID, CHOWN, SYS_ADMIN, privileged mode or Docker socket.
This is a deliberate whole-Worker trust trade-off: every Worker WorkJob can use
the capability. Enable only in the separate NAS compatibility deployment.
"""
from __future__ import annotations

import os

_ENV_ENABLED = "NFC_NAS_COMPAT_ROOT_WORKER_ENABLED"
_SHARED_GID = 10000
_CAP_DAC_OVERRIDE = 1 << 1


def _status() -> dict[str, str]:
    with open("/proc/self/status", encoding="ascii") as stream:
        return {
            key: value.strip()
            for line in stream
            if ":" in line
            for key, value in (line.split(":", 1),)
        }


def is_nas_compat_root_worker(settings=None) -> bool:
    """True only for the exact opt-in UID:GID/capability profile."""
    if settings is None:
        enabled = os.environ.get(_ENV_ENABLED, "false") == "true"
    else:
        enabled = getattr(settings, "nas_compat_root_worker_enabled", False) is True
    if not enabled or os.environ.get(_ENV_ENABLED, "false") != "true":
        return False
    try:
        if (os.getresuid() != (0, 0, 0)
                or os.getresgid() != (_SHARED_GID, _SHARED_GID, _SHARED_GID)
                or any(group != _SHARED_GID for group in os.getgroups())
                or os.environ.get("NFC_SHARED_CONFIG_GID") != str(_SHARED_GID)
                or os.environ.get("MEDIA_ORGANIZER_EXECUTION_MODE") != "maintenance_window"):
            return False
        status = _status()
        expected = {
            "CapInh": 0, "CapPrm": _CAP_DAC_OVERRIDE,
            "CapEff": _CAP_DAC_OVERRIDE, "CapBnd": _CAP_DAC_OVERRIDE,
            "CapAmb": 0, "NoNewPrivs": 1,
        }
        return all(
            int(status.get(name, "-1"), 16 if name.startswith("Cap") else 10) == value
            for name, value in expected.items()
        )
    except (OSError, ValueError, KeyError):
        return False


def verify_worker_runtime(settings) -> None:
    """Fail closed before SQLite/scheduler starts if root mode was requested incorrectly."""
    enabled = getattr(settings, "nas_compat_root_worker_enabled", False) is True
    env_enabled = os.environ.get(_ENV_ENABLED, "false") == "true"
    if enabled != env_enabled:
        raise PermissionError("NAS_COMPAT_ROOT_WORKER_ENABLED differs from loaded Worker settings")
    if not enabled:
        return
    if getattr(settings, "media_organizer_execution_mode", "strict") != "maintenance_window":
        raise PermissionError("NAS compatibility Root Worker requires maintenance_window mode")
    if not is_nas_compat_root_worker(settings):
        try:
            status = _status()
            observed = {
                "uid": os.getresuid(), "gid": os.getresgid(), "groups": os.getgroups(),
                "CapInh": status.get("CapInh"), "CapPrm": status.get("CapPrm"),
                "CapEff": status.get("CapEff"), "CapBnd": status.get("CapBnd"),
                "CapAmb": status.get("CapAmb"), "NoNewPrivs": status.get("NoNewPrivs"),
                "shared_gid": os.environ.get("NFC_SHARED_CONFIG_GID"),
                "execution_mode": os.environ.get("MEDIA_ORGANIZER_EXECUTION_MODE"),
            }
        except Exception as exc:
            observed = {"diagnostic_error": type(exc).__name__}
        raise PermissionError(
            "NAS compatibility Worker must run as 0:10000 with only effective DAC_OVERRIDE, "
            f"no extra supplementary groups and no-new-privileges; observed={observed}"
        )
