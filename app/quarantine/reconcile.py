from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence
from sqlalchemy import text, select
from sqlalchemy.orm import Session, sessionmaker, object_session

from app.models import QuarantineEntry, utcnow
from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease
from app.quarantine.candidate import qualify_candidate_anchor_fd
from app.quarantine.tx_allocator import allocate_next_generation, allocate_and_create_attempt_dir
from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd


def reconcile_quarantine_transaction(
    target: Any,
    entry_id_or_worker: Any = None,
    worker_id: str | None = None,
    session_factory: sessionmaker | None = None,
    quarantine_root: Path | str | None = None,
    allowed_roots: Sequence[Path | str] | None = None,
) -> None:
    """
    Unified Crash Reconciliation Engine (Section 16).
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

    _run_reconciliation_flow(actual_factory, actual_entry_id, actual_worker_id, quarantine_root=quarantine_root, allowed_roots=allowed_roots)


def _run_reconciliation_flow(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str | None,
    quarantine_root: Path | str | None = None,
    allowed_roots: Sequence[Path | str] | None = None,
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

    # If already in terminal or stable state, nothing to reconcile
    if state in ("active", "restored", "conflict", "purged"):
        return

    # Handle restoring state (Variants 10, 11, 12, 13)
    if state == "restoring":
        _reconcile_restoring(session_factory, entry_id, worker_id, quarantine_root=quarantine_root, allowed_roots=allowed_roots)
        return

    if state == "preparing":
        _reconcile_preparing(session_factory, entry_id, worker_id, quarantine_root=quarantine_root, allowed_roots=allowed_roots)
        return


def _reconcile_preparing(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str | None,
    quarantine_root: Path | str | None = None,
    allowed_roots: Sequence[Path | str] | None = None,
) -> None:
    # Read snapshot
    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        tx_phase = entry.tx_phase
        initial_tx_phase = tx_phase
        orig_path = Path(entry.original_path)
        pub_path = Path(entry.quarantine_path)
        gen = entry.active_attempt_generation
        anchor_path_str = entry.authoritative_anchor_path
        dev = entry.device
        ino = entry.inode
        size = entry.size
        mtime_ns = entry.mtime_ns
        chash = entry.content_hash

    q_root: Path | None = Path(quarantine_root) if quarantine_root is not None else None
    if q_root is None:
        if anchor_path_str:
            anchor_p = Path(anchor_path_str)
            if len(anchor_p.parents) >= 4 and anchor_p.parents[2].name == ".tx":
                q_root = anchor_p.parents[3]
        if q_root is None:
            curr = pub_path.parent
            while curr != curr.parent:
                if (curr / ".tx" / f"entry-{entry_id}").exists():
                    q_root = curr
                    break
                curr = curr.parent
        if q_root is None:
            try:
                from app.config import get_settings
                q_root = Path(get_settings().quarantine_root)
            except Exception:
                q_root = pub_path.parent
    tx_base = q_root / ".tx" / f"entry-{entry_id}"

    if allowed_roots is None:
        try:
            from app.config import get_settings
            roots = list(get_settings().allowed_roots)
        except Exception:
            roots = []
        try:
            if not any(orig_path.is_relative_to(Path(r)) for r in roots):
                roots.append(orig_path.parent)
        except Exception:
            pass
    else:
        roots = list(allowed_roots)

    valid_roots = list(roots)
    if q_root and q_root not in valid_roots:
        valid_roots.append(q_root)

    # Phase 1: Preparing & Candidate Anchor (Variants 1, 2, 3)
    if tx_phase in ("preparing", "candidate_anchored"):
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
            new_gen, new_attempt = allocate_and_create_attempt_dir(
                session_factory, entry_id, worker_id, quarantine_root=q_root
            )
            # Retain in preparing phase for execution engine
            return

        # Variant 2: Candidate anchor exists
        is_valid = False
        err_msg = "Candidate anchor does not match expected Gate3 identity"
        try:
            with safe_open_parent_fd(candidate_anchor, valid_roots) as (cand_dir_fd, cand_leaf):
                fd = os.open(cand_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=cand_dir_fd)
                try:
                    is_valid = qualify_candidate_anchor_fd(
                        fd,
                        expected_device=dev,
                        expected_inode=ino,
                        expected_size=size,
                        expected_mtime_ns=mtime_ns if (mtime_ns and mtime_ns > 0) else None,
                        expected_hash=chash,
                    )
                finally:
                    os.close(fd)
        except Exception as ex:
            is_valid = False
            err_msg = str(ex)

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
        if not anchor.exists():
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = f"Authoritative anchor missing: {anchor}"
                e.updated_at = utcnow()
                session.commit()
            return

        # Item 4: Reverification of Authoritative Anchor before public publication
        is_anchor_valid = False
        try:
            with safe_open_parent_fd(anchor, valid_roots) as (src_dir_fd, src_leaf):
                fd = os.open(src_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=src_dir_fd)
                try:
                    is_anchor_valid = qualify_candidate_anchor_fd(
                        fd,
                        expected_device=dev,
                        expected_inode=ino,
                        expected_size=size,
                        expected_mtime_ns=mtime_ns if (mtime_ns and mtime_ns > 0) else None,
                        expected_hash=chash,
                    )
                finally:
                    os.close(fd)
        except Exception:
            is_anchor_valid = False

        if not is_anchor_valid:
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = f"Authoritative anchor verification failed: {anchor}"
                e.updated_at = utcnow()
                session.commit()
            return

        if pub_path.exists():
            st_pub = os.lstat(str(pub_path))
            if st_pub.st_dev != dev or st_pub.st_ino != ino:
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
            # Variant 4: Public path absent; link under Pattern A fence using safe_open_parent_fd
            try:
                if not pub_path.parent.exists():
                    if worker_id:
                        renew_and_assert_worker_lease(session_factory, worker_id)
                    pub_path.parent.mkdir(parents=True, exist_ok=True)
                with safe_open_parent_fd(anchor, valid_roots) as (src_dir_fd, src_leaf):
                    with safe_open_parent_fd(pub_path, valid_roots) as (dst_dir_fd, dst_leaf):
                        if worker_id:
                            renew_and_assert_worker_lease(session_factory, worker_id)
                        os.link(src_leaf, dst_leaf, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
            except Exception as exc:
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Failed to link public quarantine path: {exc}"
                    e.updated_at = utcnow()
                    session.commit()
                return

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
        attempt_dir = anchor.parent
        parent_tx = attempt_dir.parent

        existing_captured = None
        for att in sorted(parent_tx.glob("attempt-*")):
            cs = att / "captured_source"
            if cs.exists():
                is_valid = False
                err_msg = ""
                try:
                    with safe_open_parent_fd(cs, valid_roots) as (cs_dir_fd, cs_leaf):
                        fd = os.open(cs_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=cs_dir_fd)
                        try:
                            is_valid = qualify_candidate_anchor_fd(
                                fd,
                                expected_device=dev,
                                expected_inode=ino,
                                expected_size=size,
                                expected_mtime_ns=mtime_ns if (mtime_ns and mtime_ns > 0) else None,
                                expected_hash=chash,
                            )
                        finally:
                            os.close(fd)
                except Exception as ex:
                    is_valid = False
                    err_msg = str(ex)

                if is_valid:
                    existing_captured = cs
                    break
                else:
                    # Variant 9 / Hotfix 3: Captured source slot qualification failed
                    with session_factory() as session:
                        session.execute(text("BEGIN IMMEDIATE"))
                        if worker_id:
                            assert_active_worker_lease(session, worker_id)
                        e = session.get(QuarantineEntry, entry_id)
                        e.state = "conflict"
                        e.tx_phase = "conflict"
                        e.last_error = f"Captured source slot qualification failed: {cs} ({err_msg})"
                        e.updated_at = utcnow()
                        session.commit()
                    return

        if existing_captured is None:
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
            if st_orig.st_dev != dev or st_orig.st_ino != ino:
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

            # Variant 7 / Hotfix 3: Allocate dedicated generation slot exclusively if interrupted after public publication
            if initial_tx_phase == "public_published":
                new_gen, new_attempt = allocate_and_create_attempt_dir(
                    session_factory, entry_id, worker_id, quarantine_root=q_root
                )
                captured_source = new_attempt / "captured_source"
            else:
                captured_source = attempt_dir / "captured_source"

            try:
                with safe_open_parent_fd(orig_path, valid_roots) as (src_dir_fd, src_leaf):
                    with safe_open_parent_fd(captured_source, valid_roots) as (dst_dir_fd, dst_leaf):
                        if worker_id:
                            renew_and_assert_worker_lease(session_factory, worker_id)
                        os.rename(src_leaf, dst_leaf, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
            except Exception as exc:
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Failed to rename source into captured slot: {exc}"
                    e.updated_at = utcnow()
                    session.commit()
                return

            # Full post-capture qualification before active (Finding 1)
            is_valid = False
            err_msg = ""
            try:
                with safe_open_parent_fd(captured_source, valid_roots) as (cs_dir_fd, cs_leaf):
                    fd = os.open(cs_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=cs_dir_fd)
                    try:
                        is_valid = qualify_candidate_anchor_fd(
                            fd,
                            expected_device=dev,
                            expected_inode=ino,
                            expected_size=size,
                            expected_mtime_ns=mtime_ns if (mtime_ns and mtime_ns > 0) else None,
                            expected_hash=chash,
                        )
                    finally:
                        os.close(fd)
            except Exception as ex:
                is_valid = False
                err_msg = str(ex)

            if not is_valid:
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Captured source qualification failed after rename: {captured_source} ({err_msg})"
                    e.updated_at = utcnow()
                    session.commit()
                return

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
    quarantine_root: Path | str | None = None,
    allowed_roots: Sequence[Path | str] | None = None,
) -> None:
    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        orig_path = Path(entry.original_path)
        pub_path = Path(entry.quarantine_path)
        anchor_path_str = entry.authoritative_anchor_path
        dev = entry.device
        ino = entry.inode
        size = entry.size
        mtime_ns = entry.mtime_ns
        chash = entry.content_hash

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

    q_root: Path | None = Path(quarantine_root) if quarantine_root is not None else None
    if q_root is None:
        if len(anchor.parents) >= 4 and anchor.parents[2].name == ".tx":
            q_root = anchor.parents[3]
        if q_root is None:
            try:
                from app.config import get_settings
                q_root = Path(get_settings().quarantine_root)
            except Exception:
                q_root = pub_path.parent

    if allowed_roots is None:
        try:
            from app.config import get_settings
            roots = list(get_settings().allowed_roots)
        except Exception:
            roots = []
        try:
            if not any(orig_path.is_relative_to(Path(r)) for r in roots):
                roots.append(orig_path.parent)
        except Exception:
            pass
    else:
        roots = list(allowed_roots)

    valid_roots = list(roots)
    if q_root and q_root not in valid_roots:
        valid_roots.append(q_root)

    # Reverification of Authoritative Anchor before restore reconciliation
    is_anchor_valid = False
    try:
        with safe_open_parent_fd(anchor, valid_roots) as (src_dir_fd, src_leaf):
            fd = os.open(src_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=src_dir_fd)
            try:
                is_anchor_valid = qualify_candidate_anchor_fd(
                    fd,
                    expected_device=dev,
                    expected_inode=ino,
                    expected_size=size,
                    expected_mtime_ns=mtime_ns if (mtime_ns and mtime_ns > 0) else None,
                    expected_hash=chash,
                )
            finally:
                os.close(fd)
    except Exception:
        is_anchor_valid = False

    if not is_anchor_valid:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if worker_id:
                assert_active_worker_lease(session, worker_id)
            e = session.get(QuarantineEntry, entry_id)
            e.state = "conflict"
            e.tx_phase = "conflict"
            e.last_error = f"Authoritative anchor qualification failed before restore: {anchor}"
            e.updated_at = utcnow()
            session.commit()
        return

    # Finding 3: Existing Restore Evidence = Classify First (Frozen Variant 13)
    attempt_dir = anchor.parent
    parent_tx = attempt_dir.parent

    target_view_slot = None
    for att in sorted(parent_tx.glob("attempt-*")):
        cv = att / "captured_quarantine_view"
        if cv.exists():
            is_cv_valid = False
            try:
                with safe_open_parent_fd(cv, valid_roots) as (cv_dir_fd, cv_leaf):
                    fd = os.open(cv_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=cv_dir_fd)
                    try:
                        is_cv_valid = qualify_candidate_anchor_fd(
                            fd,
                            expected_device=dev,
                            expected_inode=ino,
                            expected_size=size,
                            expected_mtime_ns=mtime_ns if (mtime_ns and mtime_ns > 0) else None,
                            expected_hash=chash,
                        )
                    finally:
                        os.close(fd)
            except Exception:
                is_cv_valid = False

            if is_cv_valid:
                target_view_slot = cv
                break
            else:
                # Finding 3.2: Foreign / corrupted view slot -> immediate conflict, ZERO further mutation!
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if worker_id:
                        assert_active_worker_lease(session, worker_id)
                    e = session.get(QuarantineEntry, entry_id)
                    e.state = "conflict"
                    e.tx_phase = "conflict"
                    e.last_error = f"Foreign quarantine view captured in slot: {cv}"
                    e.updated_at = utcnow()
                    session.commit()
                return

    # If no valid captured view exists across all generations:
    if target_view_slot is None:
        if not pub_path.exists():
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                now = utcnow()
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = "Public quarantine view absent and captured view slot missing: cannot prove retirement"
                e.updated_at = now
                session.commit()
            return

        # Finding 2 & 4: New worker must allocate attempt-(G+1) exclusively and retire pub_path
        new_gen, new_attempt = allocate_and_create_attempt_dir(
            session_factory, entry_id, worker_id, quarantine_root=q_root
        )
        captured_view = new_attempt / "captured_quarantine_view"

        try:
            with safe_open_parent_fd(pub_path, valid_roots) as (src_dir_fd, src_leaf):
                with safe_open_parent_fd(captured_view, valid_roots) as (dst_dir_fd, dst_leaf):
                    if worker_id:
                        renew_and_assert_worker_lease(session_factory, worker_id)
                    os.rename(src_leaf, dst_leaf, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
            target_view_slot = captured_view
        except Exception as exc:
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = f"Failed to retire public quarantine view: {exc}"
                e.updated_at = utcnow()
                session.commit()
            return

        # Terminal qualification of retired view
        is_retired_valid = False
        try:
            with safe_open_parent_fd(captured_view, valid_roots) as (cv_dir_fd, cv_leaf):
                fd = os.open(cv_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=cv_dir_fd)
                try:
                    is_retired_valid = qualify_candidate_anchor_fd(
                        fd,
                        expected_device=dev,
                        expected_inode=ino,
                        expected_size=size,
                        expected_mtime_ns=mtime_ns if (mtime_ns and mtime_ns > 0) else None,
                        expected_hash=chash,
                    )
                finally:
                    os.close(fd)
        except Exception:
            is_retired_valid = False

        if not is_retired_valid:
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

    # View retirement is confirmed valid. Ensure original destination is linked to authoritative anchor.
    if orig_path.exists():
        st_orig = os.lstat(str(orig_path))
        if st_orig.st_dev != dev or st_orig.st_ino != ino:
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
        try:
            if not orig_path.parent.exists():
                if worker_id:
                    renew_and_assert_worker_lease(session_factory, worker_id)
                orig_path.parent.mkdir(parents=True, exist_ok=True)
            with safe_open_parent_fd(anchor, valid_roots) as (src_dir_fd, src_leaf):
                with safe_open_parent_fd(orig_path, valid_roots) as (dst_dir_fd, dst_leaf):
                    if worker_id:
                        renew_and_assert_worker_lease(session_factory, worker_id)
                    os.link(src_leaf, dst_leaf, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        except Exception as exc:
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if worker_id:
                    assert_active_worker_lease(session, worker_id)
                e = session.get(QuarantineEntry, entry_id)
                e.state = "conflict"
                e.tx_phase = "conflict"
                e.last_error = f"Failed to link original destination: {exc}"
                e.updated_at = utcnow()
                session.commit()
            return

    # Finalize to restored
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

