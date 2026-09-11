# Gate5-G / G7 Transactional Mutation Implementation Plan v1.0.0 — Independent Review Findings

**Document Reviewed:** `docs/superpowers/plans/2026-09-11-gate5g-zfuse-transactional-mutation-implementation-plan.md` (v1.0.0, commit `98dfb6abad465363e976c61bbb038225f1aa60d4`)  
**Date:** 2026-09-11  
**Target Release:** v0.3.5  
**Review Status:** **FAILED INDEPENDENT IMPLEMENTATION-PLAN REVIEW / v1.1 CLOSURE REQUIRED**  
**Architecture Status:** PASS / APPROVED / FROZEN / CLOSED (v3.1.0)  
**Implementation Status:** NOT AUTHORIZED — SPECIFICATION PLAN REVISION ONLY  

---

## 1. Executive Summary & Review Verdict

The Independent Review evaluated the **v1.0.0 Implementation Plan** (`98dfb6a`).
While the architectural direction correctly references the frozen v3.1 specification, the plan itself **failed review** because it lacked the required executable Superpowers task structure, contained inaccuracies regarding Gate3 authority, exhibited ambiguities in candidate promotion, and left critical caller and API reconciliation gaps unmapped.

**Authoritative Directive:**
Rewrite the implementation plan to **v1.1.0** closing all 16 specific review findings. Production implementation remains **STRICTLY NOT AUTHORIZED**.

---

## 2. Inventory of Required Plan Closures (v1.1.0 Directives)

1. **Superpowers Executable Plan Format**:
   - Rewrite into bite-sized, executable tasks containing: Files (Create/Modify/Test), Interfaces (Consumes/Produces), exact test cases, exact pytest commands, expected RED failure descriptions, minimal implementation scope, refactoring, focused regression commands, exact commit boundaries, and commit messages.
2. **Candidate Anchor Qualification Authority**:
   - Correct the inaccurate claim that `safe_quarantine_hash` alone is the complete Gate3 authority.
   - Plan descriptor-bound candidate qualification (`O_RDONLY | O_NOFOLLOW`), verifying `S_ISREG`, Gate3 expected device, inode, size, streaming SHA256, and post-hash freshness checks (`mtime_ns`, `ctime_ns`) to detect mutation during hashing without re-open races.
3. **Candidate -> Authoritative Path Unambiguity**:
   - Eliminate separate `candidate_anchor` vs `anchor` ambiguity.
   - The qualified candidate anchor path directly becomes `authoritative_anchor_path`. Zero rename, zero unlink.
4. **Write-Once Capture Invariant Source**:
   - Clarify that safety stems from monotonic generation allocation committed before directory creation, exclusive directory creation, and strict generation ownership (max 1 rename per generation), NOT from `stat` checks. Existing slots trigger classification only.
5. **fs_ops Compatibility Fallback Caller Matrix**:
   - Audit all callers of `rename_noreplace` and `rename_noreplace_at`.
   - Formally dismantle the unsafe `link + verify + unlink` fallback. Un-transacted calls on unsupported filesystems fail closed with `EOPNOTSUPP`.
6. **API Startup Reconciler Deferral**:
   - Resolve conflict between `FileCenterService.reconcile_startup_entries()` and Worker lease reconciliation.
   - Transactional entries (`tx_phase IS NOT NULL`) are deferred to Worker recovery, eliminating race conditions.
7. **State vs tx_phase Persisted Matrix**:
   - Establish an exhaustive mapping of `QuarantineEntry.state`, `tx_phase`, `authoritative_anchor_path`, and `active_attempt_generation` for all 14 phases.
   - Historical `active` and `restored` rows retain their existing states.
8. **Per-Mutation Lease API**:
   - Implement `renew_and_assert_worker_lease()`.
   - List every payload-affecting mutation (candidate link, public link, source capture rename, restore link, restore view capture rename) and enforce a lease fence before each.
9. **Full Symmetrical Restore Tasks**:
   - Plan dedicated Restore tasks covering anchor lookup, `linkat` with `EEXIST`, write-once view capture rename, foreign view preservation, and crash recovery.
10. **Single Reconciliation Hierarchy & Phase Actions**:
    - Specify exact DB/filesystem facts, allowed/forbidden actions, lease requirements, and BatchPlanItem outcomes for every `tx_phase`.
11. **Comprehensive Test Matrix**:
    - Explicitly map all C0–C11 crash boundaries and R1–R16 race conditions to test functions.
12. **Migration Plan Precision**:
    - Update `init_db()` backup triggers, specify exact ALTER statements, idempotency tests, and legacy row fail-closed behavior.
13. **Purge & Retention Audit**:
    - Guard manual purge, retention tasks, and startup purging reconciler to fail closed on `ACTIVE_COMPAT`.
14. **Real NAS Acceptance on zfuse**:
    - Target `/mnt/zfpool/test_gate5g_compat/` with explicit `fuse.zfuse.zfsv3` filesystem verification, production data/config guards, and sentinel checks under sudo.
15. **Frontend Validation**:
    - Typecheck, test, and build commands specified without implementation changes.
16. **Self-Review & Plan Revision**:
    - Deliver v1.1.0 plan and update review status.
