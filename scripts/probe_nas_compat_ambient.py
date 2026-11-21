"""CI-only proof: retain DAC_OVERRIDE across a root -> non-root exec.

This file is NOT a production entrypoint. It has no network interface, accepts
the one-use synthetic probe Python string, and is only mounted in CI disposable
Docker test containers. Its purpose is to decide whether a two-container NAS
compatibility implementation deserves further design/security review.
"""
from __future__ import annotations

import ctypes
import os
import sys


CAP_DAC_OVERRIDE = 1
CAP_MASK = 1 << CAP_DAC_OVERRIDE
CAPABILITY_VERSION_3 = 0x20080522
PR_SET_KEEPCAPS = 8
PR_CAP_AMBIENT = 47
PR_CAP_AMBIENT_RAISE = 2


class CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class CapData(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


def _checked(result: int, operation: str) -> None:
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, f"{operation}: {os.strerror(code)}")


def main() -> None:
    if len(sys.argv) != 2 or os.geteuid() != 0:
        raise SystemExit("CI-only launcher needs root startup and exact test payload")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    libc.capget.argtypes = [ctypes.POINTER(CapHeader), ctypes.POINTER(CapData)]
    libc.capget.restype = ctypes.c_int
    libc.capset.argtypes = [ctypes.POINTER(CapHeader), ctypes.POINTER(CapData)]
    libc.capset.restype = ctypes.c_int

    _checked(libc.prctl(PR_SET_KEEPCAPS, 1, 0, 0, 0), "PR_SET_KEEPCAPS")
    os.setgroups([])
    os.setgid(10000)
    os.setuid(10002)

    header = CapHeader(CAPABILITY_VERSION_3, 0)
    data = (CapData * 2)()
    _checked(libc.capget(ctypes.byref(header), data), "capget")
    if not (data[0].permitted & CAP_MASK):
        raise PermissionError("DAC_OVERRIDE was not retained in the permitted set")

    # Drop SETUID/SETGID and every other permitted/effective/inheritable bit.
    # Do not permit a return to UID 0 after the switch.
    data[0] = CapData(effective=CAP_MASK, permitted=CAP_MASK, inheritable=CAP_MASK)
    data[1] = CapData()
    _checked(libc.capset(ctypes.byref(header), data), "capset DAC_OVERRIDE only")
    _checked(libc.prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_RAISE,
                        CAP_DAC_OVERRIDE, 0, 0), "PR_CAP_AMBIENT_RAISE")
    os.execv(sys.executable, [sys.executable, "-c", sys.argv[1]])


if __name__ == "__main__":
    main()
