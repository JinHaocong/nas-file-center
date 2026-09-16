from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.planning.dedupe_preview import _snapshot_real_regular_files_recursive


@dataclass(frozen=True)
class RecursiveProtectionSnapshot:
    """Public sampled snapshot contract for Recursive Last-File Protection.

    Architecture Amendment A intentionally does not treat the finite descriptor-
    bound verification passes underneath this API as an atomic snapshot against
    arbitrary external writers. They are defense in depth; callers must still
    perform the frozen Validate/Execute live protection checks.
    """

    count: int
    stable: bool
    device: int | None
    inode: int | None
    tree_identity_digest: str | None

    def digest_payload(self) -> dict[str, Any]:
        return {
            "stable": self.stable,
            "device": self.device,
            "inode": self.inode,
            "tree_identity_digest": self.tree_identity_digest,
        }


def snapshot_recursive_regular_files(
    directory: str | Path,
    *,
    quarantine_root: str | Path | None = None,
) -> RecursiveProtectionSnapshot:
    """Read one descriptor-bound, no-follow sampled recursive file snapshot."""

    snapshot = _snapshot_real_regular_files_recursive(
        directory,
        quarantine_root=quarantine_root,
    )
    return RecursiveProtectionSnapshot(
        count=snapshot.count,
        stable=snapshot.stable,
        device=snapshot.device,
        inode=snapshot.inode,
        tree_identity_digest=snapshot.tree_identity_digest,
    )