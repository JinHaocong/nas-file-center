from __future__ import annotations

from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models import QuarantineEntry
from app.tasks.recovery import assert_active_worker_lease


def allocate_next_generation(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str,
) -> tuple[int, Path]:
    """
    Pattern B generation allocator:
    Allocates a strictly monotonic attempt generation under an in-transaction worker lease fence.
    The next generation is committed to SQLite before any filesystem attempt-directory is created.
    """
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if not entry:
            raise ValueError(f"QuarantineEntry {entry_id} not found")
        next_gen = (entry.active_attempt_generation or 0) + 1
        entry.active_attempt_generation = next_gen
        quarantine_parent = Path(entry.quarantine_path).parent
        session.commit()

    attempt_dir = quarantine_parent / ".tx" / f"entry-{entry_id}" / f"attempt-{next_gen}"
    return next_gen, attempt_dir
