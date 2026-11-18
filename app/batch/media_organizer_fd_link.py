"""Linux inode-bound, exclusive hardlink primitive for V1.6 retained originals.

Source basename validation followed by os.link is racy against uncooperative
writers. linkat(AT_EMPTY_PATH) links the already-open *verified* regular file
descriptor instead, regardless of a concurrent source-basename replacement.

There is deliberately NO name-based fallback. A filesystem or OS without this
primitive must fail closed. Actual NAS-mount support needs an approved probe.
"""
from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys


_AT_EMPTY_PATH = 0x1000


def link_pinned_inode_noreplace(source_fd: int, destination_dir_fd: int,
                               destination_basename: str) -> None:
    """Create one exclusive hardlink from a pinned regular inode, never by source name.

    The caller must open the source using O_NOFOLLOW, verify the frozen inode,
    and hold the directory/Worker authority. If the destination exists, the
    kernel refuses it; neither destination nor source are removed or replaced.
    """
    if not isinstance(destination_basename, str) or (
        destination_basename in ("", ".", "..")
        or "/" in destination_basename or "\x00" in destination_basename
    ):
        raise ValueError("unsafe destination basename for pinned hardlink")
    if not sys.platform.startswith("linux"):
        raise OSError(errno.EOPNOTSUPP, "pinned fd hardlinks require Linux")
    observed = os.fstat(source_fd)
    if not stat.S_ISREG(observed.st_mode):
        raise ValueError("pinned hardlink source is not a regular file")
    libc = ctypes.CDLL(None, use_errno=True)
    linkat = getattr(libc, "linkat", None)
    if linkat is None:
        raise OSError(errno.ENOSYS, "linkat unavailable; name fallback forbidden")
    linkat.argtypes = [ctypes.c_int, ctypes.c_char_p,
                       ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    linkat.restype = ctypes.c_int
    outcome = linkat(
        source_fd, b"", destination_dir_fd,
        os.fsencode(destination_basename), _AT_EMPTY_PATH,
    )
    if outcome != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), destination_basename)
