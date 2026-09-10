# Gate5-G Final Validation Execution Plan Checkpoint

**Date:** 2026-09-10
**Target Branch:** `v0.3.5-gate5c-hotfix4`
**APPROVED_FREEZE_HEAD:** `073a69eb1e001e1738c32739f9b57820cba1b05f`

---

## 1. Gate Status Declarations

```text
Gate5-G Architecture / Validation Freeze
= PASS / APPROVED / CLOSED

APPROVED_FREEZE_HEAD =
073a69eb1e001e1738c32739f9b57820cba1b05f

Gate5-G Execution Plan
= CANDIDATE / READY FOR INDEPENDENT REVIEW

Gate5-G Execution
= NOT AUTHORIZED
= NOT STARTED

v0.3.5
= NOT CLOSED
```

> **Review Boundary Notice:**
> This checkpoint records a plan candidate prepared for external independent review.
> The authoring agent does not claim independent approval of its own plan.
> Formal execution of Gate5-G remains NOT AUTHORIZED until independent plan review and project-owner approval are granted.

---

## 2. Baseline & Scope Integrity

- **Authoritative Freeze Baseline HEAD:** `073a69eb1e001e1738c32739f9b57820cba1b05f`
- **Prior Closed Gates:** Gate5-A, Gate5-B, Gate5-C, Gate5-D, Gate5-E, and Gate5-F are all PASS / CLOSED.
- **Files Modified in this Checkpoint:**
  - `docs/superpowers/plans/2026-09-10-gate5g-final-validation-execution-plan.md` (Execution Plan)
  - `docs/history/gate5g/gate5g-execution-plan-checkpoint.md` (Execution Plan Checkpoint Record)
- **Production Files Modified:** `0`
- **Test Files Modified:** `0`
- **Frontend Files Modified:** `0`
- **Deployment / Configuration Files Modified:** `0`

---

## 3. Operationalized Plan Safeguards

1. **G0 Known Blocker & Mandatory STOP Condition:**
   - Evaluates all 8 frozen release-bearing surfaces (`pyproject.toml`, `app/main.py`, `frontend/package.json`, `frontend/package-lock.json`, `Login/index.tsx`, `Sidebar.tsx`, `compose.yaml`, `compose.komodo.yaml`) and contract test `tests/test_release_version_consistency.py`.
   - Formally fails at `APPROVED_FREEZE_HEAD` due to known historical versions (`0.3.3` / `0.3.2` / `:latest`).
   - Mandates a hard STOP without progressing to G1.
   - Enforces candidate invalidation, requiring a separately authorized bounded hotfix producing a new candidate SHA, followed by a full restart from G0.
2. **Exact G1 Regression Commands:**
   - Replaced nonexistent globs with authoritative Gate5-A focused files (`tests/test_filter_ast.py`, `tests/test_filter_compiler.py`, `tests/test_filter_policy.py`, `tests/test_filter_preview.py`, `tests/test_filter_preview_readonly.py`, `tests/test_filter_index_freshness.py`) plus Gate5-B through Gate5-F, Task Engine, Planning, full backend `tests/`, and frontend quality gates.
3. **Single Linux amd64 Docker Build & Exact Tar Archive Transport:**
   - Phase G2 builds candidate image once on `linux/amd64`.
   - Saves exact image to tar archive and computes `G2_IMAGE_ARCHIVE_SHA256`.
   - Phase G7 verifies tar archive SHA256 on NAS, loads it into Docker daemon, and verifies `G7_LOADED_IMAGE_ID == G2_IMAGE_ID`. Rebuilding, compose building, or floating pulling on NAS is strictly prohibited.
4. **Isolated Smoke & Migration Testing:**
   - Phase G3 validates API and Worker container smoke with real session cookie authentication, single worker ownership, and crash-loop free restart resilience.
   - Phase G4 validates fresh install and additive migration from Gate5-E closed baseline `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9` using a disposable database constructed without altering the active worktree.
5. **SQLite Integrity & WAL-Safe Inspection:**
   - Phase G5 validates `integrity_check = ok` and `foreign_key_check = 0 rows` after graceful container shutdown and WAL truncate checkpoint.
6. **Synthetic Filesystem Safety & Plan-Derived Assertions:**
   - Phase G6 validates full 5-stage mutation lifecycle (`Preview -> Draft -> Freeze -> Validate -> Execute`).
   - Asserts keep/quarantine paths dynamically derived from the generated frozen plan without hardcoded filename assumptions.
   - Tests genuine dedupe stale preflight rejection using a separate duplicate group.
   - Enforces mandatory quarantine restore via `POST /api/quarantine/{id}/restore` with byte-for-byte content verification.
7. **Strict Real NAS Mount Isolation:**
   - Prohibits mounting production host paths from `compose.komodo.yaml`.
   - Mandates transient compose outside git worktree or direct `docker run` on dedicated disposable directories.
   - Enforces pre-mutation canonical realpath assertion: `resolved production path != resolved test path`.
8. **Unified Final Evidence Audit (G8):**
   - Implements a comprehensive evidence template binding `VERIFIED_RUNTIME_HEAD`, `G2_IMAGE_ID`, `G7_LOADED_IMAGE_ID`, and image archive SHA256 checksums.
