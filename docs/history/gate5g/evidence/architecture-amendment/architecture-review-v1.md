# Gate5-G Architecture Amendment v1.0.0 — Independent Review Findings

**Document Reviewed:** `docs/superpowers/specs/2026-09-11-gate5g-zfuse-transactional-mutation-architecture-amendment.md` (v1.0.0)  
**Date:** 2026-09-11  
**Review Status:** **FAILED INDEPENDENT ARCHITECTURE REVIEW / REVISION-2 REQUIRED**  
**Authorization Status:** IMPLEMENTATION NOT AUTHORIZED  

---

## 1. Review Summary
Independent Architecture Review assessed the proposed Persistent Two-Phase Mutation Transaction Architecture. 

While the architectural direction (Approach B: Two-Phase Transaction + Private Recovery Anchor + Reconciliation) was approved as the correct foundational model, the review identified several **Revision-2 Blockers** that prevent freezing the amendment or authorizing implementation.

---

## 2. Identified Revision-2 Blockers

1. **Recovery Anchor Edge-Case Invariants**:
   - The lifecycle of `.tx/<tx_id>/anchor` during interrupted transactions requires more explicit cleanup invariants.
   - Ambiguous states where both source and destination are missing while anchor exists must be strictly categorized with a formal audit policy.
2. **Explicit Directory & Symlink Fail-Closed Enforcement**:
   - The capability gate must guarantee that callers attempting directory moves or symlink moves on `COMPAT_TRANSACTIONAL` mode cannot accidentally fall through to unanchored moves.
   - `rmdir_empty` and batch utilities must receive formal capability gate rejection specifications.
3. **Reconciliation Engine Formalism**:
   - The exact dispatch table for the startup reconciler must formally distinguish between unambiguous forward-convergence (resuming source unlink) and ambiguous external interference (preserving anchor and creating incident records).
   - Must guarantee that reconciliation NEVER deletes any foreign file or unknown inode.
4. **Worker Lease Takeover Semantics**:
   - Specification must formally verify that an expiring worker cannot perform a partial mutation while a new worker executes reconciliation, strictly tying each step to `assert_active_worker_lease` inside SQLite `BEGIN IMMEDIATE`.
5. **No DB Migration Mandate**:
   - Ensure Option DB-1 (reuse of existing fields with deterministic path binding) is fully articulated so that no premature schema migration is introduced.

---

## 3. Verdict & Next Steps
- **Verdict**: REVISION-2 REQUIRED.
- **Current State**:
  ```text
  Architecture Amendment = DRAFT / NOT FROZEN / NOT CLOSED
  Implementation = NOT AUTHORIZED
  Gate5-G G7 = BLOCKED
  Gate5-G G8 = NOT EXECUTED
  v0.3.5 = NOT CLOSED
  ```
- **Next Action**: Prepare Architecture Freeze Amendment Revision 2 addressing all blockers before requesting implementation authorization.
