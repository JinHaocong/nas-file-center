# V1.6 Media Organizer — Security Review Notes (Not a Release Approval)

**Scope:** Draft PR #397, semantic organizer execution and private-media boundary handling.
**Status:** Internal implementation review and synthetic CI evidence. **Independent security review has not occurred.**
**NAS mount tests:** Not performed. Do not merge, deploy or enable execution as a result of this note.

## Findings and actions

| ID | Severity | Finding | Current action | Release gate |
|---|---|---|---|---|
| SEC-01 | High | A public P/V target folder can be replaced after mkdir but before the owner witness is written. | Added failure injection test verifying no marker or staged media is written to a populated foreign replacement; now checks directory identity/binding and emptiness before ownership. | **Open:** independent review of an empty replacement swapped immediately after mkdir, which cannot be excluded by a post-hoc basename/inode read alone. Prefer a trusted pre-witnessed temporary directory with no-replace promotion if mount semantics permit |
| SEC-02 | High | Crash in the final private marker removal → empty-stage rmdir gap leaves an unwitnessed directory. | Existing code refuses automatic adoption; regression test confirms fail-closed behavior. | **Open:** proof of documented manual recovery, or redesign to maintain a durable witness across final directory deletion |
| SEC-03 | High | Network NAS filesystem may not support required hardlink, directory fsync, or directory no-replace rename semantics. | New scratch-only capability probe and synthetic rejection tests. Original source files never probed. | **Open:** owner-approved disposable parent on actual NAS mount; all capability fields true and owned scratch cleanup verified |
| SEC-04 | High | A configured source tree must not be scanned solely because it appears deeper in collections or uses different filename casing. | New private comma-separated exact-directory-basename config; matching uses casefold, never substring filename matches. Included in preview, frozen plan and canonical rescan. | **Open:** private deployment setting confirmed by owner. Do not commit sensitive source names |
| SEC-05 | Medium | Cross-unit movement or wrong placement can reprocess already indexed media. | Test single-unit confirmation, 001 numbering, 200/201 partition, old wrapper identities and second-pass zero-change. | Run full regression on final head; validate a disposable copy of realistic nested work boundaries |
| SEC-06 | High | Malicious or stale preview/recovery request could bypass mutation authority. | Separate feature gate default false, global mutation/deletion gates, admin routes, exact unit confirmation, Worker lease, immutable manifest, stage owner witnesses, idempotent resume. | Independent race and authorization review, including filesystem swaps after every check |
| SEC-07 | Medium | A full CI run cannot prove external NAS durability. | Focused backend/frontend TDD plus legacy regressions run in GitHub, no production data. | Final GitHub checks all green, operator-approved disposable same-mount validation, manual signoff |

## Synthetic validation evidence

- Controlled TDD tests verified red before missing exclusion and capability-probe modules were implemented, then green after implementation.
- Destination-swap test intentionally replaced a just-created public bucket before the owner witness. **Before fix**, the test observed an owner marker written to the foreign directory; **after fix**, focused backend/frontend CI passed.
- Rejected untrusted stage, foreign target occupancy, changed file identities, interrupted hardlink publication, nested classification cleanup, 200/201 boundary and zero-change repeat scan remain in the focused suite.
- All synthetic tests use temporary directories; media filenames are generic and do not include user private inventories.

## Explicit launch restriction

**PR #397 remains Draft.** MEDIA_ORGANIZER_EXECUTION_ENABLED must remain false in every deployment. No production NAS write, automatic batch execution, merge to main or release until all open High risk items are independently reviewed and approved. The capability probe command and exact approval requirements are documented in docs/media-organizer-v16-execution-gate.md.
