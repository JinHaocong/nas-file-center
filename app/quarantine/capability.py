from __future__ import annotations

from enum import Enum
import os
from pathlib import Path
import stat
from typing import Sequence

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.fs_ops import _probe_rename_noreplace_supported


class MutationCapability(str, Enum):
    NATIVE_ATOMIC_NOREPLACE = "native_atomic_noreplace"
    COMPAT_TRANSACTIONAL = "compat_transactional"
    CROSS_STORAGE_TRANSACTIONAL = "cross_storage_transactional"
    UNSUPPORTED = "unsupported"


def resolve_mutation_capability(
    source_path: Path | str,
    target_dir: Path | str,
    quarantine_root: Path | str,
    allowed_roots: Sequence[Path | str],
    *,
    negative_probe_cache: set[int] | None = None,
) -> MutationCapability:
    """
    Resolves mutation capability without imposing transaction overhead on native filesystems.
    Probes target_dir directly using safe_open_parent_fd descriptor to avoid probing target's parent.

    Enforces:
    1. Direct descriptor probing via safe_open_parent_fd context manager.
    2. Regular file check for COMPAT_TRANSACTIONAL fallback (symlinks/special inodes unsupported).
    3. Strict device parity across source, target, and quarantine roots.
    """
    try:
        st_src = os.lstat(source_path)
    except OSError:
        return MutationCapability.UNSUPPORTED

    # Open target directory descriptor safely using safe_open_parent_fd context manager.
    # A task-local cache may remember only negative filesystem capability. Reusing a
    # negative result is fail-closed: it can select the stronger transactional
    # compatibility path, but it can never grant native mutation authority.
    probe_leaf = ".__probe_noreplace_anchor"
    try:
        with safe_open_parent_fd(Path(target_dir) / probe_leaf, allowed_roots) as (target_dfd, _):
            target_fd_st = os.fstat(target_dfd)
            target_device = int(target_fd_st.st_dev)
            if negative_probe_cache is not None and target_device in negative_probe_cache:
                probe_result = False
            else:
                probe_result = _probe_rename_noreplace_supported(dir_fd=target_dfd)
                if probe_result is False and negative_probe_cache is not None:
                    negative_probe_cache.add(target_device)
    except Exception:
        return MutationCapability.UNSUPPORTED

    try:
        st_target = os.stat(target_dir)
        st_quar = os.stat(quarantine_root)
    except OSError:
        return MutationCapability.UNSUPPORTED

    source_device = int(st_src.st_dev)
    target_device = int(st_target.st_dev)
    quarantine_device = int(st_quar.st_dev)

    # Gate6-C: a source/target device split is a separate transactional mode.
    # The configured quarantine storage must participate in the transfer on one
    # side (quarantine: target side, restore: source side), and the target
    # filesystem must positively prove native NOREPLACE publication.
    if source_device != target_device:
        if not stat.S_ISREG(st_src.st_mode):
            return MutationCapability.UNSUPPORTED
        if quarantine_device not in {source_device, target_device}:
            return MutationCapability.UNSUPPORTED
        if probe_result is True:
            return MutationCapability.CROSS_STORAGE_TRANSACTIONAL
        return MutationCapability.UNSUPPORTED

    if probe_result is True:
        return MutationCapability.NATIVE_ATOMIC_NOREPLACE
    elif probe_result is False:
        # Check regular file: symlinks, directories, and special files are unsupported under COMPAT
        if not stat.S_ISREG(st_src.st_mode):
            return MutationCapability.UNSUPPORTED

        # Same-storage COMPAT retains the existing strict three-way device parity.
        if source_device != quarantine_device:
            return MutationCapability.UNSUPPORTED

        return MutationCapability.COMPAT_TRANSACTIONAL

    return MutationCapability.UNSUPPORTED
