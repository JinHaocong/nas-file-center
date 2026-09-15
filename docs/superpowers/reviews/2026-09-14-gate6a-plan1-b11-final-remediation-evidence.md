# Gate6-A Plan 1 B11 Final Remediation Evidence

Date: 2026-09-14

## Scope

This evidence closes the independent-review B11 blocker against candidate
`735781a5ef5cbe0444c439f7dbcd2ad268f6923d`.

The blocked behavior was:

- SQLite had already durably recorded `active_attempt_generation = N`;
- the process crashed before `attempt-N` reached the filesystem;
- recovery treated the missing directory as permission to allocate `N+1`;
- repeated pre-directory crashes could therefore advance N indefinitely.

That behavior contradicted the frozen Plan 1 recovery requirement: the durable
DB generation is allocation authority and recovery must reconstruct that exact
generation without advancing it.

## RED

Test-only commits changed the active recovery contract to require:

- durable generation `3` remains `3`;
- recovery creates `attempt-3/purge`;
- `attempt-4` remains absent.

Formal Gate6-A TDD run `34807117998` on test-only HEAD
`dafbf8df1f616ec3699e336aa28c246592e0851f` observed the expected RED:

- preserved Gate5-G regressions: PASS (`48/48`);
- Gate6-A focused suite: `1 failed, 65 passed, 30 skipped`;
- the only failure was
  `test_recovery_uses_current_durable_generation_after_repeated_pre_directory_crashes`,
  because `attempt-3/purge` was not created by the old implementation.

## GREEN implementation

`execute_transactional_purge_capture()` now treats a durable
`active_attempt_generation > frozen_generation` as the current recovery
authority.

If `attempt-N` is absent, recovery now:

1. verifies the existing attempt parent is a non-symlink directory;
2. renews/asserts the Worker lease;
3. creates exactly `attempt-N` with exclusive `os.mkdir`;
4. renews/asserts the Worker lease again;
5. creates exactly `attempt-N/purge` with exclusive `os.mkdir`;
6. continues capture using generation `N`;
7. never calls the generation allocator merely because the already-durable
   `attempt-N` directory is missing.

`current_generation == frozen_generation` still uses the normal allocator for a
new attempt, because no post-freeze purge generation has yet been durably
allocated.

The verified production fix was committed as
`7e3ca521bdef2e4847ac5e7d782514b9b07ca8f2`.

## GREEN evidence

Dedicated remediation workflow run `34807236090` completed SUCCESS.
It required all of the following before committing the production fix:

- exact patch application;
- `python -m py_compile app/quarantine/purge.py`;
- `git diff --check`;
- both B11 recovery contracts;
- transactional purge core/recovery regressions;
- preserved Gate5-G regressions.

The temporary patch script and remediation workflow were removed by the same
verified commit, so they are not part of the final candidate tree.

## Release-scope relationship

Plan 1 still keeps COMPAT/zfuse Permanent Purge fail-closed on the v0.3.6
release surface. This B11 fix is nevertheless required because the dormant purge
core/recovery state machine remains security-sensitive code and the Gate6-A
scope amendment explicitly requires its recovery invariants to be correct.

This evidence does not claim final closure. Any commit after the previous exact
candidate invalidates earlier exact-candidate TDD/Closure/NAS-image evidence.
The new exact candidate must pass fresh formal Gate6-A TDD, full Closure,
linux/amd64 packaging, and independent re-review before real-NAS acceptance.
