"""Optional, fail-closed root-startup -> non-root NAS capability handoff.

This is NOT invoked by the default Compose deployment. A future, explicitly
reviewed NAS compatibility profile may execute this as the Worker's entrypoint.
The Python Worker continues as a distinct non-root UID; the process receives
only effective CAP_DAC_OVERRIDE, not UID 0 or full container capabilities.

IMPORTANT: DAC_OVERRIDE is still powerful across ALL writable Worker mounts.
This handoff proves only a possible execution identity, not namespace custody,
safety of other WorkJobs, a ZOS/FUSE compatibility result or deployment approval.
"""
from __future__ import annotations

import ctypes
import os
import sys


_CAP_DAC_OVERRIDE = 1
_CAP_SETGID = 6
_CAP_SETUID = 7
_DAC_MASK = 1 << _CAP_DAC_OVERRIDE
_STARTUP_MASK = _DAC_MASK | (1 << _CAP_SETGID) | (1 << _CAP_SETUID)
_CAPABILITY_V3 = 0x20080522
_PR_SET_KEEPCAPS = 8
_PR_CAP_AMBIENT = 47
_PR_CAP_AMBIENT_RAISE = 2


class _Header(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _Data(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


def _status() -> dict[str, str]:
    with open("/proc/self/status", encoding="utf-8") as stream:
        return dict(line.strip().split(":", 1) for line in stream if ":" in line)


def _capsets() -> tuple[int, int, int, int, int]:
    status = _status()
    return tuple(int(status[name].strip(), 16) for name in (
        "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb",
    ))


def _uid(name: str) -> int:
    raw = os.environ.get(name, "")
    if not raw.isascii() or not raw.isdecimal():
        raise PermissionError(f"NAS_COMPAT: invalid {name}")
    uid = int(raw)
    if not 1 <= uid < 1 << 31:
        raise PermissionError(f"NAS_COMPAT: invalid {name}")
    return uid


def _checked(value: int, operation: str) -> None:
    if value != 0:
        code = ctypes.get_errno()
        raise OSError(code, f"NAS_COMPAT {operation}: {os.strerror(code)}")


def _libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    libc.capget.argtypes = [ctypes.POINTER(_Header), ctypes.POINTER(_Data)]
    libc.capget.restype = ctypes.c_int
    libc.capset.argtypes = [ctypes.POINTER(_Header), ctypes.POINTER(_Data)]
    libc.capset.restype = ctypes.c_int
    return libc


def _drop_to_worker(uid: int, gid: int) -> None:
    """Irreversibly drop UID 0, retaining ONLY DAC_OVERRIDE over exec.

    This handoff is not a privilege-elevating helper and must only be run
    during the container's trusted startup as UID 0. It executes no shell.
    """
    if uid <= 0 or gid <= 0 or uid == gid:
        raise PermissionError("NAS_COMPAT: invalid non-root Worker identity")
    if os.getresuid() != (0, 0, 0) or os.getresgid()[1] != gid:
        raise PermissionError("NAS_COMPAT: unexpected privileged startup identity")
    if _status().get("NoNewPrivs", "").strip() != "1":
        raise PermissionError("NAS_COMPAT: no-new-privileges is required")
    inh, prm, eff, bnd, amb = _capsets()
    if (eff != _STARTUP_MASK or prm != _STARTUP_MASK
            or bnd != _STARTUP_MASK or inh != 0 or amb != 0):
        raise PermissionError("NAS_COMPAT: unexpected privileged startup capabilities")
    libc = _libc()
    _checked(libc.prctl(_PR_SET_KEEPCAPS, 1, 0, 0, 0), "keepcaps")
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)

    header = _Header(_CAPABILITY_V3, 0)
    data = (_Data * 2)()
    _checked(libc.capget(ctypes.byref(header), data), "capget")
    if not (data[0].permitted & _DAC_MASK):
        raise PermissionError("NAS_COMPAT: permitted DAC override disappeared")
    data[0] = _Data(_DAC_MASK, _DAC_MASK, _DAC_MASK)
    data[1] = _Data()
    _checked(libc.capset(ctypes.byref(header), data), "capset")
    _checked(libc.prctl(_PR_CAP_AMBIENT, _PR_CAP_AMBIENT_RAISE,
                        _CAP_DAC_OVERRIDE, 0, 0), "ambient raise")
    assert_nas_compat_worker_identity(uid, gid)


def assert_nas_compat_worker_identity(uid: int, gid: int) -> None:
    """Fail closed when effective privileges/UID changed from approved profile."""
    if (os.getresuid() != (uid, uid, uid)
            or os.getresgid() != (gid, gid, gid)
            or os.getgroups()
            or _status().get("NoNewPrivs", "").strip() != "1"):
        raise PermissionError("NAS_COMPAT: unexpected runtime identity")
    inh, prm, eff, bnd, amb = _capsets()
    if ((inh, prm, eff, amb) != (_DAC_MASK,) * 4
            or bnd != _STARTUP_MASK):
        raise PermissionError("NAS_COMPAT: capability set does not match approved profile")


def verify_optional_worker_runtime() -> None:
    """Worker startup gate; normal mode is unchanged and capability-free by Compose."""
    enabled = os.environ.get("NFC_NAS_COMPAT_WORKER_ENABLED", "false")
    if enabled != "true":
        if enabled != "false":
            raise PermissionError("NAS_COMPAT: unsupported enable value")
        return
    assert_nas_compat_worker_identity(
        _uid("NFC_NAS_COMPAT_WORKER_UID"), _uid("NFC_NAS_COMPAT_WORKER_GID"),
    )


def main() -> None:
    if os.environ.get("NFC_NAS_COMPAT_WORKER_ENABLED") != "true":
        raise PermissionError("NAS_COMPAT: root startup requires explicit opt-in")
    if os.environ.get("MEDIA_ORGANIZER_EXECUTION_MODE") != "maintenance_window":
        raise PermissionError("NAS_COMPAT: only reviewed maintenance-window mode is eligible")
    uid = _uid("NFC_NAS_COMPAT_WORKER_UID")
    gid = _uid("NFC_NAS_COMPAT_WORKER_GID")
    api_uid = _uid("NFC_SECRET_OWNER_UID")
    if uid == api_uid or gid != _uid("NFC_SHARED_CONFIG_GID"):
        raise PermissionError("NAS_COMPAT: API/Worker shared identities are inconsistent")
    _drop_to_worker(uid, gid)
    # The only production command is fixed; no shell or arbitrary command
    # is accepted from request content, CLI args or environment.
    os.execv(sys.executable, [sys.executable, "-m", "app.worker"])


if __name__ == "__main__":
    main()
