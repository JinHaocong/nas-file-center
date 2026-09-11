# Gate5-G / G7 Independent Implementation-Plan Review (v1.1.0)
# Final Implementation Plan Review Findings Archive

**Date:** 2026-09-11  
**Target Release:** NAS File Center v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Baseline Plan HEAD:** `23d2d93d88ed67687b24b8a433fc225d46204183`  
**Frozen Architecture HEAD:** `0ddf932747021578f08843c5069ef88a461d493f`  
**Production Code Baseline HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Review Verdict:** **FAILED / REVISION-1.1.1 REQUIRED**  

---

## 1. Executive Summary

The Independent Reviewer evaluated **Implementation Plan v1.1.0** against the frozen Revision 3.1 Architecture Amendment (`0ddf932`). While the 12-task structure and core commitments are sound, 10 specific deficiencies were identified that must be closed in **Implementation Plan v1.1.1** before implementation authorization can be granted.

---

## 2. Authoritative Review Findings

### Finding 1: Non-Conforming `tx_phase` Identifiers & Historical State Rewrite
- **Issue**: Plan v1.1.0 introduced informal/intermediate phase names (`candidate_created`, `source_captured_expected`, `restore_published`, `restore_view_captured`) and improperly proposed rewriting historical `state` to `'legacy'`.
- **Mandatory Closure**:
  - Strictly use the 10 frozen `tx_phase` values: `preparing`, `candidate_anchored`, `authoritative_anchored`, `public_published`, `source_captured`, `active`, `restoring`, `restored`, `conflict`, `legacy`.
  - Intermediate FS-success / DB-lag states must be represented as: existing frozen `tx_phase` + observed filesystem facts.
  - Legacy migration rule: existing rows keep their historical state (`active`, `restored`, etc.); `tx_phase` remains `NULL` (or logical legacy classification). Never overwrite historical `state`.

### Finding 2: Missing DB-Lag Filesystem Fact Reconciliation Variants
- **Issue**: The reconciliation table in v1.1.0 lacked explicit mappings for critical crash/lag boundaries where the filesystem succeeded but DB has not updated.
- **Mandatory Closure**:
  - Expand the phase-action table with all 13 mandatory variants:
    1. `preparing` + no anchor
    2. `preparing` + candidate anchor exists
    3. `preparing` + generation committed but attempt dir missing
    4. `authoritative_anchored` + public absent
    5. `authoritative_anchored` + public present and matches anchor
    6. `authoritative_anchored` + public present but foreign
    7. `public_published` + captured-source absent
    8. `public_published` + captured-source present expected
    9. `public_published` + captured-source present foreign
    10. `restoring` + original absent
    11. `restoring` + original present expected
    12. `restoring` + original present foreign/EEXIST
    13. `restoring` + captured-quarantine-view present expected/foreign
  - Specify DB facts, FS facts, read/classify action, new generation requirement, next frozen phase/state, FS mutation allowance, lease fence requirement, and BatchPlanItem outcome for each.
  - Enforce rule: *CLASSIFY EXISTING EVIDENCE BEFORE ISSUING ANOTHER MUTATION*.

### Finding 3: Under-Specified Worker Lease Fence
- **Issue**: Proposing `session.flush()` is insufficient and leaves ambiguity regarding SQLite write lock retention during slow FUSE calls.
- **Mandatory Closure**:
  - Freeze exact short-lived committed fence protocol:
    ```python
    with SessionLocal() as session:
        # BEGIN IMMEDIATE
        renew + assert current worker
        # COMMIT
    # No SQLite write lock held here
    execute EXACTLY ONE payload-affecting filesystem syscall
    ```
  - Before next payload syscall: repeat the committed lease fence.
  - Add explicit tests for cross-session visibility, zero open write transactions during slow syscalls, and rejection of stale workers post-takeover.

### Finding 4: Incomplete Capability Routing API
- **Issue**: The plan did not provide a standalone capability resolver, risking overhead on native atomic filesystems or leaking unsupported objects.
- **Mandatory Closure**:
  - Define `resolve_mutation_capability(...)` reusing existing probe machinery.
  - Route: NATIVE supported -> native atomic `rename_noreplace`; COMPAT regular file -> transaction engine; COMPAT symlink/dir/special -> `EOPNOTSUPP`; UNKNOWN / probe failure -> FAIL CLOSED.

### Finding 5: Obsolete Hotfix Test Invalidation & Zero-Fallback Verification
- **Issue**: Decommissioning the old `fs_ops` link+unlink fallback breaks existing tests expecting fallback success (e.g. `tests/test_gate5g_g7_hotfix1_fs_ops.py`).
- **Mandatory Closure**:
  - Plan exact test modifications in Task 6 so that `rename_noreplace` asserts `EOPNOTSUPP` and zero link+unlink fallback when native atomic rename is unsupported.
  - Task 6 regression must include all Gate5-G `fs_ops` tests so the commit is completely GREEN.

### Finding 6: Missing R1–R16 Race Condition Test Mapping
- **Issue**: The claim that all 16 race scenarios were tested was unsubstantiated without explicit test names and code.
- **Mandatory Closure**:
  - Create dedicated race test file `tests/test_gate5g_g7_races.py` mapping R1 through R16 with exact test function names and code skeletons.

### Finding 7: NAS Validation Path Isolation & Safety Guards
- **Issue**: The plan referenced `/mnt/zfpool/test_gate5g_compat_*`, risking mutation of immutable G7 failure evidence.
- **Mandatory Closure**:
  - Future candidate validation must use a NEW sibling disposable root: `/mnt/zfpool/test_gate5g_candidate_<sha>/`.
  - Never touch old evidence root `/mnt/zfpool/test_gate5g_compat_*`.
  - Add strict fail-closed guards against production paths (`/volume1/*`, `/volume2/*`, `/data`, `/config`, `/etc`).
  - Require `sudo`, `stat -f` zfuse check, `st_dev` equality, and sentinel verification.

### Finding 8: Codebase Function Location Accuracy
- **Issue**: `execute_item` was inaccurately referenced as `app/tasks/handlers.py::execute_item()`.
- **Mandatory Closure**:
  - Correct to `app/execution/executor.py::execute_item` (imported by `app/tasks/handlers.py`).
  - Audit all other function and line references against `c32d0778c59add81e0c296d6f73aa66bc403c04f`.

### Finding 9: Superpowers Executability & Agentic Header
- **Issue**: Missing standard agentic-worker header, missing test code skeletons for safety-critical RED steps, and unclear evidence paths in Task 12.
- **Mandatory Closure**:
  - Add required agentic-worker header block.
  - Provide concrete code skeletons for all RED steps.
  - Specify exact walkthrough/evidence path and commit files in Task 12.
  - Ensure every Task passes its focused regression suite before committing.

### Finding 10: Remote Archive & Versioning
- **Issue**: Evidence bundle must be updated to v1.1.1.
- **Mandatory Closure**:
  - Archive `implementation-plan-review-v1.1.md`.
  - Update plan to v1.1.1 and archive immutable `implementation-plan-v1.1.1.md`.
  - Update `review-status.md` and `README.md`.
  - Maintain DOCS/EVIDENCE ONLY; do NOT modify production or test code.
