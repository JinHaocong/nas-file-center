from __future__ import annotations

from app.exceptions import StateConflictError
from app.models import QuarantineEntry
from app.quarantine.single_unlink_purge import purge_single_transactional_entry
from app.service import FileCenterService


class Gate6A2FileCenterService(FileCenterService):
    """Gate6-A2 adapter for the public single Clear action.

    Transactional quarantine entries use the pathname-scoped unlink_v1 engine.
    Legacy/non-transactional entries have no frozen Gate6-A2 authority and must
    fail closed rather than falling back to the historical purge implementation.
    """

    def purge_quarantine_entry(
        self,
        entry_id: int,
        *,
        confirmation: str,
        is_admin: bool = False,
    ) -> dict:
        # Preserve the established public validation order before deciding
        # whether the entry has Gate6-A2 destructive authority. A legacy entry
        # with an invalid request still reports the request error, while a valid
        # permanent-clear request fails closed before any historical purge core.
        if not is_admin:
            raise PermissionError("Only administrator can purge quarantine entries")
        if not self.settings.allow_mutation:
            raise ValueError("Filesystem mutation is disabled")
        if not self.settings.allow_delete:
            raise ValueError("Permanent deletion is disabled")
        if confirmation != "DELETE":
            raise ValueError("Confirmation token must be 'DELETE'")

        with self.SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                raise KeyError(f"Quarantine entry #{entry_id} not found")
            is_transactional = (
                entry.authoritative_anchor_path is not None
                or entry.tx_phase is not None
                or int(entry.active_attempt_generation or 0) > 0
            )

        if is_transactional:
            return purge_single_transactional_entry(
                self,
                entry_id,
                confirmation=confirmation,
                is_admin=is_admin,
            )

        raise StateConflictError(
            "LEGACY_QUARANTINE_PURGE_UNSUPPORTED: "
            "Gate6-A2 permanent Clear requires transactional unlink_v1 authority"
        )
