from __future__ import annotations

import errno
from pathlib import Path
from app.models import QuarantineEntry


def safe_quarantine_purge_guard(entry: QuarantineEntry) -> None:
    """
    Zero Payload-Bearing Unlink Guard for COMPAT mode.
    If entry has an authoritative anchor or is transactional, purging payload
    is strictly forbidden under COMPAT mode with EOPNOTSUPP.
    """
    if entry.authoritative_anchor_path is not None or entry.tx_phase is not None:
        raise OSError(
            errno.EOPNOTSUPP,
            f"Zero Payload-Bearing Unlink Guard: Purge is disabled in COMPAT mode for transactional entry #{entry.id} with authoritative anchor",
        )
