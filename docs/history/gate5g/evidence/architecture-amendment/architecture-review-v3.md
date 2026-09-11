# Gate5-G Architecture Amendment v3.0.0 — Independent Architecture Review Findings & Closure Directives

**Document Reviewed:** `docs/superpowers/specs/2026-09-11-gate5g-zfuse-transactional-mutation-architecture-amendment.md` (v3.0.0, commit `22837e27a5f193b8d986f3a7626e12864689068a`)  
**Date:** 2026-09-11  
**Review Status:** **REVISION 3 CORE PARADIGM ACCEPTED / CLOSURE DIRECTIVES FOR v3.1.0 ISSUED**  
**Authorization Status:** IMPLEMENTATION NOT AUTHORIZED — SPECIFICATION CLOSURE ONLY  

---

## 1. Executive Summary & Verdict

The Independent Architecture Review has evaluated the **Revision 3** architecture (`22837e2`).

### What Was Accepted
The fundamental paradigm shift is **ACCEPTED and FROZEN**:
- Authoritative persistent private payload anchor.
- Presentation-only public quarantine view.
- Capture-by-rename source retirement.
- Option DB-2 (minimal explicit durable transaction fields) architectural direction.
- Single reconciliation hierarchy.

### What Must Be Closed (v3.1.0 Directives)
To achieve final architectural closure before any implementation planning, the following specific findings (P0-1 through P1-2, state model disambiguation, and matrix extensions) must be formally closed in **v3.1.0**.

---

## 2. Comprehensive Inventory of Closure Directives

### P0-1: Candidate Anchor Qualification
- `os.link(source, anchor)` does NOT immediately make the anchor authoritative.
- **Protocol Requirements**:
  1. Create candidate anchor in private attempt namespace.
  2. AFTER link succeeds, validate candidate anchor against Gate3 Frozen expected identity (hash, size, physical inode/dev, mode).
  3. Validation must strictly preserve Gate3 authority.
  4. No public publication and no source capture may occur until candidate anchor qualification succeeds.
  5. On mismatch (e.g. source replaced between final pre-mutation Gate3 check and `os.link`):
     - Preserve candidate anchor.
     - Preserve source and public filesystem facts.
     - Set state = `conflict`.
     - DO NOT unlink candidate anchor.
     - DO NOT report success.

### P0-2: Generation Allocation + Write-Once Capture Slot
- Ordinary `rename()` can overwrite its destination if it already exists. Safety must come from namespace ownership by construction.
- **Protocol Requirements**:
  - Generation allocation occurs under SQLite `BEGIN IMMEDIATE`.
  - `active_generation` monotonically increments and is committed before filesystem attempt directory (`attempt-<gen>/`) creation.
  - Generations NEVER decrement or reuse.
  - Attempt directory is created exclusively.
  - Each generation owns exactly ONE write-once capture slot (`attempt-<gen>/captured-source`).
  - A generation may issue at most ONE rename into `captured-source`.
  - If `captured-source` already exists, NO rename to that path is allowed.
  - Retry/recovery classifies the existing slot.
  - A new execution attempt gets a NEW generation.
  - No check-then-rename retry.

### P0-3: Zero Payload-Bearing Unlink in COMPAT
- For Gate5-G `COMPAT_TRANSACTIONAL`, FORBID unlink of:
  - authoritative anchor
  - expected captured-source
  - foreign captured object
  - unknown inode
  - restore captured view
  - any other payload-bearing private pathname.
- Retain expected `captured-source` as another hard link (consumes zero duplicate payload bytes).
- **Allowed Cleanup ONLY**:
  - non-payload metadata (`attempt-meta.json`)
  - verified-empty directories (`rmdir`).
- Delete Category C duplicate-hard-link cleanup from v3.
- Permanent payload cleanup remains out of scope.

### P0-4: Formally Justify "One Stale FS Syscall" (Lease-Fencing Discipline)
- Do not merely assume a stale worker executes one more syscall without formal structural justification.
- **Mandatory Execution Discipline**:
  ```text
  renew / assert active worker lease
    ↓
  exactly ONE payload-affecting filesystem mutation
    ↓
  before the next payload-affecting mutation:
  renew / assert active worker lease again
  ```
- Thus, lease expiry after a successful fence can permit at most the already-authorized single filesystem syscall.
- Every payload-affecting FS mutation must have its own lease fence.
- Non-mutating stat/read/classification may occur between fences.
- Production code will require restructuring during future implementation to enforce this.

### P0-5: Foreign / Unknown = Preserve in Place
- Do NOT rename foreign or unknown payload merely to organize conflict storage.
- **Protocol Requirements**:
  - `FOREIGN / UNKNOWN = PRESERVE EXACTLY IN ITS UNIQUE ATTEMPT SLOT + DB conflict record + audit metadata`.
  - Remove ordinary `captured-source -> captured-foreign-<timestamp>`.
  - Remove any `if source_path vacant: ordinary rename(foreign, source_path)` (unsafe check-then-rename on zfuse).
  - Regular foreign files: future/manual recovery MAY use hard-link publication with `EEXIST` semantics.
  - Symlink / directory / unknown: preserve in place + conflict; no automatic restoration.

### P1-1: DB-2 Legacy Row Compatibility
- Current `QuarantineEntry` schema has no Revision-3 transaction fields.
- **Migration Semantics**:
  - New DB-2 fields are safely nullable/defaulted as appropriate (`tx_token`, `tx_phase`, `authoritative_anchor_path`, `active_attempt_generation`).
  - Existing rows are LEGACY entries (`tx_phase = NULL` or `'legacy'`).
  - Migration MUST NOT fabricate authoritative anchors for old rows.
  - Existing data remains untouched.
  - Native-supported legacy operations may use existing native semantics.
  - A legacy row on COMPAT zfuse requiring transactional safety but lacking an anchor MUST fail closed (`legacy_anchor_missing`).

### P1-2: COMPAT Purge / Retention Safety Gate
- Permanent-delete architecture is outside this amendment.
- **Retention / Purge Semantics**:
  - `ACTIVE_COMPAT` authoritative anchor MUST NOT be deleted by current purge.
  - COMPAT entries are not automatically purgeable under this amendment.
  - Any purge request or retention action requiring authoritative payload destruction MUST fail closed until separately authorized.
  - MUST NOT mark a COMPAT entry "purged" while its authoritative payload still exists.

### State Model Disambiguation
- Choose exact terminology. Eliminate ambiguous phrases like `conflict / active_degraded`.
- Freeze one deterministic externally persisted interpretation for:
  - `active`: Valid authoritative anchor + retired source + verified public view.
  - `conflict`: Discrepancy detected (foreign capture, public view corruption, mismatch, or stale conflict); payload preserved.
  - `restored`: Original path published; quarantine view retired; anchor preserved.
  - `legacy`: Pre-amendment rows lacking transaction fields.
  - Transaction phases: `preparing`, `candidate_anchored`, `authoritative_anchored`, `public_published`, `source_captured`, `active`, `restoring`, `restored`, `conflict`.
- Specify that ONLY the Gate3-qualified anchor path stored in `authoritative_anchor_path` is authoritative; later generations NEVER replace it; restore generations reference this same anchor.

### Crash & Race Matrix Extensions
- Add explicit boundaries and races for:
  - Source replacement before candidate anchor link.
  - Candidate anchor mismatch after link.
  - Crash after generation commit before attempt mkdir.
  - `captured-source` already exists on retry.
  - Stale generation tries second capture.
  - Legacy row without anchor on COMPAT.
  - Retention/purge attempt on `ACTIVE_COMPAT`.

---

## 3. Review Status

```text
REVISION 3 CORE PARADIGM ACCEPTED
v3.1.0 CLOSURE DIRECTIVES ISSUED
```
