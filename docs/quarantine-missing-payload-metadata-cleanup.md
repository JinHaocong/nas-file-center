# Externally missing quarantine payload: metadata-only retirement

Related: [Issue #359](https://github.com/JinHaocong/nas-file-center/issues/359), [incident #357](https://github.com/JinHaocong/nas-file-center/issues/357).

## Why a separate action?

An owner may delete a file from `.nas-file-center-trash` using NAS tools. Its DB row may still be `active`, or an old nontransactional `purging` row may remain after a Docker restart. The normal terminal-record deletion path only handles `restored/purged/abandoned/conflict`; it may also retire NFC transaction directories. **Do not widen those terminal states or replay a permanent purge.**

A separate **admin-only** `DELETE /api/quarantine/{id}/missing-record?confirmation=CLEANUP_MISSING_RECORD` is available, only after `ALLOW_MUTATION` and `ALLOW_DELETE` are enabled. The UI labels it **清理缺失文件记录** and requires an explicit confirmation. This is strictly DB metadata retirement plus an `AuditEvent`: zero filesystem unlink, rmdir, rename, or cleanup jobs; the original payload is never touched by this API.

## Fail-closed proof

The server holds `BEGIN IMMEDIATE` while loading the row, inspecting source tasks/plans, checking path absence twice with `openat`-style nofollow directory handles, and committing deletion plus audit atomically.

- Only ordinary `active` or `purging` states qualify. Any tx token/phase/mode/anchor/generation/cross-storage identity/restore target blocks the action. Any `.tx/entry-{id}` namespace (including empty), file, symlink, unexpected parent type, unreadable path or missing quarantine mount blocks.
- Quarantine root is traversed from `/` without following symlinks. For an ordinary payload, **the full parent directory chain must exist and be safely accessible**; only the final leaf may be absent. A missing parent could be a detached nested mount and therefore blocks cleanup. For the optional `.tx` evidence namespace, absence of the `.tx` directory itself is allowed only after safely opening the configured quarantine root. Inability to open that root never proves deletion.
- Active associated task/item/plan, pending plan item pointing at the payload, or any active batch/quarantine Worker prevents retirement. An interrupted linked WorkJob with `WORKER_INTERRUPTED` blocks `purging` rows.
- A `purging` row must have last changed **before this API service instance started** and at least 10 minutes ago. This is a conservative guard for a legacy synchronous purge not represented as a WorkJob. If uncertain, reject and review `/recovery-diagnostic`, Worker logs and service deployment topology.
- The existing `_reconcile_single_transitional_entry` and Worker reconciliation remain separate and unchanged. Do not remove transaction evidence, force `purged`, or modify frozen plans.

**Residual concurrency limitation:** Filesystem changes outside the application cannot be transacted atomically with SQLite. Two descriptor-based checks narrow but do not eliminate a malicious or concurrent NAS operation that creates a payload immediately after verification. This endpoint performs **no filesystem deletion** even in such a race; if external tools are modifying the same subtree continuously, stop those operations before retiring records. For `purging`, use only with a known single API instance / old worker process fully stopped; otherwise fail closed and request human review.

No bulk endpoint in the initial implementation: prove single-record safety and regression/owner behavior first. Every attempt has a separate, server-enforced explicit confirmation; failed attempts retain the row and existing evidence.

## Verification / release boundary

Synthetic tests use pytest `tmp_path` mounts, SQLite and isolated admin/non-admin API clients. They check ordinary missing payload, aged pre-restart legacy `purging`, outstanding work, tx fields, `.tx` evidence, still-present/replaced payload, symlink ancestry, unavailable mount, permissions, and a simulated file appearance between checks. Frontend contract tests confirm the distinct endpoint and confirmation.

No API/Worker deployment to the real NAS is done in this PR. Do not invoke this action for #1106/#884 without first reading their real recovery diagnostics. Even after code CI succeeds, #357 stays OPEN and formal acceptance stays **69/74 (93.2%)**, with #70–#74 / 14 human boxes outstanding. Frontend changes require renewed visual evidence and owner review.
