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
    UNSUPPORTED = "unsupported"


def resolve_mutation_capability(
    source_path: Path | str,
    target_dir: Path | str,
    quarantine_root: Path | str,
    allowed_roots: Sequence[Path | str],
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

    # Open target directory descriptor safely using safe_open_parent_fd context manager
    probe_leaf = ".__probe_noreplace_anchor"
    try:
        with safe_open_parent_fd(Path(target_dir) / probe_leaf, allowed_roots) as (target_dfd, _):
            probe_result = _probe_rename_noreplace_supported(dir_fd=target_dfd)
    except Exception:
        return MutationCapability.UNSUPPORTED

    if probe_result is True:
        return MutationCapability.NATIVE_ATOMIC_NOREPLACE
    elif probe_result is False:
        # Check regular file: symlinks, directories, and special files are unsupported under COMPAT
        if not stat.S_ISREG(st_src.st_mode):
            return MutationCapability.UNSUPPORTED

        # Enforce device parity across source, target dir, and quarantine root
        try:
            st_target = os.stat(target_dir)
            st_quar = os.stat(quarantine_root)
            if st_src.st_dev != st_target.st_dev or st_src.st_dev != st_quar.st_dev:
                return MutationCapability.UNSUPPORTED
        except OSError:
            return MutationCapability.UNSUPPORTED

        return MutationCapability.COMPAT_TRANSACTIONAL

    return MutationCapability.UNSUPPORTED
