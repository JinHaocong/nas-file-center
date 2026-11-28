from __future__ import annotations

from datetime import timedelta
from typing import Literal

from app.config import Settings
from app.maintenance.database import inspect_database
from app.models import utcnow


ArchiveKind = Literal["task_events", "operation_journal"]


def preview_maintenance(settings: Settings, session_factory) -> dict:
    """Show physical database usage and the two history retention policies."""
    from app.maintenance.journal import preview_operation_journal_archive
    from app.maintenance.organizer import preview_task_event_archive

    now = utcnow()
    return {
        "database": inspect_database(settings.database_path),
        "task_events": preview_task_event_archive(
            session_factory, now - timedelta(days=settings.task_event_retention_days),
        ),
        "operation_journal": preview_operation_journal_archive(
            session_factory, now - timedelta(days=settings.operation_journal_retention_days),
        ),
        "policy": {
            "automatic": settings.history_archive_auto_enabled,
            "task_event_retention_days": settings.task_event_retention_days,
            "operation_journal_retention_days": settings.operation_journal_retention_days,
        },
    }


def archive_history_batch(settings: Settings, session_factory, kind: ArchiveKind, *, fence=None) -> dict:
    """Apply one bounded archive batch using the configured cutoff."""
    if kind == "task_events":
        from app.maintenance.organizer import archive_task_events

        return archive_task_events(
            session_factory, settings.history_archives_dir,
            utcnow() - timedelta(days=settings.task_event_retention_days), fence=fence,
        )

    from app.maintenance.journal import archive_operation_journal

    return archive_operation_journal(
        session_factory, settings.history_archives_dir,
        utcnow() - timedelta(days=settings.operation_journal_retention_days), fence=fence,
    )
