# NAS File Center v0.3.5 — Gate5-E / E4-hotfix2 Independent Review

## 1. Review Metadata

- **Date:** 2026-09-10
- **Reviewed HEAD:** `b0d093898cfc3603aa15fb5ca4b53ba3462724d1`
- **Branch:** `v0.3.5-gate5c-hotfix4`
- **Target Component:** Gate5-E / E4 Remove Empty Directories (Quarantine-First Logical Removal)
- **Status:**
  - **Gate5-E / E4-hotfix2 INDEPENDENT REVIEW = NOT PASS**
  - **E4 = NOT CLOSED**
  - **Gate5-F = FORBIDDEN**

---

## 2. Provenance Record & Correction

The authoring and implementation provenance for E4-hotfix2 is verified and recorded as:
- **E4-hotfix2 Architecture Freeze Amendment Commit:** `9d8bfc2d8cee562ba2edec0b956fb89a502c5a40`
- **E4-hotfix2 Implementation / Reviewed HEAD:** `b0d093898cfc3603aa15fb5ca4b53ba3462724d1`

*(Note: Prior walkthrough text mistakenly referenced a truncated/scrambled hash `b0d09383679f2255651c6cbf094625b15be625ee`, which is not a valid commit. The authoritative reviewed remote HEAD is `b0d093898cfc3603aa15fb5ca4b53ba3462724d1`.)*

---

## 3. Findings

### Finding 1 — BLOCKER: QUARANTINE_ROOT symlink prohibition is bypassed

- **Severity:** BLOCKER
- **Component:** `app/batch_utilities/empty_dir_quarantine.py`
- **Root cause:**
  `empty_dir_quarantine.py` currently resolves `quarantine_root` before checking `q_root.is_symlink()`:
  ```python
  q_root = Path(quarantine_root).resolve()
  if not q_root.exists() or not q_root.is_dir() or q_root.is_symlink():
      ...
  ```
  Therefore, a configured quarantine-root leaf that is a symlink gets dereferenced first by `.resolve()`. The subsequent `.is_symlink()` inspection examines the resolved target rather than the configured lexical leaf symlink.
- **Architecture Requirement:**
  - The quarantine root must exist, be a real directory, and its configured leaf MUST NOT be a symlink.
  - The quarantine root must be acquired using no-follow descriptor acquisition (`os.O_DIRECTORY | os.O_NOFOLLOW`) and physical identity binding via `fstat()`.
  - All operations inside quarantine must be descriptor-anchored.

---

### Finding 2 — BLOCKER: rmdir_empty crash reconciliation State C rollback is not FD-anchored

- **Severity:** BLOCKER
- **Component:** `app/tasks/handlers.py` (`_reconcile_executing_item`)
- **Root cause:**
  Current crash reconciliation for State C performs rollback using pathname `os.open()`:
  ```python
  q_fd = os.open(str(settings.quarantine_root), os.O_RDONLY | os.O_DIRECTORY)
  src_parent_fd = os.open(str(src.parent), os.O_RDONLY | os.O_DIRECTORY)
  ```
  This call lacks `os.O_NOFOLLOW` and does not walk from the authorized `ALLOWED_ROOT` descriptor chain. If an ancestor directory of `src.parent` is replaced with a symlink by a concurrent attacker/actor during the crash window, the rollback `rename_noreplace_at` would follow the symlink and inject the mismatched quarantine object into an unintended directory.
- **Architecture Requirement:**
  - If the original source parent cannot be safely reacquired through the authorized FD-anchored chain (`ALLOWED_ROOT` -> `O_DIRECTORY | O_NOFOLLOW` walk), **DO NOT ROLLBACK**.
  - Preserve the unknown object safely in quarantine.
  - Mark item state as `failed` with conflict details.
  - Under no circumstances may path-based fallback or un-anchored pathname opening occur.

---

## 4. Conclusion & Directives

- **Conclusion:** E4-hotfix2 does NOT meet closure criteria due to Findings 1 and 2.
- **Directives:**
  1. Record this independent review finding document into version control.
  2. Implement bounded hotfix (Gate5-E / E4-hotfix3) under existing E4-hotfix2 Architecture Freeze Amendment.
  3. Follow strict TDD: construct RED regressions reproducing Findings 1 and 2 before editing production code.
  4. Implement minimal production fixes for quarantine root lexical symlink rejection and FD-anchored State C rollback.
  5. Correct provenance SHA references in documentation.
  6. Execute 5-level test verification suite.
