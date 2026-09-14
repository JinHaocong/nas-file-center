from pathlib import Path

path = Path("app/quarantine/purge.py")
text = path.read_text()
old = '''            # If the current attempt directory is absent, the generation was only
            # durably allocated. Allocate a fresh monotonic generation below. This
            # remains valid even after multiple consecutive allocation-only crashes.
'''
new = '''            else:
                # The DB generation is already durable allocation authority. If its
                # attempt directory never reached the filesystem, recover that exact
                # generation rather than allocating N+1 again. Repeated crashes before
                # mkdir must therefore remain pinned to the same durable generation.
                attempt_parent = current_attempt_dir.parent
                if (
                    not os.path.lexists(attempt_parent)
                    or attempt_parent.is_symlink()
                    or not attempt_parent.is_dir()
                ):
                    raise StateConflictError(
                        "PURGE_RECOVERY_REQUIRED: current purge attempt parent is not a safe directory "
                        f"(generation={current_generation})"
                    )
                renew_and_assert_worker_lease(session_factory, worker)
                try:
                    os.mkdir(current_attempt_dir, mode=0o700)
                except FileExistsError as exc:
                    raise StateConflictError(
                        "PURGE_RECOVERY_REQUIRED: current purge attempt appeared during recovery "
                        f"(generation={current_generation})"
                    ) from exc

                current_purge_dir = current_attempt_dir / "purge"
                renew_and_assert_worker_lease(session_factory, worker)
                try:
                    os.mkdir(current_purge_dir, mode=0o700)
                except FileExistsError as exc:
                    raise StateConflictError(
                        "PURGE_RECOVERY_REQUIRED: purge namespace appeared during recovery "
                        f"(generation={current_generation})"
                    ) from exc
                purge_dir = current_purge_dir
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one B11 recovery marker, found {count}")
path.write_text(text.replace(old, new, 1))
