from __future__ import annotations

import json

from sqlalchemy import text

from app.exceptions import StateConflictError
from app.models import AuditEvent, QuarantineEntry, WorkJob, utcnow
from app.quarantine.single_unlink_purge import _durable_terminal_recovery_evidence
from app.quarantine.restore import validate_restore_destination_intent
from app.quarantine.unlink_purge import (
    SEMANTICS_VERSION,
    _durable_authority_manifest,
    build_unlink_manifest,
)
from app.service import FileCenterService


class Gate6A2FileCenterService(FileCenterService):
    """Gate6-A2 adapter: API validates and queues; Worker owns every unlink."""

    def enqueue_quarantine_restore(
        self,
        entry_id: int,
        *,
        conflict_policy: str | None = None,
        conflict_strategy: str | None = None,
        custom_target: str | None = None,
        user_id: int | None = None,
    ) -> dict:
        """Validate and queue a restore; the Worker is the only media mutator."""
        policy = conflict_policy or conflict_strategy or "skip"
        if policy not in {"skip", "rename", "manual"}:
            raise ValueError(
                f"Invalid conflict_policy: {policy}. Must be 'skip', 'rename', or 'manual'."
            )
        if not self.settings.allow_mutation:
            raise ValueError("Filesystem mutation is disabled")

        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            entry = session.get(QuarantineEntry, int(entry_id))
            if entry is None:
                session.rollback()
                raise KeyError(f"Quarantine entry #{entry_id} not found")

            validate_restore_destination_intent(
                entry,
                allowed_roots=self.settings.allowed_roots,
                quarantine_root=self.settings.quarantine_root,
                custom_target=custom_target,
                conflict_policy=policy,
            )

            expected_identity = {
                "original_path": str(entry.original_path),
                "quarantine_path": str(entry.quarantine_path),
                "state": str(entry.state),
                "tx_phase": entry.tx_phase,
                "transaction_mode": entry.transaction_mode,
                "authoritative_anchor_path": entry.authoritative_anchor_path,
                "active_attempt_generation": int(entry.active_attempt_generation or 0),
                "size": int(entry.size or 0),
                "content_hash": entry.content_hash,
                "mtime_ns": int(entry.mtime_ns or 0),
                "device": int(entry.device or 0),
                "inode": int(entry.inode or 0),
                "quarantine_device": (
                    int(entry.quarantine_device)
                    if entry.quarantine_device is not None else None
                ),
                "quarantine_inode": (
                    int(entry.quarantine_inode)
                    if entry.quarantine_inode is not None else None
                ),
                "quarantine_mtime_ns": (
                    int(entry.quarantine_mtime_ns)
                    if entry.quarantine_mtime_ns is not None else None
                ),
            }
            job = WorkJob(
                kind="quarantine-restore",
                status="queued",
                state_json=json.dumps(
                    {
                        "entry_id": int(entry.id),
                        "conflict_policy": policy,
                        "custom_target": custom_target,
                        "requested_by_user_id": user_id,
                        "expected_identity": expected_identity,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                progress_current=0,
                progress_total=1,
                progress_message=f"Queued restore for quarantine entry #{entry.id}",
                created_at=utcnow(),
            )
            session.add(job)
            session.flush()
            session.add(AuditEvent(
                operation="quarantine.restore_enqueue",
                path=str(entry.quarantine_path),
                result="queued",
                details_json=json.dumps(
                    {
                        "quarantine_entry_id": int(entry.id),
                        "work_job_id": int(job.id),
                        "requested_by_user_id": user_id,
                        "conflict_policy": policy,
                        "custom_target": custom_target,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ))
            session.commit()
            return {
                "id": int(entry.id),
                "entry_id": int(entry.id),
                "status": "queued",
                "state": "queued",
                "work_job_id": int(job.id),
                "conflict_policy": policy,
            }

    def purge_quarantine_entry(
        self,
        entry_id: int,
        *,
        confirmation: str,
        is_admin: bool = False,
        user_id: int | None = None,
    ) -> dict:
        if not is_admin:
            raise PermissionError("Only administrator can purge quarantine entries")
        if not self.settings.allow_mutation:
            raise ValueError("Filesystem mutation is disabled")
        if not self.settings.allow_delete:
            raise ValueError("Permanent deletion is disabled")
        if confirmation != "DELETE":
            raise ValueError("Confirmation token must be 'DELETE'")

        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                session.rollback()
                raise KeyError(f"Quarantine entry #{entry_id} not found")

            is_transactional = (
                entry.authoritative_anchor_path is not None
                or entry.tx_phase is not None
                or int(entry.active_attempt_generation or 0) > 0
            )
            if not is_transactional:
                session.rollback()
                raise StateConflictError(
                    "LEGACY_QUARANTINE_PURGE_UNSUPPORTED: "
                    "Gate6-A2 permanent Clear requires transactional unlink_v1 authority"
                )

            if entry.state == "active" and entry.tx_phase == "active":
                manifest = build_unlink_manifest(
                    entry, self.settings.quarantine_root,
                )
            elif entry.state == "purging" and entry.tx_phase == "purging":
                manifest = _durable_authority_manifest(
                    session,
                    int(entry.id),
                    attempt_generation=int(entry.active_attempt_generation or 0),
                )
            elif entry.state == "purged" and entry.tx_phase == "purged":
                manifest, _recovery = _durable_terminal_recovery_evidence(
                    session,
                    entry=entry,
                    quarantine_root=self.settings.quarantine_root,
                )
            else:
                session.rollback()
                raise StateConflictError(
                    f"Cannot queue Gate6-A2 purge in state '{entry.state}' phase '{entry.tx_phase}'"
                )

            blockers = list(manifest.get("blockers") or [])
            if blockers:
                session.rollback()
                raise StateConflictError("UNLINK_MANIFEST_INVALID:" + ",".join(blockers))

            frozen = json.loads(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            job = WorkJob(
                kind="quarantine-single-purge",
                status="queued",
                state_json=json.dumps(
                    {
                        "entry_id": int(entry.id),
                        "confirmation": confirmation,
                        "requested_by_user_id": user_id,
                        "frozen_manifest": frozen,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                progress_current=0,
                progress_total=len(frozen.get("owned_paths") or []),
                progress_message=f"Queued permanent clear for quarantine entry #{entry.id}",
                created_at=utcnow(),
            )
            session.add(job)
            session.flush()
            session.add(AuditEvent(
                operation="quarantine.single_purge_enqueue",
                path=str(entry.quarantine_path),
                result="queued",
                details_json=json.dumps(
                    {
                        "quarantine_entry_id": int(entry.id),
                        "work_job_id": int(job.id),
                        "purge_semantics": SEMANTICS_VERSION,
                        "requested_by_user_id": user_id,
                        "frozen_manifest_digest": frozen.get("manifest_digest"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ))
            session.commit()
            return {
                "id": int(entry.id),
                "entry_id": int(entry.id),
                "status": "queued",
                "state": str(entry.state),
                "work_job_id": int(job.id),
                "purge_semantics": SEMANTICS_VERSION,
            }
