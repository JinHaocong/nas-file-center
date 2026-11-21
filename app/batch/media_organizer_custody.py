"""Strict-mode production namespace custody provider (#402).

This provider intentionally has no live issuer until host/NAS ACL and mount
semantics prove external writer exclusion. Strict mode remains fail-closed.

The separate operator-confirmed maintenance-window contract is implemented
in media_organizer_authority.py. It does NOT call this provider and is never
reported as strict namespace custody. Its documented assumption is that the
operator pauses all other writers for the full execute/cleanup/recovery window.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Iterable


class NamespaceCustodyUnavailable(ValueError):
    """No OS-enforced external namespace custody is proven for this unit."""


class ScopedNamespaceCustody(Protocol):
    def assert_exclusive(self, parent: Path) -> None:
        """Refresh the external exclusive namespace boundary for this directory."""


def verified_namespace_custody(settings, unit: Path) -> ScopedNamespaceCustody:
    """Fail closed in production until a supported and reviewed issuer exists.

    A future implementation must bind a specific mount, canonical unit inode,
    non-root Worker principal, all old classification parent namespaces,
    SMB/NAS ACL policy, and a revocable exclusive operational lease.
    """
    raise NamespaceCustodyUnavailable(
        "SEC-12: externally enforced exclusive NAS namespace custody is not proven"
    )


def assert_exclusive_custody(
    proof: ScopedNamespaceCustody | None,
    parents: Iterable[Path],
) -> None:
    if proof is None or not callable(getattr(proof, "assert_exclusive", None)):
        raise NamespaceCustodyUnavailable(
            "SEC-12: an affirmative flag is not an exclusive custody proof"
        )
    try:
        for folder in parents:
            if not isinstance(folder, Path) or not folder.is_absolute():
                raise NamespaceCustodyUnavailable("SEC-12: noncanonical custody scope")
            result = proof.assert_exclusive(folder)
            # Successful assertions return only None. Booleans, status values
            # and evidence records are not a verified assertion of custody.
            if result is not None:
                raise NamespaceCustodyUnavailable(
                    "SEC-12: invalid namespace custody assertion result"
                )
    except (OSError, PermissionError) as exc:
        raise NamespaceCustodyUnavailable(
            "SEC-12: namespace custody unavailable at mutation boundary"
        ) from exc
