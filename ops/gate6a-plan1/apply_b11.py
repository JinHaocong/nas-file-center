from pathlib import Path

path = Path("app/quarantine/purge.py")
source = path.read_text()
old = '''    elif current_state == "purging" and current_tx_phase == "purging":
        frozen_generation = _frozen_selected_attempt_generation(frozen_manifest, entry_id)
        if current_generation != frozen_generation:
            current_attempt_dir = (
                q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{current_generation}"
            )
            allocation_only_crash = (
                current_generation == frozen_generation + 1
                and not os.path.lexists(current_attempt_dir)
            )
            resumable_capture = (
                current_generation == frozen_generation + 1
                and current_attempt_dir.is_dir()
                and (current_attempt_dir / "purge").is_dir()
            )
            if resumable_capture:
                purge_dir = current_attempt_dir / "purge"
            elif not allocation_only_crash:
                raise StateConflictError(
                    "PURGE_RECOVERY_REQUIRED: purge capture generation already advanced "
                    f"(frozen={frozen_generation}, current={current_generation})"
                )
'''
new = '''    elif current_state == "purging" and current_tx_phase == "purging":
        frozen_generation = _frozen_selected_attempt_generation(frozen_manifest, entry_id)
        if current_generation < frozen_generation:
            raise StateConflictError(
                "PURGE_RECOVERY_REQUIRED: purge capture generation regressed "
                f"(frozen={frozen_generation}, current={current_generation})"
            )
        if current_generation > frozen_generation:
            current_attempt_dir = (
                q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{current_generation}"
            )
            if os.path.lexists(current_attempt_dir):
                if current_attempt_dir.is_symlink() or not current_attempt_dir.is_dir():
                    raise StateConflictError(
                        "PURGE_RECOVERY_REQUIRED: current purge attempt is not a safe directory "
                        f"(generation={current_generation})"
                    )
                current_purge_dir = current_attempt_dir / "purge"
                if os.path.lexists(current_purge_dir):
                    if current_purge_dir.is_symlink() or not current_purge_dir.is_dir():
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: current purge namespace is not a safe directory "
                            f"(generation={current_generation})"
                        )
                    purge_dir = current_purge_dir
                else:
                    try:
                        attempt_children = list(current_attempt_dir.iterdir())
                    except OSError as exc:
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: cannot classify current purge attempt "
                            f"(generation={current_generation}): {exc}"
                        ) from exc
                    if attempt_children:
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: current purge attempt contains unexpected evidence "
                            f"(generation={current_generation})"
                        )
                    renew_and_assert_worker_lease(session_factory, worker)
                    try:
                        os.mkdir(current_purge_dir, mode=0o700)
                    except FileExistsError as exc:
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: purge namespace appeared during recovery "
                            f"(generation={current_generation})"
                        ) from exc
                    purge_dir = current_purge_dir
            # If the current attempt directory is absent, the generation was only
            # durably allocated. Allocate a fresh monotonic generation below. This
            # remains valid even after multiple consecutive allocation-only crashes.
'''
count = source.count(old)
assert count == 1, f"expected one B11 recovery block, got {count}"
path.write_text(source.replace(old, new))
