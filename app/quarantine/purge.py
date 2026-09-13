from __future__ import annotations

from typing import Any, Callable
from pathlib import Path

from app.quarantine.bulk import build_purge_topology_manifest as _build_preview_purge_topology_manifest


def build_purge_topology_manifest(
    entry: Any,
    quarantine_root: Path | str,
    *,
    owner_lookup: Callable[[int], Any | None] | None = None,
) -> dict[str, Any]:
    """Build the read-only Gate6-A transactional purge topology manifest."""
    return _build_preview_purge_topology_manifest(
        entry,
        quarantine_root,
        owner_lookup=owner_lookup,
    )
