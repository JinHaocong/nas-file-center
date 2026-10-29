"""Fail-closed proof for retiring an externally missing quarantine payload's DB row.

Only observations are made here. No unlink, rmdir, rename, directory cleanup,
or transaction replay is permitted on this metadata-only path.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import stat

from sqlalchemy import or_, select

from app.exceptions import StateConflictError
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, WorkJob, utcnow


_ACTIVE_JOB_STATES = ("queued", "running", "paused", "cancel_requested")
_ACTIVE_ITEM_STATES = ("planned", "executing", "paused", "queued", "pending")
_RELEVANT_JOB_KINDS = ("batch-plan-execute", "quarantine-record-cleanup")


def _as_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def require_absent_beneath_quarantine_root(
    root: Path, candidate: Path, *, label: str, require_intact_parent: bool = False,
    expected_root_device: int | None = None,
) -> None:
    """Walk from / through nofollow directory FDs; only ENOENT proves absence.

    Payload cleanup requires an intact, accessible parent chain: an absent
    intermediate directory could be a temporarily unmounted subtree, not an
    externally deleted file. Only the final missing leaf proves payload
    absence. For the optional private .tx namespace, absent .tx itself can
    demonstrate no visible residue. Never follow a swapped pathname.
    """
    root = Path(root)
    candidate = Path(candidate)
    if (
        not root.is_absolute() or not candidate.is_absolute()
        or ".." in root.parts or ".." in candidate.parts
        or root == Path("/") or candidate == root
        or not candidate.is_relative_to(root)
    ):
        raise StateConflictError(f"Unsafe {label} path; quarantine root containment is unproven")

    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise StateConflictError("Nofollow directory traversal is unavailable")
    with ExitStack() as stack:
        try:
            fd = os.open("/", flags)
            stack.callback(os.close, fd)
            for component in root.parts[1:]:
                next_fd = os.open(component, flags, dir_fd=fd)
                stack.callback(os.close, next_fd)
                fd = next_fd
            root_identity = os.fstat(fd)
            if not stat.S_ISDIR(root_identity.st_mode):
                raise StateConflictError("Quarantine root is not a plain directory")
            if expected_root_device is not None and (
                expected_root_device <= 0 or root_identity.st_dev != expected_root_device
            ):
                raise StateConflictError(
                    "Recorded quarantine payload device differs from current root; "
                    "mount may be detached or replaced"
                )

            relative_parts = candidate.relative_to(root).parts
            for component in relative_parts[:-1]:
                try:
                    next_fd = os.open(component, flags, dir_fd=fd)
                except FileNotFoundError as exc:
                    if require_intact_parent:
                        raise StateConflictError(
                            f"Cannot prove {label} absence: an ancestor directory is missing"
                        ) from exc
                    return
                stack.callback(os.close, next_fd)
                fd = next_fd
            try:
                os.stat(relative_parts[-1], dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise StateConflictError(f"{label} still exists (including symlinks); cannot delete record")
        except StateConflictError:
            raise
        except OSError as exc:
            raise StateConflictError(f"Cannot prove {label} absence: {exc}") from exc


def assert_missing_quarantine_entry_safe(
    session,
    entry: QuarantineEntry,
    *,
    quarantine_root: Path,
    service_started_at: datetime,
) -> None:
    """Require ordinary, quiescent state and provable absence; do not mutate."""
    if entry.state not in {"active", "purging"}:
        raise StateConflictError(
            f"Quarantine entry #{entry.id} is in state {entry.state}; only active/purging missing-record cleanup is supported"
        )
    if (
        entry.tx_token is not None or entry.tx_phase is not None
        or entry.transaction_mode is not None
        or entry.authoritative_anchor_path is not None
        or int(entry.active_attempt_generation or 0) != 0
        or entry.quarantine_device is not None
        or entry.quarantine_inode is not None
        or entry.restore_target_path is not None
    ):
        raise StateConflictError(
            f"Quarantine entry #{entry.id} has transactional/frozen evidence; use Worker recovery, never metadata cleanup"
        )

    # A legacy direct API purge has no WorkJob lease. Only accept a purging
    # row known to predate this API service process, and long enough stale to
    # rule out an ordinary short in-flight request in this process.
    if entry.state == "purging":
        last_change = _as_aware(entry.updated_at) if entry.updated_at else None
        if (
            last_change is None
            or last_change >= _as_aware(service_started_at)
            or utcnow() - last_change < timedelta(minutes=10)
        ):
            raise StateConflictError(
                "Purging state might still be in flight; require an old, pre-restart transition and read-only diagnosis"
            )

    if entry.task_id is not None:
        source_job = session.get(WorkJob, entry.task_id)
        if source_job is not None and (
            source_job.status in _ACTIVE_JOB_STATES
            or (entry.state == "purging" and source_job.error_code == "WORKER_INTERRUPTED")
        ):
            raise StateConflictError("Associated job may be running or require evidence-based recovery")
    if entry.plan_item_id is not None:
        source_item = session.get(BatchPlanItem, entry.plan_item_id)
        if source_item is not None:
            plan = session.get(BatchPlan, source_item.plan_id)
            if source_item.state in _ACTIVE_ITEM_STATES or (
                plan is not None and plan.status in {"executing", "queued", "validating", "paused"}
            ):
                raise StateConflictError("Associated batch item/plan may still execute")

    # Task/plan provenance may NOT identify the later purge attempt. Block
    # outstanding destructive runners globally and any pending item referencing
    # this exact path, even when entry.task_id points to a completed old job.
    active_destructive = session.scalars(
        select(WorkJob.id).where(
            WorkJob.status.in_(_ACTIVE_JOB_STATES),
            WorkJob.kind.in_(_RELEVANT_JOB_KINDS),
        ).limit(1)
    ).first()
    if active_destructive is not None:
        raise StateConflictError("A batch/quarantine Worker job is still active; retry only when quiescent")

    pending_item = session.scalars(
        select(BatchPlanItem.id).where(
            BatchPlanItem.operation.in_(("quarantine_purge", "quarantine_restore")),
            BatchPlanItem.state.in_(_ACTIVE_ITEM_STATES),
            or_(
                BatchPlanItem.source_path == entry.quarantine_path,
                BatchPlanItem.target_path == entry.quarantine_path,
            ),
        ).limit(1)
    ).first()
    if pending_item is not None:
        raise StateConflictError("An unresolved plan item references this quarantine path")

    root = Path(quarantine_root).absolute()
    require_absent_beneath_quarantine_root(
        root, Path(entry.quarantine_path), label="quarantine payload",
        require_intact_parent=True,
    )
    # Even an empty private tx namespace is evidence until a lease-fenced
    # Worker has retired it. Metadata cleanup never removes that namespace.
    require_absent_beneath_quarantine_root(
        root, root / ".tx" / f"entry-{entry.id}", label="transaction evidence"
    )


def observe_quarantine_candidate(
    root: Path, candidate: Path, *, label: str, require_intact_parent: bool = False
) -> str:
    """Admin diagnostic only: observe absent/present/indeterminate without mutating.

    Reuse the exact nofollow proof used by metadata cleanup, but do NOT grant
    cleanup permission based on this point-in-time observation. In particular,
    a vanished outer mount or a symlink ancestor is indeterminate; a present
    leaf (including a symlink) is present. Read-only calls never change DB or FS.
    """
    try:
        require_absent_beneath_quarantine_root(
            root, candidate, label=label,
            require_intact_parent=require_intact_parent,
        )
    except StateConflictError as exc:
        if str(exc) == f"{label} still exists (including symlinks); cannot delete record":
            return "present"
        return "indeterminate"
    return "absent"


def assert_orphaned_transaction_record_safe(
    session,
    entry: QuarantineEntry,
    *,
    quarantine_root: Path,
    service_started_at: datetime,
) -> None:
    """Human-attested DB-only retirement of a stale, evidence-free purge.

    This is deliberately NOT normal missing-record cleanup. An absent parent
    can mean an offline nested mount: allow it only on the *same device* as
    the frozen public payload and only with explicit admin confirmation.
    Never touch filesystem bytes or pretend a frozen purge succeeded.
    """
    if not (
        entry.state == "purging"
        and entry.tx_phase == "purging"
        and entry.transaction_mode == "cross_storage_transactional"
        and int(entry.active_attempt_generation or 0) > 0
    ):
        raise StateConflictError("Only interrupted cross-storage purging records may use orphan retirement")
    if (
        entry.task_id is not None or entry.plan_item_id is not None
        or entry.restore_target_path is not None
        or entry.restore_device is not None or entry.restore_inode is not None
    ):
        raise StateConflictError("Record has task/plan/restore authority; manual retirement is blocked")
    changed = _as_aware(entry.updated_at) if entry.updated_at else None
    if (
        changed is None or changed >= _as_aware(service_started_at)
        or utcnow() - changed < timedelta(minutes=10)
    ):
        raise StateConflictError("Purging transition may still be in flight; require an old pre-restart state")

    # Existence of *any* destructive executor can make a later frozen retry
    # possible. Fail closed, even if provenance IDs are absent on this row.
    active_job = session.scalars(
        select(WorkJob.id).where(
            WorkJob.status.in_(_ACTIVE_JOB_STATES),
            WorkJob.kind.in_(
                ("batch-plan-execute", "quarantine-record-cleanup",
                 "quarantine-purge", "quarantine-restore")
            ),
        ).limit(1)
    ).first()
    if active_job is not None:
        raise StateConflictError("Destructive Worker job is active; orphan retirement blocked")

    plan_ref = session.scalars(
        select(BatchPlanItem.id).where(
            BatchPlanItem.operation.in_(("quarantine_purge", "quarantine_restore")),
            BatchPlanItem.state.in_(_ACTIVE_ITEM_STATES),
            or_(
                BatchPlanItem.source_path.in_((entry.original_path, entry.quarantine_path)),
                BatchPlanItem.target_path.in_((entry.original_path, entry.quarantine_path)),
            ),
        ).limit(1)
    ).first()
    if plan_ref is not None:
        raise StateConflictError("Unfinished frozen plan item references the orphan record")

    root = Path(quarantine_root).absolute()
    private_root = root / ".tx" / f"entry-{entry.id}"
    if entry.authoritative_anchor_path:
        anchor = Path(entry.authoritative_anchor_path)
        if (
            not anchor.is_absolute() or ".." in anchor.parts
            or not anchor.is_relative_to(private_root)
        ):
            raise StateConflictError("Authoritative anchor is outside the expected .tx entry namespace")

    frozen_device = int(entry.quarantine_device or 0)
    if frozen_device <= 0:
        raise StateConflictError(
            "Cannot prove quarantine mount identity without frozen payload device"
        )

    # Same securely opened nofollow root FD for device and absence proofs.
    # For manually removed directories, only this narrowly scoped path may
    # accept missing intermediate directories. Inaccessible/symlinked roots
    # and mount/device changes still fail closed.
    require_absent_beneath_quarantine_root(
        root, Path(entry.quarantine_path),
        label="orphan quarantine payload", expected_root_device=frozen_device,
    )
    require_absent_beneath_quarantine_root(
        root, private_root, label="orphan private transaction evidence",
        expected_root_device=frozen_device,
    )
