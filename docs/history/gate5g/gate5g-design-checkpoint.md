# Gate5-G Final Validation Design Checkpoint (Revision 1)

**Date:** 2026-09-10
**Target Branch:** `v0.3.5-gate5c-hotfix4`
**BASE_HEAD:** `cd49f6cbb244cd4e4ff4bbbd0e4608fdf752db12`

---

## 1. External Independent Review Provenance

```text
Reviewed candidate:
cd49f6cbb244cd4e4ff4bbbd0e4608fdf752db12

External independent review verdict:
CHANGES REQUIRED

Findings:
6

Architecture direction:
accepted

Gate5-G Architecture / Validation Freeze:
NOT APPROVED

Gate5-G Execution:
NOT AUTHORIZED
```

> **Review Boundary & Non-Approval Notice:**
> These findings were supplied by an external independent reviewer.
> The authoring agent is revising the design in response and does not claim independent approval of its own revised design.
> Formal Architecture / Validation Freeze requires external project-owner approval prior to any execution.

### Commit-Range Provenance Note
```text
e04399c8ee8a5b2a81b9090dabb402c49e21e2fb
→
cd49f6cbb244cd4e4ff4bbbd0e4608fdf752db12
contains two docs-only commits.
```

---

## 2. Gate Status Declarations

```text
Gate5-G Final Validation Design
= READY FOR INDEPENDENT RE-REVIEW

Gate5-G Architecture / Validation Freeze
= NOT APPROVED YET

Gate5-G Execution
= NOT STARTED

v0.3.5
= NOT CLOSED
```

---

## 3. Scope & File Audit

- **Authoritative Baseline HEAD:** `cd49f6cbb244cd4e4ff4bbbd0e4608fdf752db12`
- **Prior Closed Gates:** Gate5-A, Gate5-B, Gate5-C, Gate5-D, Gate5-E, and Gate5-F are all PASS / CLOSED.
- **Files Modified in this Revision:**
  - `docs/superpowers/specs/2026-09-10-gate5g-final-validation-design.md` (Design Specification)
  - `docs/history/gate5g/gate5g-design-checkpoint.md` (Design Checkpoint Record)
- **Production Files Modified:** `0`
- **Test Files Modified:** `0`
- **Frontend Files Modified:** `0`
- **Deployment / Configuration Files Modified:** `0`

---

## 4. Independent Review Findings Addressed (6 / 6)

### Finding 1 — Complete G0 Release-Version Inventory & Contract Test
- Expanded G0 release-bearing surfaces from 6 to 8:
  1. `pyproject.toml` (`[project].version`)
  2. `app/main.py` (`FastAPI(..., version=...)`)
  3. `frontend/package.json` (`version`)
  4. `frontend/package-lock.json` (`version` and `packages[""]["version"]`)
  5. `frontend/src/pages/Login/index.tsx` (visible `NAS File Center v0.3.5` UI string)
  6. `frontend/src/components/Sidebar.tsx` (visible `v0.3.5` UI string)
  7. `compose.yaml` (default application image tag `nas-file-center:0.3.5`)
  8. `compose.komodo.yaml` (production application image reference `kerwinjhc/nas-file-center:0.3.5`)
- Froze `tests/test_release_version_consistency.py` as the release-version contract test.
- Documented that a future bounded G0 release-metadata hotfix will update this test to expect `0.3.5` in lockstep with the release surfaces, triggering candidate invalidation and restart from G0.
- Recorded current known discrepancies as `KNOWN G0 BLOCKING FINDING` without altering them in this checkpoint.

### Finding 2 — Exact Gate5-A Focused Regression Command & Hierarchy Cleanup
- Replaced the nonexistent glob `tests/test_gate5a_*.py` with the authoritative Gate5-A focused test suite:
  ```bash
  pytest \
    tests/test_filter_ast.py \
    tests/test_filter_compiler.py \
    tests/test_filter_policy.py \
    tests/test_filter_preview.py \
    tests/test_filter_preview_readonly.py \
    tests/test_filter_index_freshness.py \
    tests/test_gate5b_*.py \
    tests/test_gate5c_*.py \
    tests/test_gate5d_*.py \
    tests/test_gate5e_*.py \
    tests/test_gate5f_*.py -v
  ```
- Removed unverified descriptive labels attached to Gate5-A through Gate5-F in Section 1.1 to avoid accidentally rewriting closed-gate definitions.

### Finding 3 — Real Dedupe Candidate for Stale Safety Black-Box
- Restructured the Phase G6 safety fixture to include a dedicated duplicate pair (`stale_group_fileA.dat`, `stale_group_fileB.dat`).
- Froze an authentic deduplication stale lifecycle: Scan -> Preview -> Draft -> Freeze -> inspect planned mutation source -> externally modify that source on disk -> Validate -> Execute refusal.
- Eliminated artificial plans targeting unique files and prohibited synthetic DB row injection.

### Finding 4 — Plan-Derived Keep and Remove Assertions
- Eliminated hardcoded assumptions regarding which file (`fileA` vs. `fileB`) is preserved or removed.
- Required assertions to be dynamically derived from the generated frozen plan:
  - Assert the plan's `actual keep_path` remains intact.
  - Assert the plan's `actual planned mutation source` moves to quarantine.
  - Assert at least one protected member remains and no unauthorized file is modified.
- Required explicit recording of `keep_path`, planned source path, and planned quarantine target in verification evidence.

### Finding 5 — Exact G2 -> G7 Image-Byte Identity Transfer
- Enforced single-build immutability: Phase G2 builds the `linux/amd64` Docker image once.
- Strictly prohibited the NAS from rebuilding the image, running `docker compose build`, pulling floating tags, or substituting images.
- Froze exact transport protocol:
  - G2: `docker save` to tar archive -> compute `G2_IMAGE_ARCHIVE_SHA256` -> transfer to NAS.
  - G7: verify archive SHA256 matches -> `docker load` -> verify `G7_LOADED_IMAGE_ID == G2_IMAGE_ID` -> verify architecture is `linux/amd64`.
- Mandated explicit recording of `G2_IMAGE_ID`, `G2_IMAGE_TAG`, `G2_IMAGE_ARCHIVE_SHA256`, `G7_LOADED_IMAGE_ID`, `G7_IMAGE_ARCHIVE_SHA256`, and `identity_match = YES` in Phase G8 evidence.

### Finding 6 — Explicit Isolation of Real NAS Host Mounts
- Strictly prohibited G6/G7 verification from using the production host mount paths committed in `compose.komodo.yaml`.
- Prohibited in-place editing of `compose.komodo.yaml`.
- Mandated that NAS validation execute via a verifier-owned transient Compose file outside the worktree, a transient Compose override outside the worktree, or direct `docker run` commands.
- All mechanisms must mount strictly dedicated disposable `CONFIG` and `DATA` directories with zero access to production media or production `app.db`.
- Added a mandatory pre-mutation assertion:
  ```text
  real production DATA mount path != Gate5-G disposable test DATA path
  real production CONFIG mount path != Gate5-G disposable CONFIG path
  ```
- Failure to verify absolute path isolation immediately triggers: `STOP / G7 = FAIL / NOT EXECUTED`.
