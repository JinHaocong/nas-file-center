from __future__ import annotations

import json
from typing import Any

from app.exceptions import StateConflictError
from app.models import QuarantineEntry


def freeze_bulk_plan_item(
    service,
    *,
    plan_kind: str,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """Return plan-item Freeze updates for Gate6-A kinds, or None when not owned here."""
    if plan_kind != "quarantine-bulk-restore" or item.get("operation") != "restore":
        return None

    metadata = json.loads(item.get("metadata_json") or "{}")
    entry_id = metadata.get("quarantine_entry_id")
    if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0:
        raise StateConflictError("Bulk restore plan item is missing a valid quarantine_entry_id")

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} no longer exists at Freeze")
        if entry.state != "active":
            raise StateConflictError(
                f"Quarantine entry #{entry_id} is no longer active at Freeze (state={entry.state})"
            )

    return {}
