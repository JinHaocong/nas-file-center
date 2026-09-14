from pathlib import Path

path = Path("app/quarantine/purge.py")
text = path.read_text()

helper_marker = "\n\ndef destroy_transactional_purge_capture(\n"
helper = r'''


def _fsync_zeroized_purge_tombstone(
    session_factory: Any,
    worker_id: str,
    captured_path: Path,
    valid_roots: list[Path],
    *,
    expected_device: int,
    expected_inode: int,
) -> None:
    """Prove durability of an already-zeroized exact payload inode without re-truncating it."""
    try:
        with safe_open_parent_fd(captured_path, valid_roots) as (dir_fd, leaf):
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(leaf, flags, dir_fd=dir_fd)
            try:
                before = os.fstat(fd)
                if not (
                    stat.S_ISREG(before.st_mode)
                    and before.st_dev == expected_device
                    and before.st_ino == expected_inode
                    and before.st_size == 0
                ):
                    raise StateConflictError(
                        f"PURGE_DURABILITY_FAILED: zeroized tombstone identity mismatch: {captured_path}"
                    )
                renew_and_assert_worker_lease(session_factory, worker_id)
                os.fsync(fd)
                after = os.fstat(fd)
                if not (
                    stat.S_ISREG(after.st_mode)
                    and after.st_dev == expected_device
                    and after.st_ino == expected_inode
                    and after.st_size == 0
                ):
                    raise StateConflictError(
                        f"PURGE_DURABILITY_FAILED: zeroized tombstone changed during fsync: {captured_path}"
                    )
            finally:
                os.close(fd)
    except StateConflictError:
        raise
    except OSError as exc:
        raise StateConflictError(
            f"PURGE_DURABILITY_FAILED: cannot fsync zeroized tombstone {captured_path}: {exc}"
        ) from exc
'''

if text.count(helper_marker) != 1:
    raise SystemExit(f"B9 helper insertion marker expected once, got {text.count(helper_marker)}")
text = text.replace(helper_marker, helper.rstrip() + helper_marker, 1)

old = '''    if not _read_destroy_marker(purge_dir, valid_roots, marker_expected):
        raise StateConflictError("PURGE_RECOVERY_REQUIRED: valid destroy-intent marker is required")
    _assert_zeroized_closure(
        purge_dir,
        valid_roots,
        aliases,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )

    with session_factory() as session:
'''
new = '''    if not _read_destroy_marker(purge_dir, valid_roots, marker_expected):
        raise StateConflictError("PURGE_RECOVERY_REQUIRED: valid destroy-intent marker is required")
    _assert_zeroized_closure(
        purge_dir,
        valid_roots,
        aliases,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )
    if not aliases:
        raise StateConflictError(
            "PURGE_RECOVERY_REQUIRED: frozen purge aliases are required for durability proof"
        )
    durability_path = purge_dir / _purge_slot_name(aliases[0])
    _fsync_zeroized_purge_tombstone(
        session_factory,
        worker,
        durability_path,
        valid_roots,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )
    _assert_zeroized_closure(
        purge_dir,
        valid_roots,
        aliases,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )

    with session_factory() as session:
'''
if text.count(old) != 1:
    raise SystemExit(f"B9 terminal durability block expected once, got {text.count(old)}")
text = text.replace(old, new, 1)
path.write_text(text)
