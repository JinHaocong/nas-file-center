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
    quarantine_root: Path | str | None = None,
) -> tuple[int, Path]:
    """
    Pattern B generation allocator:
    Allocates a strictly monotonic attempt generation under an in-transaction worker lease fence.
    The next generation is committed to SQLite before any filesystem attempt-directory is created.
    """
    q_root: Path | None = Path(quarantine_root) if quarantine_root is not None else None
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if not entry:
            raise ValueError(f"QuarantineEntry {entry_id} not found")
        next_gen = (entry.active_attempt_generation or 0) + 1
        entry.active_attempt_generation = next_gen
        session.commit()

    if q_root is None:
        if entry.quarantine_path:
            qp = Path(entry.quarantine_path)
            try:
                from app.config import get_settings
                settings_root = Path(get_settings().quarantine_root)
                try:
                    qp.relative_to(settings_root)
                    q_root = settings_root
                except ValueError:
                    q_root = qp.parent
            except Exception:
                q_root = qp.parent
        if q_root is None:
            try:
                from app.config import get_settings
                q_root = Path(get_settings().quarantine_root)
            except Exception:
                q_root = None

    if q_root is None:
        raise ValueError(f"quarantine_root could not be determined for entry {entry_id}")

    attempt_dir = q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{next_gen}"
    return next_gen, attempt_dir

