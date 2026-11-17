# V1.6 Media Organizer — Security Review Notes (Not a Release Approval)

**Scope:** Draft PR #397, semantic organizer execution and private-media boundary handling.
**Status:** Internal implementation review and synthetic CI evidence. **Independent security review has not occurred.**
**NAS mount tests:** Not performed. Do not merge, deploy or enable execution as a result of this note.

## Findings and actions

| ID | Severity | Finding | Current action | Release gate |
|---|---|---|---|---|
| SEC-01 | High | Creating a public P/V directory before writing its ownership marker allowed empty-directory replacement races. | Replaced public bare mkdir with PRIVATE, witnessed group creation inside the verified stage and atomic directory NOREPLACE promotion. Media hardlinks recheck the public owner witness and directory binding. New failure-injection tests verify late foreign collisions and post-promotion swaps fail closed. | **Pending independent review:** remaining races involving private-stage replacement and actual mount NOREPLACE semantics; do not treat synthetic CI as security sign-off |
| SEC-02 | High | Crash in the final private marker removal → empty-stage rmdir gap left an unwitnessed directory. | Added fsynced PRIVATE retirement receipt outside the stage, bound to frozen manifest checksum and stage device/inode; exactly empty stage can be reconciled after interruption. Missing, tampered or changed-replacement receipt cases fail closed. API also checks receipt before explicit Worker recovery. | **Pending independent review and real mount durability proof:** correctness and audit retention for the private receipt across power loss |
| SEC-03 | High | Network NAS filesystem may not support required hardlink, directory fsync, or cross-parent directory no-replace rename semantics. | Scratch-only capability probe now reproduces the actual private-stage-child to public-parent promotion, including a collision with an existing empty target; nested scratch cleanup is inode-checked. Synthetic acceptance and rejection tests passed. | **Open:** owner-approved disposable parent on actual NAS mount; every capability field, including directory_cross_parent_noreplace, must be true and owned scratch cleanup verified |
| SEC-04 | High | A configured source tree must not be scanned solely because it appears deeper in collections or uses different filename casing. | New private comma-separated exact-directory-basename config; matching uses casefold, never substring filename matches. Included in preview, frozen plan and canonical rescan. | **Open:** private deployment setting confirmed by owner. Do not commit sensitive source names |
| SEC-05 | Medium | Cross-unit movement or wrong placement can reprocess already indexed media. | Test single-unit confirmation, 001 numbering, 200/201 partition, old wrapper identities and second-pass zero-change. | Run full regression on final head; validate a disposable copy of realistic nested work boundaries |
| SEC-06 | High | Malicious or stale preview/recovery request could bypass mutation authority. | Separate feature gate default false, global mutation/deletion gates, admin routes, exact unit confirmation, Worker lease, immutable manifest, stage owner witnesses, idempotent resume. | Independent race and authorization review, including filesystem swaps after every check |
| SEC-07 | Medium | A full CI run cannot prove external NAS durability. | Focused backend/frontend TDD plus legacy regressions run in GitHub, no production data. | Final GitHub checks all green, operator-approved disposable same-mount validation, manual signoff |

## Synthetic validation evidence

- Controlled TDD tests verified red before missing exclusion and capability-probe modules were implemented, then green after implementation.
- Destination-swap tests first reproduced an owner marker in an injected foreign directory. The publisher now prepares witnessed groups privately, promotes them with directory NOREPLACE, and checks ownership before each media link. Tested synthetic late-target collision, pending group interruption and post-promotion empty-directory replacement.
- Last-stage-marker gap tests originally required manual intervention. New receipt-backed code permits exact-matching empty-stage recovery; synthetic tests cover valid recovery, forged receipt and replaced stage inode. Worker API test confirms a new admin recovery job can be queued only with valid receipt evidence.
- Rejected untrusted stage, foreign target occupancy, changed file identities, interrupted hardlink publication, nested classification cleanup, 200/201 boundary and zero-change repeat scan remain in the focused suite.
- All synthetic tests use temporary directories; media filenames are generic and do not include user private inventories.

## Explicit launch restriction

**PR #397 remains Draft.** MEDIA_ORGANIZER_EXECUTION_ENABLED must remain false in every deployment. No production NAS write, automatic batch execution, merge to main or release until all open High risk items are independently reviewed and approved. The capability probe command and exact approval requirements are documented in docs/media-organizer-v16-execution-gate.md.
