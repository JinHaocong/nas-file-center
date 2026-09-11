# Gate5-G Architecture Amendment Review Status

**Stage:** Architecture Amendment v3.0.0 (Revision 3)  
**Date:** 2026-09-11  
**Status:** **G7 ARCHITECTURE AMENDMENT REVISION 3 COMPLETE / READY FOR INDEPENDENT ARCHITECTURE REVIEW**  

## State Summary
- Revision 2 evaluated by Independent Architecture Review and failed due to P0-A through P0-E (check-then-unlink is fundamentally non-atomic on uncooperative filesystems).
- Revision 3 establishes the **Authoritative Private Payload Anchor** model:
  - Private anchor persists for the FULL `QuarantineEntry` lifecycle; steady state is `ACTIVE_COMPAT`.
  - Public quarantine path is strictly a presentation-only view; normal lifecycle NEVER unlinks the authoritative anchor.
  - Source retirement executes via **capture-by-rename** into unique per-attempt private slots; foreign replacements are preserved in conflict holding and NEVER deleted.
  - Stale workers are handled via **passive invariant protection** (resumed syscalls are intrinsically non-destructive).
  - Symmetrical restore redesigned around authoritative anchor and capture-by-rename view retirement.
  - Formally recommends minimal durable database fields (Option DB-2).
- Implementation remains strictly **NOT AUTHORIZED** pending Independent Architecture Review approval.
