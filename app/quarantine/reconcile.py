from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence
from sqlalchemy import text, select
from sqlalchemy.orm import Session, sessionmaker, object_session

from app.models import QuarantineEntry, utcnow
from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease
from app.quarantine.candidate import qualify_candidate_anchor_fd
from app.quarantine.tx_allocator import allocate_next_generation


def reconcile_quarantine_transaction(
    target: sessionmaker | Session | QuarantineEntry | int,
    entry_id_or_worker: int | str | None = None,
    worker_id: str | None = None,
    session_factory: sessionmaker | None = None,
) -> None:
    """
    Unified Crash Reconciliation Engine implementing all 13 DB-Lag variants.
    Reconciles in-progress or interrupted transactional quarantine entries.
    Adheres strictly to the single-writer principle and Pattern A/B fences.
    """
    actual_factory: sessionmaker | None = None
    actual_entry_id: int | None = None
    actual_worker_id: str | None = None

    if isinstance(target, QuarantineEntry):
        actual_entry_id = target.id
        actual_worker_id = entry_id_or_worker if isinstance(entry_id_or_worker, str) else worker_id
        if session_factory:
            actual_factory = session_factory
        else:
            s = object_session(target)
            if s:
                actual_factory = sessionmaker(bind=s.get_bind())
            else:
                raise ValueError("QuarantineEntry has no attached session and no session_factory provided")
    elif isinstance(target, Session):
        actual_entry_id = int(entry_id_or_worker)
        actual_worker_id = worker_id
        actual_factory = session_factory or sessionmaker(bind=target.get_bind())
    elif isinstance(target, sessionmaker):
        actual_factory = target
        actual_entry_id = int(entry_id_or_worker)
        actual_worker_id = worker_id
    elif isinstance(target, int):
        actual_entry_id = target
        actual_worker_id = entry_id_or_worker if isinstance(entry_id_or_worker, str) else None
        actual_factory = session_factory
    else:
        raise TypeError(f"Unsupported target type: {type(target)}")

    if not actual_factory or actual_entry_id is None:
        raise ValueError("Both session_factory and entry_id must be resolvable")

    _run_reconciliation_flow(actual_factory, actual_entry_id, actual_worker_id)


def _run_reconciliation_flow(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str | None,
) -> None:
    # 1. Load entry state under Pattern B fence
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        if worker_id:
            assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if not entry:
            raise ValueError(f"QuarantineEntry #{entry_id} not found")

        state = entry.state
        tx_phase = entry.tx_phase
        orig_path = Path(entry.original_path)
        pub_path = Path(entry.quarantine_path)
        gen = entry.active_attempt_generation
        anchor_path_str = entry.authoritative_anchor_path
        dev = entry.device
        ino = entry.inode
        size = entry.size
        mtime_ns = entry.mtime_ns
        chash = entry.content_hash

    # If already in terminal or stable state, nothing to reconcile
    if state in ("active", "restored", "conflict", "purged"):
        return

    # Handle restoring state (Variants 10, 11, 12, 13)
    if state == "restoring":
        _reconcile_restoring(session_factory, entry_id, worker_id)
        return

    if state == "preparing":
        _reconcile_preparing(session_factory, entry_id, worker_id)
        return


def _reconcile_preparing(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str | None,
) -> None:
    # Read snapshot
    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        tx_phase = entry.tx_phase
        orig_path = Path(entry.original_path)
        pub_path = Path(entry.quarantine_path)
        gen = entry.active_attempt_generation
        anchor_path_str = entry.authoritative_anchor_path
        dev = entry.device
        ino = entry.inode
        size = entry.size
        mtime_ns = entry.mtime_ns
        chash = entry.content_hash

    q_root = pub_path.parent
    tx_base = q_root / ".tx" / f"entry-{entry_id}"

    # Phase 1: Preparing & Candidate Anchor (Variants 1, 2, 3)
    if tx_phase == "preparing":
        attempt_dir = tx_base / f"attempt-{gen}"
        candidate_anchor = attempt_dir / "anchor"

        if not attempt_dir.exists() or not candidate_anchor.exists():
            # Variant 1 / 3: Candidate anchor missing
            if not orig_path.exists():
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Original source missing during crash reconciliation: {orig_path}"
                    e.updated_at = utcnow()
                    session.commit()
                return

            # Allocate generation and retry attempt dir under Pattern A fence
            new_gen = allocate_next_generation(session_factory, entry_id, worker_id)
            new_attempt = tx_base / f"attempt-{new_gen}"
            if worker_id:
                renew_and_assert_worker_lease(session_factory, worker_id)
            new_attempt.mkdir(parents=True, exist_ok=True)
            # Retain in preparing phase for execution engine
            return

        # Variant 2: Candidate anchor exists
        fd = os.open(str(candidate_anchor), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        err_msg = "Candidate anchor does not match expected Gate3 identity"
        try:
            is_valid = qualify_candidate_anchor_fd(
                fd,
                expected_device=dev,
                expected_inode=ino,
                expected_size=size,
                expected_mtime_ns=mtime_ns,
                expected_hash=chash,
            )
        except Exception as ex:
            is_valid = False
            err_msg = str(ex)
        finally:
            os.close(fd)

        if not is_valid:
            # Variant 2 mismatch: set conflict under Pattern B fence, zero unlink, zero retry
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = f"Candidate anchor qualification failed: {err_msg}"
                e.updated_at = utcnow()
                session.commit()
            return

        # Variant 2 match: promote to authoritative_anchored under Pattern B fence
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if worker_id:
                assert_active_worker_lease(session, worker_id)
            e = session.get(QuarantineEntry, entry_id)
            e.authoritative_anchor_path = str(candidate_anchor)
            e.tx_phase = "authoritative_anchored"
            e.updated_at = utcnow()
            session.commit()
            tx_phase = "authoritative_anchored"
            anchor_path_str = str(candidate_anchor)

    # Phase 2: Authoritative Anchored -> Public Published (Variants 4, 5, 6)
    if tx_phase == "authoritative_anchored":
        anchor = Path(anchor_path_str)
        st_anchor = os.stat(str(anchor))

        if pub_path.exists():
            st_pub = os.lstat(str(pub_path))
            if st_pub.st_dev != st_anchor.st_dev or st_pub.st_ino != st_anchor.st_ino:
                # Variant 6: Foreign occupant at public path
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Public quarantine path occupied by foreign inode: {pub_path}"
                    e.updated_at = utcnow()
                    session.commit()
                return
            # Variant 5: Public path exists and matches anchor (FS succeeded, DB lagged)
        else:
            # Variant 4: Public path absent; link under Pattern A fence
            if worker_id:
                renew_and_assert_worker_lease(session_factory, worker_id)
            os.link(str(anchor), str(pub_path))

        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if worker_id:
                assert_active_worker_lease(session, worker_id)
            e = session.get(QuarantineEntry, entry_id)
            e.tx_phase = "public_published"
            e.updated_at = utcnow()
            session.commit()
            tx_phase = "public_published"

    # Phase 3: Public Published -> Source Captured -> Active (Variants 7, 8, 9)
    if tx_phase == "public_published":
        anchor = Path(anchor_path_str)
        st_anchor = os.stat(str(anchor))
        attempt_dir = anchor.parent
        captured_source = attempt_dir / "captured_source"

        if captured_source.exists():
            st_cap = os.lstat(str(captured_source))
            if st_cap.st_dev != st_anchor.st_dev or st_cap.st_ino != st_anchor.st_ino:
                # Variant 9: Captured source occupied by foreign inode
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Captured source slot occupied by foreign inode: {captured_source}"
                    e.updated_at = utcnow()
                    session.commit()
                return
            # Variant 8: Captured source matches anchor (FS succeeded, DB lagged)
        else:
            # Variant 7: Captured source absent, check original source path
            if not orig_path.exists():
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Source path missing before capture rename: {orig_path}"
                    e.updated_at = utcnow()
                    session.commit()
                return

            st_orig = os.lstat(str(orig_path))
            if st_orig.st_dev != st_anchor.st_dev or st_orig.st_ino != st_anchor.st_ino:
                # Source swapped
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Source path occupied by foreign inode before capture: {orig_path}"
                    e.updated_at = utcnow()
                    session.commit()
                return

            # Rename source into captured_source slot under Pattern A fence
            if worker_id:
                renew_and_assert_worker_lease(session_factory, worker_id)
            os.rename(str(orig_path), str(captured_source))

        # Finalize to Active under Pattern B fence
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if worker_id:
                assert_active_worker_lease(session, worker_id)
            e = session.get(QuarantineEntry, entry_id)
            now = utcnow()
            e.tx_phase = "active"
            e.state = "active"
            e.quarantined_at = e.quarantined_at or now
            e.updated_at = now
            session.commit()


def _reconcile_restoring(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str | None,
) -> None:
    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        orig_path = Path(entry.original_path)
        pub_path = Path(entry.quarantine_path)
        anchor_path_str = entry.authoritative_anchor_path

    if not anchor_path_str:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if worker_id:
                assert_active_worker_lease(session, worker_id)
            e = session.get(QuarantineEntry, entry_id)
            e.state = "conflict"
            e.tx_phase = "conflict"
            e.last_error = f"Entry lacks authoritative anchor path"
            e.updated_at = utcnow()
            session.commit()
        return

    anchor = Path(anchor_path_str)
    if not anchor.exists():
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if worker_id:
                assert_active_worker_lease(session, worker_id)
            e = session.get(QuarantineEntry, entry_id)
            e.state = "conflict"
            e.tx_phase = "conflict"
            e.last_error = f"Authoritative anchor missing on disk: {anchor}"
            e.updated_at = utcnow()
            session.commit()
        return

    st_anchor = os.stat(str(anchor))
    attempt_dir = anchor.parent
    captured_view = attempt_dir / "captured_quarantine_view"

    # Variant 10, 11, 12: Check original path
    if orig_path.exists():
        st_orig = os.lstat(str(orig_path))
        if st_orig.st_dev != st_anchor.st_dev or st_orig.st_ino != st_anchor.st_ino:
            # Variant 12: Destination occupied by foreign file
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = f"Original destination occupied by foreign inode: {orig_path}"
                e.updated_at = utcnow()
                session.commit()
            return
    else:
        # Variant 10: Original path absent, link from anchor under Pattern A fence
        if not orig_path.parent.exists():
            if worker_id:
                renew_and_assert_worker_lease(session_factory, worker_id)
            orig_path.parent.mkdir(parents=True, exist_ok=True)
        if worker_id:
            renew_and_assert_worker_lease(session_factory, worker_id)
        os.link(str(anchor), str(orig_path))

    # Variant 11, 13: View retirement
    if pub_path.exists() and not captured_view.exists():
        if worker_id:
            renew_and_assert_worker_lease(session_factory, worker_id)
        os.rename(str(pub_path), str(captured_view))

    if captured_view.exists():
        st_view = os.lstat(str(captured_view))
        if st_view.st_dev != st_anchor.st_dev or st_view.st_ino != st_anchor.st_ino:
            # Variant 11/13: Foreign view captured
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = f"Foreign quarantine view captured in slot: {captured_view}"
                e.updated_at = utcnow()
                session.commit()
            return
        else:
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                now = utcnow()
                e.state = "restored"
                e.tx_phase = "restored"
                e.restored_at = e.restored_at or now
                e.updated_at = now
                session.commit()
            return
    elif not pub_path.exists():
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if worker_id:
                assert_active_worker_lease(session, worker_id)
            e = session.get(QuarantineEntry, entry_id)
            now = utcnow()
            e.state = "restored"
            e.tx_phase = "restored"
            e.restored_at = e.restored_at or now
            e.updated_at = now
            session.commit()
        return
