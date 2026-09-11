from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from app.exceptions import StateConflictError
from app.models import QuarantineEntry
from app.path_safety import validate_mutation_destination
from app.quarantine.paths import safe_quarantine_hash
from app.quarantine.candidate import qualify_candidate_anchor_fd


def validate_restore_destination_intent(
    entry: QuarantineEntry,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
    custom_target: str | None = None,
    conflict_policy: str = "skip",
) -> tuple[Path, Path]:
    """
    Fast validation of DB state and destination path intent without reading or hashing
    quarantine content. Safe to run inside short DB transactions.
    """
    if entry.state != "active":
        raise StateConflictError(f"Cannot restore quarantine entry in state '{entry.state}'")

    target = Path(entry.quarantine_path)
    if not target.exists():
        entry.state = "inconsistent"
        entry.last_error = f"Quarantined target file does not exist: {target}"
        raise StateConflictError(f"Quarantined target file does not exist: {target}")

    if conflict_policy == "manual":
        if not custom_target or not custom_target.strip():
            raise ValueError("custom_target is required when conflict_policy is 'manual'")
        dest = validate_mutation_destination(
            custom_target.strip(),
            allowed_roots,
            quarantine_root=quarantine_root,
        )
    else:
        dest = validate_mutation_destination(
            entry.original_path,
            allowed_roots,
            quarantine_root=quarantine_root,
        )

    return target, dest


def verify_quarantine_source_integrity(
    target: Path,
    expected_size: int | None = None,
    expected_hash: str | None = None,
) -> dict:
    """
    Verify quarantine source file existence, symlink-safety, size and content hash.
    MUST run outside SQLite write transactions.
    Returns verified stat dictionary snapshot.
    """
    target = Path(target)
    if not target.exists():
        raise StateConflictError(f"Quarantined target file does not exist: {target}")

    if target.is_symlink() or os.path.islink(target):
        raise ValueError("Quarantined target is a symlink, restore aborted")

    try:
        st_before = target.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"Stat failed on quarantined file: {exc}")

    if expected_size is not None and expected_size > 0:
        if st_before.st_size != expected_size:
            raise ValueError(f"Quarantined file size mismatch (expected {expected_size}, got {st_before.st_size})")

    if expected_hash:
        current_hash = safe_quarantine_hash(target)
        if current_hash != expected_hash:
            raise ValueError(f"Hash verification failed: Quarantined file hash mismatch (expected {expected_hash}, got {current_hash})")

    try:
        st_after = target.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"Post-hash stat failed on quarantined file: {exc}")

    before_mtime = getattr(st_before, "st_mtime_ns", int(st_before.st_mtime * 1e9))
    after_mtime = getattr(st_after, "st_mtime_ns", int(st_after.st_mtime * 1e9))
    before_ctime = getattr(st_before, "st_ctime_ns", int(st_before.st_ctime * 1e9))
    after_ctime = getattr(st_after, "st_ctime_ns", int(st_after.st_ctime * 1e9))

    if (
        getattr(st_before, "st_dev", 0) != getattr(st_after, "st_dev", 0)
        or getattr(st_before, "st_ino", 0) != getattr(st_after, "st_ino", 0)
        or st_before.st_size != st_after.st_size
        or before_mtime != after_mtime
        or before_ctime != after_ctime
    ):
        raise ValueError("Quarantined source modified during hash verification")

    return {
        "object_type": "file",
        "size": st_after.st_size,
        "mtime_ns": after_mtime,
        "ctime_ns": after_ctime,
        "device": getattr(st_after, "st_dev", 0),
        "inode": getattr(st_after, "st_ino", 0),
    }


def assert_source_unmodified(target: Path, verified_stat: dict) -> None:
    """
    Immediate pre-mutation fence check: verify that device, inode, size, mtime, and ctime
    have not changed since the source integrity was verified.
    """
    target = Path(target)
    try:
        st = target.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"Stat failed on quarantined source before mutation: {exc}")

    if verified_stat.get("device") is not None and getattr(st, "st_dev", 0) != verified_stat["device"]:
        raise ValueError("Quarantined source device modified before mutation")
    if verified_stat.get("inode") is not None and getattr(st, "st_ino", 0) != verified_stat["inode"]:
        raise ValueError("Quarantined source inode modified before mutation")
    if verified_stat.get("size") is not None and st.st_size != verified_stat["size"]:
        raise ValueError(f"Quarantined source size modified before mutation (expected {verified_stat['size']}, got {st.st_size})")
    if verified_stat.get("mtime_ns") is not None and getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)) != verified_stat["mtime_ns"]:
        raise ValueError("Quarantined source mtime modified before mutation")
    if verified_stat.get("ctime_ns") is not None and getattr(st, "st_ctime_ns", int(st.st_ctime * 1e9)) != verified_stat["ctime_ns"]:
        raise ValueError("Quarantined source ctime modified before mutation")


def validate_quarantine_for_restore(
    entry: QuarantineEntry,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
    custom_target: str | None = None,
    conflict_policy: str = "skip",
) -> tuple[Path, Path]:
    """
    Composite validation that checks both intent and content integrity.
    Mutates entry.state and entry.last_error on inconsistency before raising.
    Returns (quarantine_target_path, destination_path).
    """
    try:
        target, dest = validate_restore_destination_intent(
            entry,
            allowed_roots=allowed_roots,
            quarantine_root=quarantine_root,
            custom_target=custom_target,
            conflict_policy=conflict_policy,
        )
        verify_quarantine_source_integrity(target, entry.size, entry.content_hash)
        return target, dest
    except (StateConflictError, ValueError) as exc:
        entry.state = "inconsistent"
        entry.last_error = str(exc)
        raise


def execute_transactional_restore(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str | None,
    allowed_roots: Sequence[Path | str] | None = None,
    quarantine_root: Path | str | None = None,
    custom_target: str | None = None,
) -> None:
    """
    Executes transactional restore with public view retirement into write-once slot.
    Terminal condition:
    - Original path published from authoritative anchor.
    - Public quarantine view retired into write-once restore slot.
    - Authoritative anchor remains intact.
    - Foreign view: preserved where captured -> conflict.
    """
    if not worker_id or not str(worker_id).strip():
        raise PermissionError("Transactional restore requires valid worker authority / lease; direct unauthenticated API mutation is forbidden")

    from sqlalchemy import text
    from app.models import utcnow
    from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease
    from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
    from app.quarantine.tx_allocator import allocate_next_generation, allocate_and_create_attempt_dir

    if allowed_roots is None:
        from app.config import get_settings
        roots = list(get_settings().allowed_roots)
    else:
        roots = list(allowed_roots)

    q_root = Path(quarantine_root) if quarantine_root is not None else None
    if q_root is None:
        try:
            from app.config import get_settings
            q_root = Path(get_settings().quarantine_root)
        except Exception:
            q_root = None

    valid_roots = list(roots)
    if q_root and q_root not in valid_roots:
        valid_roots.append(q_root)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if not entry:
            raise ValueError(f"QuarantineEntry {entry_id} not found")
        if not entry.authoritative_anchor_path:
            raise StateConflictError(f"Entry {entry_id} lacks authoritative anchor")
        anchor_path = Path(entry.authoritative_anchor_path)
        if not anchor_path.exists():
            entry.state = "conflict"
            entry.tx_phase = "conflict"
            entry.last_error = f"Authoritative anchor missing: {anchor_path}"
            session.commit()
            raise StateConflictError(f"Authoritative anchor missing: {anchor_path}")

        expected_dev = entry.device
        expected_ino = entry.inode
        expected_size = entry.size
        expected_hash = entry.content_hash
        expected_mtime_ns = entry.mtime_ns

        target_candidate = custom_target if custom_target else entry.original_path
        dest_path = validate_mutation_destination(
            target_candidate,
            roots,
            quarantine_root=q_root,
        )
        public_quarantine_path = Path(entry.quarantine_path)

        initial_state = entry.state
        entry.state = "restoring"
        entry.tx_phase = "restoring"
        session.commit()

    attempt_dir = anchor_path.parent
    parent_tx = attempt_dir.parent

    if q_root is None:
        if len(anchor_path.parents) >= 4 and anchor_path.parents[2].name == ".tx":
            q_root = anchor_path.parents[3]
        elif public_quarantine_path.parent:
            q_root = public_quarantine_path.parent

    # Item 4: Reverification of Authoritative Anchor before any mutation
    is_valid = False
    try:
        with safe_open_parent_fd(anchor_path, valid_roots) as (src_dir_fd, src_leaf):
            fd = os.open(src_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=src_dir_fd)
            try:
                is_valid = qualify_candidate_anchor_fd(
                    fd,
                    expected_dev=expected_dev,
                    expected_ino=expected_ino,
                    expected_size=expected_size or 0,
                    expected_hash=expected_hash or "",
                    expected_mtime_ns=expected_mtime_ns,
                )
            finally:
                os.close(fd)
    except Exception:
        is_valid = False

    if not is_valid:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            entry.state = "conflict"
            entry.tx_phase = "conflict"
            entry.last_error = f"Authoritative anchor verification failed: {anchor_path}"
            session.commit()
        raise StateConflictError(f"Authoritative anchor verification failed: {anchor_path}")

    # Finding 3: Classify existing restore evidence first across all attempts (Frozen Variant 13)
    target_slot = None
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
                            expected_device=expected_dev,
                            expected_inode=expected_ino,
                            expected_size=expected_size or 0,
                            expected_hash=expected_hash or "",
                            expected_mtime_ns=expected_mtime_ns,
                        )
                    finally:
                        os.close(fd)
            except Exception:
                is_cv_valid = False

            if is_cv_valid:
                target_slot = cv
                break
            else:
                # Foreign / unexpected view captured: preserve in place, zero mutation, conflict!
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    assert_active_worker_lease(session, worker_id)
                    entry = session.get(QuarantineEntry, entry_id)
                    entry.state = "conflict"
                    entry.tx_phase = "conflict"
                    entry.last_error = f"Foreign quarantine view captured in slot: {cv}"
                    session.commit()
                raise StateConflictError(f"Foreign quarantine view captured in slot: {cv}")

    if target_slot is not None:
        # Existing expected captured view found: publish destination if missing, converge restored, zero new generation
        if dest_path.exists():
            st_dest = os.lstat(str(dest_path))
            if st_dest.st_dev != expected_dev or st_dest.st_ino != expected_ino:
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    assert_active_worker_lease(session, worker_id)
                    entry = session.get(QuarantineEntry, entry_id)
                    entry.state = "conflict"
                    entry.tx_phase = "conflict"
                    entry.last_error = f"Destination path occupied by foreign inode: {dest_path}"
                    session.commit()
                raise FileExistsError(f"Destination path occupied by foreign inode: {dest_path}")
        else:
            if not dest_path.parent.exists():
                renew_and_assert_worker_lease(session_factory, worker_id)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
            with safe_open_parent_fd(anchor_path, valid_roots) as (src_dir_fd, src_leaf):
                with safe_open_parent_fd(dest_path, valid_roots) as (dst_dir_fd, dst_leaf):
                    renew_and_assert_worker_lease(session_factory, worker_id)
                    os.link(src_leaf, dst_leaf, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            now = utcnow()
            entry.state = "restored"
            entry.tx_phase = "restored"
            entry.restored_at = now
            entry.updated_at = now
            session.commit()
        return

    # No captured view in any generation:
    if public_quarantine_path.exists():
        # Destination link from Authoritative Anchor using descriptor-relative safe traversal
        if dest_path.exists():
            st_dest = os.lstat(str(dest_path))
            if st_dest.st_dev != expected_dev or st_dest.st_ino != expected_ino:
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    assert_active_worker_lease(session, worker_id)
                    entry = session.get(QuarantineEntry, entry_id)
                    entry.state = "conflict"
                    entry.tx_phase = "conflict"
                    entry.last_error = f"Destination path occupied by foreign inode: {dest_path}"
                    session.commit()
                raise FileExistsError(f"Destination path occupied by foreign inode: {dest_path}")
        else:
            if not dest_path.parent.exists():
                renew_and_assert_worker_lease(session_factory, worker_id)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
            with safe_open_parent_fd(anchor_path, valid_roots) as (src_dir_fd, src_leaf):
                with safe_open_parent_fd(dest_path, valid_roots) as (dst_dir_fd, dst_leaf):
                    renew_and_assert_worker_lease(session_factory, worker_id)
                    os.link(src_leaf, dst_leaf, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        # Finding 2: If this is a lease takeover / retry of an interrupted restore, allocate attempt-(G+1) exclusively
        if initial_state == "restoring":
            restore_gen, restore_attempt_dir = allocate_and_create_attempt_dir(
                session_factory, entry_id, worker_id, quarantine_root=q_root
            )
            captured_view_slot = restore_attempt_dir / "captured_quarantine_view"
        else:
            captured_view_slot = attempt_dir / "captured_quarantine_view"

        with safe_open_parent_fd(public_quarantine_path, valid_roots) as (src_dir_fd, src_leaf):
            with safe_open_parent_fd(captured_view_slot, valid_roots) as (dst_dir_fd, dst_leaf):
                renew_and_assert_worker_lease(session_factory, worker_id)
                os.rename(src_leaf, dst_leaf, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        # Terminal qualification of retired view
        is_retired_valid = False
        try:
            with safe_open_parent_fd(captured_view_slot, valid_roots) as (cv_dir_fd, cv_leaf):
                fd = os.open(cv_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=cv_dir_fd)
                try:
                    is_retired_valid = qualify_candidate_anchor_fd(
                        fd,
                        expected_device=expected_dev,
                        expected_inode=expected_ino,
                        expected_size=expected_size or 0,
                        expected_hash=expected_hash or "",
                        expected_mtime_ns=expected_mtime_ns,
                    )
                finally:
                    os.close(fd)
        except Exception:
            is_retired_valid = False

        if is_retired_valid:
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                assert_active_worker_lease(session, worker_id)
                entry = session.get(QuarantineEntry, entry_id)
                now = utcnow()
                entry.state = "restored"
                entry.tx_phase = "restored"
                entry.restored_at = now
                entry.updated_at = now
                session.commit()
            return
        else:
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                assert_active_worker_lease(session, worker_id)
                entry = session.get(QuarantineEntry, entry_id)
                now = utcnow()
                entry.state = "conflict"
                entry.tx_phase = "conflict"
                entry.last_error = f"Retired quarantine view qualification failed: {captured_view_slot}"
                entry.updated_at = now
                session.commit()
            raise RuntimeError(f"Retired quarantine view qualification failed: {captured_view_slot}")
    else:
        # Neither captured_view nor pub_path exists: cannot prove retirement occurred! Fail-closed to conflict.
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            now = utcnow()
            entry.state = "conflict"
            entry.tx_phase = "conflict"
            entry.last_error = "Public quarantine view absent and captured view slot missing: cannot prove retirement"
            entry.updated_at = now
            session.commit()
        raise RuntimeError("Public quarantine view absent and captured view slot missing: cannot prove retirement")

