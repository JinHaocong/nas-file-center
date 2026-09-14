from pathlib import Path

path = Path("app/quarantine/purge.py")
text = path.read_text()
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
                "PURGE_RECOVERY_REQUIRED: purge generation regressed "
                f"(frozen={frozen_generation}, current={current_generation})"
            )
        if current_generation > frozen_generation:
            # active_attempt_generation is the durable allocation authority. A crash
            # after its DB commit must resume that exact generation; recovery must
            # never allocate another generation merely because attempt/purge mkdir
            # had not completed yet.
            current_attempt_dir = (
                q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{current_generation}"
            )
            if os.path.lexists(current_attempt_dir):
                if current_attempt_dir.is_symlink() or not current_attempt_dir.is_dir():
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: allocated attempt path is not a safe directory: {current_attempt_dir}"
                    )
            else:
                renew_and_assert_worker_lease(session_factory, worker)
                try:
                    os.mkdir(current_attempt_dir, mode=0o700)
                except FileExistsError:
                    if current_attempt_dir.is_symlink() or not current_attempt_dir.is_dir():
                        raise StateConflictError(
                            f"PURGE_RECOVERY_REQUIRED: allocated attempt path was replaced: {current_attempt_dir}"
                        )
                except OSError as exc:
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: cannot recreate allocated attempt directory {current_attempt_dir}: {exc}"
                    ) from exc

            purge_candidate = current_attempt_dir / "purge"
            if os.path.lexists(purge_candidate):
                if purge_candidate.is_symlink() or not purge_candidate.is_dir():
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: purge namespace is not a safe directory: {purge_candidate}"
                    )
                try:
                    attempt_children = set(os.listdir(current_attempt_dir))
                except OSError as exc:
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: cannot inspect allocated attempt directory {current_attempt_dir}: {exc}"
                    ) from exc
                if attempt_children != {"purge"}:
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: unknown content in allocated attempt directory: {current_attempt_dir}"
                    )
                purge_dir = purge_candidate
            else:
                try:
                    attempt_children = os.listdir(current_attempt_dir)
                except OSError as exc:
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: cannot inspect allocated attempt directory {current_attempt_dir}: {exc}"
                    ) from exc
                if attempt_children:
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: unknown content in allocated attempt directory: {current_attempt_dir}"
                    )
                renew_and_assert_worker_lease(session_factory, worker)
                try:
                    os.mkdir(purge_candidate, mode=0o700)
                except FileExistsError:
                    if purge_candidate.is_symlink() or not purge_candidate.is_dir():
                        raise StateConflictError(
                            f"PURGE_RECOVERY_REQUIRED: purge namespace was replaced: {purge_candidate}"
                        )
                except OSError as exc:
                    raise StateConflictError(
                        f"PURGE_RECOVERY_REQUIRED: cannot create purge namespace {purge_candidate}: {exc}"
                    ) from exc
                purge_dir = purge_candidate
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one B11 recovery block, found {count}")
path.write_text(text.replace(old, new, 1))
