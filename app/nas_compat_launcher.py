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

from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import sys
from typing import Iterator


_CAP_DAC_OVERRIDE = 1
_CAP_SETGID = 6
_CAP_SETUID = 7
_DAC_MASK = 1 << _CAP_DAC_OVERRIDE
_STARTUP_MASK = _DAC_MASK | (1 << _CAP_SETGID) | (1 << _CAP_SETUID)
_CAPABILITY_V3 = 0x20080522
_PR_SET_KEEPCAPS = 8
_PR_CAP_AMBIENT = 47
_PR_CAP_AMBIENT_RAISE = 2
_PR_CAP_AMBIENT_CLEAR_ALL = 4
_APPROVED_KINDS = frozenset(('media-organizer-preview', 'media-organizer-execute', 'media-organizer-cleanup'))
_MUTATION_KINDS = frozenset(('media-organizer-execute', 'media-organizer-cleanup'))


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


def assert_nas_compat_worker_identity(uid: int, gid: int, *, phase: str = "handoff") -> None:
    """Validate the exact non-root identity and capability state.

    handoff: transient elevated state immediately after the root->UID drop;
    parked: normal Worker with DAC permitted but NOT effective or ambient;
    scoped: one explicitly approved foreground media-handler call only.
    """
    if (os.getresuid() != (uid, uid, uid)
            or os.getresgid() != (gid, gid, gid)
            or os.getgroups()
            or _status().get("NoNewPrivs", "").strip() != "1"):
        raise PermissionError("NAS_COMPAT: unexpected runtime identity")
    expected = {
        "handoff": (_DAC_MASK, _DAC_MASK, _DAC_MASK, _STARTUP_MASK, _DAC_MASK),
        "parked": (0, _DAC_MASK, 0, _STARTUP_MASK, 0),
        "scoped": (0, _DAC_MASK, _DAC_MASK, _STARTUP_MASK, 0),
    }.get(phase)
    if expected is None or _capsets() != expected:
        raise PermissionError("NAS_COMPAT: capability set does not match approved profile")


def park_nas_compat_runtime() -> None:
    """First action after exec: clear ambient/effective before app.worker imports."""
    if (os.environ.get("NFC_NAS_COMPAT_WORKER_ENABLED") != "true"
            or os.environ.get("MEDIA_ORGANIZER_EXECUTION_MODE") != "maintenance_window"):
        raise PermissionError("NAS_COMPAT: unapproved startup mode")
    uid, gid = _uid("NFC_NAS_COMPAT_WORKER_UID"), _uid("NFC_NAS_COMPAT_WORKER_GID")
    assert_nas_compat_worker_identity(uid, gid, phase="handoff")
    libc = _libc()
    _checked(libc.prctl(_PR_CAP_AMBIENT, _PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0),
             "clear ambient")
    header = _Header(_CAPABILITY_V3, 0)
    data = (_Data * 2)()
    _checked(libc.capget(ctypes.byref(header), data), "capget")
    if data[0].permitted != _DAC_MASK or data[1].permitted != 0:
        raise PermissionError("NAS_COMPAT: inherited unexpected permissions")
    data[0] = _Data(0, _DAC_MASK, 0)
    data[1] = _Data()
    _checked(libc.capset(ctypes.byref(header), data), "capset park")
    assert_nas_compat_worker_identity(uid, gid, phase="parked")


def _set_job_dac_effective(enable: bool) -> None:
    """Change only this handler thread's effective DAC bit."""
    uid, gid = _uid("NFC_NAS_COMPAT_WORKER_UID"), _uid("NFC_NAS_COMPAT_WORKER_GID")
    assert_nas_compat_worker_identity(uid, gid, phase="parked" if enable else "scoped")
    libc = _libc()
    header = _Header(_CAPABILITY_V3, 0)
    data = (_Data * 2)()
    _checked(libc.capget(ctypes.byref(header), data), "capget")
    if (data[0].permitted != _DAC_MASK or data[0].inheritable != 0
            or data[1].permitted != 0 or data[1].effective != 0
            or data[1].inheritable != 0):
        raise PermissionError("NAS_COMPAT: unexpected thread capabilities")
    data[0] = _Data(_DAC_MASK if enable else 0, _DAC_MASK, 0)
    data[1] = _Data()
    _checked(libc.capset(ctypes.byref(header), data), "capset scoped DAC")
    assert_nas_compat_worker_identity(uid, gid, phase="scoped" if enable else "parked")


def _approved_media_job(job, settings) -> bool:
    """Never elevate arbitrary jobs, failed tasks, or unapproved media writes."""
    if job.kind not in _APPROVED_KINDS:
        return False
    if job.status != "running" or type(job.id) is not int or job.id <= 0:
        raise PermissionError("NAS_COMPAT: approved job must be running")
    try:
        state = json.loads(job.state_json or "{}")
    except (TypeError, ValueError) as exc:
        raise PermissionError("NAS_COMPAT: invalid frozen job evidence") from exc
    if not isinstance(state, dict) or state.get("execution_mode") != "maintenance_window":
        raise PermissionError("NAS_COMPAT: incorrect frozen job mode")
    unit = state.get("unit" if job.kind in _MUTATION_KINDS else "selection")
    if (not isinstance(unit, str) or not unit.startswith("/")
            or ".." in Path(unit).parts or os.path.normpath(unit) != unit
            or "\x00" in unit
            or not any(Path(unit).is_relative_to(root) for root in settings.allowed_roots)):
        raise PermissionError("NAS_COMPAT: invalid job scope")
    if job.kind in _MUTATION_KINDS:
        if (state.get("maintenance_window_confirmed") is not True
                or type(state.get("approved_job_id")) is not int
                or state["approved_job_id"] != job.id
                or not isinstance(state.get("confirmation"), str)
                or not state["confirmation"]
                or not all(getattr(settings, key, False) is True for key in (
                    "media_organizer_execution_enabled", "allow_mutation", "allow_delete",
                ))):
            raise PermissionError("NAS_COMPAT: missing job-bound mutation approval")
    return True


@contextmanager
def scoped_nas_compat_job(job, settings) -> Iterator[None]:
    """Raise effective DAC only for an approved semantic-media WorkJob.

    If revocation fails, terminate immediately. A conventional exception
    handler must never continue with a potentially elevated capability.
    """
    verify_optional_worker_runtime()
    if os.environ.get("NFC_NAS_COMPAT_WORKER_ENABLED", "false") != "true":
        yield
        return
    if not _approved_media_job(job, settings):
        yield
        verify_optional_worker_runtime()
        return
    _set_job_dac_effective(True)
    try:
        yield
    finally:
        try:
            _set_job_dac_effective(False)
            verify_optional_worker_runtime()
        except BaseException:
            os._exit(70)


def verify_optional_worker_runtime() -> None:
    """Worker startup gate; normal mode is unchanged and capability-free by Compose."""
    enabled = os.environ.get("NFC_NAS_COMPAT_WORKER_ENABLED", "false")
    if enabled != "true":
        if enabled != "false":
            raise PermissionError("NAS_COMPAT: unsupported enable value")
        return
    if os.environ.get("MEDIA_ORGANIZER_EXECUTION_MODE") != "maintenance_window":
        raise PermissionError("NAS_COMPAT: runtime is not maintenance-window mode")
    assert_nas_compat_worker_identity(
        _uid("NFC_NAS_COMPAT_WORKER_UID"), _uid("NFC_NAS_COMPAT_WORKER_GID"),
        phase="parked",
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
    os.execv(sys.executable, [sys.executable, "-m", "app.nas_compat_runtime_entry"])


if __name__ == "__main__":
    main()
