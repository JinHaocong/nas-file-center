from __future__ import annotations

import hashlib
import os
import stat


def qualify_candidate_anchor_fd(
    candidate_fd: int,
    expected_dev: int | None = None,
    expected_ino: int | None = None,
    expected_size: int = 0,
    expected_hash: str = "",
    expected_mtime_ns: int | None = None,
    *,
    expected_device: int | None = None,
    expected_inode: int | None = None,
) -> bool:
    dev = expected_dev if expected_dev is not None else expected_device
    ino = expected_ino if expected_ino is not None else expected_inode
    if dev is None or ino is None:
        raise ValueError("expected_dev (or expected_device) and expected_ino (or expected_inode) required")
    """
    Authoritative Gate3 candidate anchor qualification protocol.
    Operates strictly on an opened file descriptor without pathname reopen races.

    Validates:
    1. S_ISREG(st_before.st_mode)
    2. st_dev == expected_dev, st_ino == expected_ino, st_size == expected_size
    3. st_mtime_ns == expected_mtime_ns (if provided)
    4. Streaming SHA256 matches expected_hash
    5. Post-hash stat check (intra-qualification stability):
       st_dev, st_ino, st_size, and mtime_ns must match before-hash snapshot.

    ctime is intentionally diagnostic-only here. Real zfuse/fuseblk production
    evidence shows that a read-only descriptor hash can advance ctime while dev,
    inode, size, mtime, and content remain unchanged. Treating that read-induced
    ctime change as mutation makes qualification deterministically false-positive.
    (Pre-link ctime comparison was already excluded because os.link legitimately
    changes ctime.)
    """
    try:
        st_before = os.fstat(candidate_fd)
    except OSError:
        return False

    if not stat.S_ISREG(st_before.st_mode):
        return False

    if st_before.st_dev != dev or st_before.st_ino != ino or st_before.st_size != expected_size:
        return False

    before_mtime_ns = getattr(st_before, "st_mtime_ns", int(st_before.st_mtime * 1e9))

    if expected_mtime_ns is not None and expected_mtime_ns > 0 and before_mtime_ns != expected_mtime_ns:
        return False

    try:
        os.lseek(candidate_fd, 0, os.SEEK_SET)
        h = hashlib.sha256()
        while chunk := os.read(candidate_fd, 1024 * 1024):
            h.update(chunk)
    except OSError:
        return False

    if h.hexdigest().lower() != expected_hash.lower():
        return False

    try:
        st_after = os.fstat(candidate_fd)
    except OSError:
        return False

    after_mtime_ns = getattr(st_after, "st_mtime_ns", int(st_after.st_mtime * 1e9))

    return (
        st_after.st_dev == st_before.st_dev
        and st_after.st_ino == st_before.st_ino
        and st_after.st_size == st_before.st_size
        and after_mtime_ns == before_mtime_ns
    )
