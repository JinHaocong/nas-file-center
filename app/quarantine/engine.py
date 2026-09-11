from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence
import uuid
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models import QuarantineEntry, utcnow
from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease
from app.quarantine.candidate import qualify_candidate_anchor_fd
from app.quarantine.tx_allocator import allocate_next_generation


def execute_transactional_quarantine(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str,
    allowed_roots: Sequence[Path | str] | None = None,
) -> None:
    """
    Executes transactional quarantine mutation for COMPAT_TRANSACTIONAL mode.

    Protocol (5-step fenced flow):
    1. Allocation: Monotonic attempt generation allocation committed in DB before mkdir.
       Pattern A fence before os.mkdir.
    2. Candidate Anchor & Qualification:
       Pattern A fence before os.link(source, candidate_anchor).
       Open candidate descriptor, run qualify_candidate_anchor_fd against Gate3 baseline.
       If mismatch: transition to conflict (Pattern B), preserve candidate anchor in place (ZERO unlink), abort.
       If match: promote to authoritative anchor in DB (Pattern B).
    3. Public Publication:
       Pattern A fence before os.link(authoritative_anchor, public_quarantine_path).
       Advance to public_published in DB (Pattern B).
    4. Source Capture:
       Write-once capture slot: Pattern A fence before os.rename(source, captured_source).
       Advance to source_captured in DB (Pattern B).
    5. Post-Capture Verification:
       Verify captured source matches expected dev and ino.
       If match: promote entry to state='active', tx_phase='active' (Pattern B).
       If foreign: transition entry to state='conflict', tx_phase='conflict' (Pattern B).
    """
    # Initialize / verify entry under Pattern B
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if not entry:
            raise ValueError(f"QuarantineEntry {entry_id} not found")
        source_path = Path(entry.original_path)
        quarantine_path = Path(entry.quarantine_path)
        expected_dev = entry.device
        expected_ino = entry.inode
        expected_size = entry.size
        expected_hash = entry.content_hash
        expected_mtime_ns = entry.mtime_ns
        if not entry.tx_token:
            entry.tx_token = uuid.uuid4().hex
        entry.tx_phase = "preparing"
        session.commit()

    # Step 1: Allocate generation & attempt directory
    gen, attempt_dir = allocate_next_generation(session_factory, entry_id, worker_id)
    renew_and_assert_worker_lease(session_factory, worker_id)
    attempt_dir.mkdir(parents=True, exist_ok=False)

    # Step 2: Candidate Anchor Creation & Qualification
    candidate_anchor_path = attempt_dir / "anchor"
    renew_and_assert_worker_lease(session_factory, worker_id)
    os.link(str(source_path), str(candidate_anchor_path))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        entry.tx_phase = "candidate_anchored"
        session.commit()

    fd = os.open(str(candidate_anchor_path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        qualified = qualify_candidate_anchor_fd(
            fd,
            expected_dev=expected_dev,
            expected_ino=expected_ino,
            expected_size=expected_size,
            expected_hash=expected_hash or "",
            expected_mtime_ns=expected_mtime_ns if (expected_mtime_ns and expected_mtime_ns > 0) else None,
        )
    finally:
        os.close(fd)

    if not qualified:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            entry.tx_phase = "conflict"
            entry.state = "conflict"
            entry.last_error = "candidate_anchor_qualification_failed"
            session.commit()
        raise RuntimeError("Candidate anchor qualification failed against Gate3 baseline; entering conflict")

    # Qualification passed -> promote to authoritative anchor
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        entry.tx_phase = "authoritative_anchored"
        entry.authoritative_anchor_path = str(candidate_anchor_path)
        session.commit()

    # Step 3: Public Quarantine Publication
    if not quarantine_path.parent.exists():
        renew_and_assert_worker_lease(session_factory, worker_id)
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)

    renew_and_assert_worker_lease(session_factory, worker_id)
    try:
        os.link(str(candidate_anchor_path), str(quarantine_path))
    except Exception as exc:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            entry.state = "conflict"
            entry.tx_phase = "conflict"
            entry.last_error = f"Failed to publish to public quarantine path: {exc}"
            entry.updated_at = utcnow()
            session.commit()
        raise

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        entry.tx_phase = "public_published"
        session.commit()

    # Step 4: Source Capture via Write-Once Slot
    captured_source_path = attempt_dir / "captured_source"
    if not captured_source_path.exists():
        renew_and_assert_worker_lease(session_factory, worker_id)
        os.rename(str(source_path), str(captured_source_path))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        entry.tx_phase = "source_captured"
        session.commit()

    # Step 5: Post-Capture Verification & Promotion
    st_captured = os.lstat(str(captured_source_path))
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        now = utcnow()
        if st_captured.st_dev == expected_dev and st_captured.st_ino == expected_ino:
            entry.tx_phase = "active"
            entry.state = "active"
            entry.quarantined_at = now
            entry.updated_at = now
            session.commit()
        else:
            entry.tx_phase = "conflict"
            entry.state = "conflict"
            entry.last_error = f"foreign_inode_captured: expected {expected_dev}:{expected_ino}, got {st_captured.st_dev}:{st_captured.st_ino}"
            entry.updated_at = now
            session.commit()
            raise RuntimeError(f"Foreign inode captured in slot: expected {expected_dev}:{expected_ino}, got {st_captured.st_dev}:{st_captured.st_ino}")
