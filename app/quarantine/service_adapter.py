from __future__ import annotations

from app.models import QuarantineEntry
from app.quarantine.single_unlink_purge import purge_single_transactional_entry
from app.service import FileCenterService


class Gate6A2FileCenterService(FileCenterService):
    """Incremental Gate6-A2 adapter for the public single Clear action.

    Transactional quarantine entries use the new pathname-scoped unlink engine.
    Truly legacy, non-transactional entries remain on the existing compatibility
    path until their migration/closure semantics are handled explicitly.
    """

    def purge_quarantine_entry(
        self,
        entry_id: int,
        *,
        confirmation: str,
        is_admin: bool = False,
    ) -> dict:
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

        return super().purge_quarantine_entry(
            entry_id,
            confirmation=confirmation,
            is_admin=is_admin,
        )
