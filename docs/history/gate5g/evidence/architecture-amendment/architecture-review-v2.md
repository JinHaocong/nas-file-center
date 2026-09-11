# Gate5-G Architecture Amendment v2.0.0 — Independent Review Findings & Revision-3 Directives

**Document Reviewed:** `docs/superpowers/specs/2026-09-11-gate5g-zfuse-transactional-mutation-architecture-amendment.md` (v2.0.0, commit `fb0efa96d2982174bb1bc56f6b065342ff7f7ae9`)  
**Date:** 2026-09-11  
**Review Status:** **FAILED INDEPENDENT ARCHITECTURE REVIEW / REVISION-3 REQUIRED**  
**Authorization Status:** IMPLEMENTATION NOT AUTHORIZED  

---

## 1. Executive Summary & Authoritative Verdict

Independent Architecture Review evaluated the **Revision 2** amendment (`fb0efa9`).
While Revision 2 correctly identified edge-case boundaries, it **fundamentally failed** to resolve the core concurrency hazards. It attempted to fix Time-of-Check to Time-of-Use (TOCTOU) races by adding more `stat` / `fstat` checks and `st_nlink` assertions immediately before issuing `unlink()`.

**Authoritative Finding:**
Userspace `check-then-unlink` is fundamentally incapable of providing atomic deletion guarantees on non-cooperative filesystems. Adding `st_nlink >= 2` does not bind the check to the subsequent `unlink()`. 

Therefore, Revision 2 is **REJECTED**.

---

## 2. Authoritative Findings on Revision 2 Defects

### P0-A: Anchor Release Remains TOCTOU
- **Revision 2 Proposal**:
  ```text
  fstat(anchor)
  lstat(destination)
  assert same inode/dev
  assert anchor.st_nlink >= 2
  unlink(anchor)
  ```
- **The Concurrency Hole**:
  - `st_nlink >= 2` is only an instantaneous observation at the time of `fstat`.
  - It does NOT atomically bind the check to `unlink(anchor)`.
  - Concurrency sequence:
    1. Checks pass (`st_nlink == 2`).
    2. External actor unlinks or replaces `destination`.
    3. Kernel inode link count drops to 1.
    4. NAS File Center executes `unlink(anchor)`.
    5. Link count drops to 0. Original user payload is deleted from disk.
- **Directive**:
  - DO NOT solve this with another stat.
  - DO NOT solve this with another nlink check.
  - DO NOT solve this with open FD plus later unlink.
  - Ordinary quarantine completion **MUST NOT** unlink the authoritative anchor.

---

### P0-B: Source Retirement Remains TOCTOU
- **Revision 2 Proposal**:
  ```text
  fstatat(source)
  verify source inode == anchor inode
  unlink(source)
  ```
- **The Concurrency Hole**:
  - Concurrency sequence:
    1. Source verification passes for inode A.
    2. Third party removes A at the public pathname.
    3. Third party creates new file B at the same pathname.
    4. NAS File Center executes `unlink(source)`.
    5. Third-party file B is deleted!
- **Directive**:
  - The exact pattern `stat/lstat/fstatat(source) -> verify -> unlink(source)` is **STRICTLY FORBIDDEN**.
  - No variation of check-then-unlink is acceptable.
  - Source retirement must use **capture-by-rename** into a private attempt slot.

---

### P0-C: Q1.5 Recovery Repeats Check-Then-Delete
- **Revision 2 Proposal**:
  - For `DB = preparing`, `anchor = present`:
  - Verify `anchor == source` -> `unlink(anchor)`.
- **The Concurrency Hole**:
  - Permits source replacement after verification and before anchor deletion.
  - A crash matrix entry is not 'solved' merely because it is listed.
- **Directive**:
  - Default must be preservation, not cleanup.
  - If uncertainty exists, preserve anchor and enter `conflict`.

---

### P0-D: Stale-Worker Directory Rename Is NOT Fencing
- **Revision 2 Claim**:
  - Worker B renames `.tx/<token>` to `.tx/<token>.fenced_<workerB>`, causing stale Worker A to receive `ENOENT`.
- **The Concurrency Hole**:
  - An open directory file descriptor (`dir_fd`) continues to reference the directory inode regardless of pathname renaming in parent directories.
  - Stale Worker A holding `old_tx_dfd` can still execute `unlink("anchor", dir_fd=old_tx_dfd)` against the renamed directory.
  - `src_parent_fd` is completely unaffected by renaming `.tx`.
- **Directive**:
  - `rename(tx_dir) != filesystem fencing`.
  - Do not claim stale workers can be prevented from issuing syscalls via directory rename.
  - Design primitives such that any stale syscall executed by a resumed worker is **passively data-preserving**.

---

### P0-E: Restore Inherits Identical Defects
- **Revision 2 Proposal**:
  - Verify quarantine source, unlink quarantine source; verify restored destination, unlink anchor.
- **The Concurrency Hole**:
  - Reproduces the exact same TOCTOU race windows against `quarantine_path` and `original_path`.
- **Directive**:
  - Restore must originate from the authoritative private anchor.
  - Quarantine public view retirement must use capture-by-rename, never check-then-unlink.

---

### Additional Architecture Concerns

1. **DB-1 Schema Cramming**:
   - Forcing transaction identity into `QuarantineEntry.last_error` and scanning directory prefixes is fragile and error-prone.
   - Data safety takes precedence over zero-migration dogmatism.
   - Revision 3 must explicitly evaluate DB-1 vs DB-2 and recommend minimal durable transaction/generation fields if safety-critical.

2. **Codebase Reality vs Specification (Flag Mismatch)**:
   - Revision 2 claimed existing code uses `O_PATH | O_DIRECTORY | O_NOFOLLOW`.
   - Codebase inspection reveals `app/batch_utilities/empty_dir_quarantine.py::safe_open_parent_fd` actually uses `os.O_RDONLY | os.O_DIRECTORY` (with `os.O_NOFOLLOW` if available).
   - Specification must clearly separate CURRENT CODE FACT from PROPOSED IMPLEMENTATION REQUIREMENT.

---

## 3. Mandatory Architectural Directives for Revision 3

```text
1. Authoritative Private Payload Anchor
   - Private anchor is the authoritative payload for the FULL QuarantineEntry lifecycle.
   - Public quarantine pathname is merely a presentation / view hard link.
   - Normal quarantine lifecycle NEVER unlinks the authoritative anchor.
   - Steady state is ACTIVE_COMPAT.

2. Capture-Based Source Retirement
   - Ordinary atomic rename of source_path -> .tx/entry-<id>/attempt-<gen>/captured-source.
   - Inspect captured object AFTER rename.
   - If expected inode -> success.
   - If foreign inode -> NEVER delete; move to conflict holding; abort quarantine; payload safe in anchor.

3. Stale-Worker Safety via Invariant Design
   - Stale worker syscalls must be inherently non-destructive:
     - link() to occupied destination -> EEXIST.
     - rename() into its own attempt slot -> preserves captured object.
     - DB commit -> blocked by SQLite lease assertion.
     - anchor deletion -> prohibited from existing in the codebase.

4. Symmetrical Restore via Authoritative Anchor
   - Restore links authoritative anchor to original_path.
   - Public quarantine view retired via capture-by-rename.
```

---

## 4. Verdict

```text
VERDICT: FAILED INDEPENDENT ARCHITECTURE REVIEW
REVISION-3 REQUIRED BEFORE ANY IMPLEMENTATION
```
