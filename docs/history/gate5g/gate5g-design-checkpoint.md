# Gate5-G Final Validation Design Checkpoint

**Date:** 2026-09-10
**Target Branch:** `v0.3.5-gate5c-hotfix4`
**BASE_HEAD:** `e04399c8ee8a5b2a81b9090dabb402c49e21e2fb`

---

## 1. Gate Status Declarations

```text
Gate5-G Final Validation Design
= CANDIDATE

Gate5-G Architecture / Validation Freeze
= NOT APPROVED YET

Gate5-G Execution
= NOT STARTED

v0.3.5
= NOT CLOSED
```

> **Review Boundary Notice:**
> This document is a design checkpoint prepared for external independent review.
> The authoring agent does not claim independent approval of its own design.
> Formal Architecture / Validation Freeze requires external project-owner approval prior to any execution.

---

## 2. Baseline & Scope Integrity

- **Authoritative Baseline HEAD:** `e04399c8ee8a5b2a81b9090dabb402c49e21e2fb`
- **Prior Closed Gates:** Gate5-A, Gate5-B, Gate5-C, Gate5-D, Gate5-E, and Gate5-F are all PASS / CLOSED.
- **Files Modified in this Checkpoint:**
  - `docs/superpowers/specs/2026-09-10-gate5g-final-validation-design.md` (Design Specification)
  - `docs/history/gate5g/gate5g-design-checkpoint.md` (Design Checkpoint Record)
- **Production Files Modified:** `0`
- **Test Files Modified:** `0`
- **Frontend Files Modified:** `0`
- **Deployment / Configuration Files Modified:** `0`

---

## 3. Known G0 Release Metadata Blocker Recorded

The design specification explicitly records the following known version metadata discrepancies present at `BASE_HEAD`:
- `pyproject.toml`: `version = "0.3.3"`
- `app/main.py`: `FastAPI(..., version="0.3.3")`
- `frontend/package.json`: `"version": "0.3.3"`
- `frontend/package-lock.json`: `"version": "0.3.3"`
- `compose.yaml`: `image: nas-file-center:0.3.2`
- `compose.komodo.yaml`: `image: kerwinjhc/nas-file-center:latest`

**Formal Handling:**
These mismatches are designated as `KNOWN G0 BLOCKING FINDING`. They are deliberately preserved without modification in this design checkpoint. During initial Gate5-G execution, Phase G0 will formally record this failure, triggering an authorized, bounded release-metadata hotfix to establish the canonical `0.3.5` release candidate commit.

---

## 4. Key Architectural & Verification Commitments

1. **Immutable Candidate Model:**
   - Evaluated strictly against: `One Immutable Candidate SHA + One Immutable Built Image Identity + Fixed Verification Matrix`.
   - Rejection of floating references, `:latest` tags, or multi-commit aggregation.
2. **Immutable-Candidate Restart Rule:**
   - Any failure requiring changes to code, tests, frontend, Dockerfile, compose files, or package metadata marks the candidate as `FAIL`.
   - A new candidate SHA must be produced via bounded hotfix, and executable verification must restart from Phase G0.
   - Evidence distinction: `VERIFIED_RUNTIME_HEAD` (runtime candidate) vs. `ARCHIVAL_RECORD_HEAD` (documentation-only archival commit under `docs/history/gate5g/**`).
3. **Phase Matrix (G0 – G8):**
   - **G0:** Release metadata consistency (`0.3.5`).
   - **G1:** Source regression (`pytest tests/` 0 failed 0 errors; frontend `typecheck`, `test`, `build` 0 exit code).
   - **G2:** Clean `linux/amd64` Docker build & container inspection (`x86_64`, python, fclones, app imports, frontend dist).
   - **G3:** API + Worker container smoke, single worker ownership, crash-loop free operation, restart resilience, zero scheduler.
   - **G4:** Database migration verification for fresh install and additive upgrade from Gate5-E closed baseline (`3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`).
   - **G5:** SQLite `integrity_check` (ok) and `foreign_key_check` (0 rows) post-shutdown.
   - **G6:** Synthetic filesystem safety lifecycle (preview -> draft -> freeze -> validate -> execute, quarantine move, stale detection, sentinel isolation).
   - **G7:** Real 极空间 NAS black-box validation on a dedicated disposable test directory.
   - **G8:** Final candidate audit requiring 100% passing across G0–G7 on identical candidate.
4. **Target Release Boundary:**
   - Release tagging (`v0.3.5`) and public image publishing are strictly deferred until after Gate5-G and v0.3.5 are formally CLOSED by the project owner.
