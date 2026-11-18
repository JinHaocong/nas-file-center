# V1.6 user-rule traceability and implementation status

**Authoritative product source:** [NAS File Center｜Luolcy 与非 Luolcy 智能整理规则 V1.6（已确认）](https://chatgpt.com/space/page_9fe339e8ac288191b3868fd4dbd5062a)
**Status:** source rules checked against PR #397 code on 2026-11-18.
**Candidate at time of review:** `7846c263d8a6ddbaeeb739e7d9b093ef0c9a22af`.

This matrix distinguishes **read-only planner conformance** from **end-to-end executable completion**. A rule appearing correctly in a preview does not mean it can safely mutate the NAS.

## Rule-by-rule traceability

| Confirmed rule | Current implementation / evidence | Status |
|---|---|---|
| Both modes identify independent organizing units before moving anything | Luolcy uses the fixed MediaPackage `YYMM/YYMMDD/author/package` iterator. Generic mode uses `media_organizer_units.discover_semantic_units` and the per-unit planner. | Implemented for preview |
| Preserve author, collection, package, date and quality/version boundaries | Generic traversal descends each non-wrapper directory independently; `NO.001` / `A3594-53` work IDs are recognized inside old wrappers; 4K/PT and other non-wrapper directories are not flattened into parents. Ambiguous numeric/new-folder names block. | Implemented for preview; conservative blockers remain |
| Both modes use deterministic numbering from 001 and preserve final extension spelling | Shared `media_package_naming.allocate_names`; `numbered_name` uses `Path(name).suffix`; generic planner sorts by relative path `casefold()` then original path. Existing Luolcy naming tests cover numbering, extension preservation and Other collision suffixes. | Implemented in planning |
| Pure 1–200 P or V is flattened and numbered; no P/V bucket | Luolcy `preview_media_package_package` and generic `preview_semantic_unit` use the 200 threshold and `flatten_pure_media`. | Implemented in preview; generic flat execution remains separately gated |
| Pure 201+ P or V is grouped in batches of at most 200 | Both planners use `MAX_FILES_PER_GROUP = 200`; each batch restarts numbering at 001 and uses actual count/byte-size labels. | Implemented in preview; generic grouped execution BLOCKED |
| Any mixed P+V, including 1P+1V, produces separate P and V groups, each at most 200 | Generic planner produces P/V groups by final extension, independently numbers each type and calculates live size labels. | Preview implemented; actual execution BLOCKED by SEC-12 |
| P/V/Other classification uses the final extension, case-insensitively | `get_media_type(Path(filename).suffix)`; last suffix is used, e.g. `video.mp4.png`→P and `photo.jpg.mp4`→V. Original suffix case is preserved in target names. | Implemented in preview |
| Other retains original filename; collisions get safe suffixes, never P/V numbering | `allocate_names(kind="Other")` keeps names and allocates a casefold-safe `__dupNNN` suffix. | Implemented in planning |
| Merge only verified historical wrappers (P/P1/photos/videos/etc.); do not flatten real child works | `_is_wrapper` recognizes explicit aliases; planner blocks possible semantic work under wrappers; unit discovery can separately discover clear work IDs under legacy wrappers. | Implemented in preview, requires more edge-case coverage |
| Correct wrong-way P/V folders by actual file type | Planner classifies by extension, not folder name. | Implemented in preview |
| Already-correct layout, numbering, group count and byte labels means 0 moves/renames | Planner returns `already_organized` when the complete target mapping has no path changes and no stale wrappers. Luolcy and generic planner tests cover canonical no-op. | Implemented in preview |
| Same basename in multiple wrappers is not a duplicate; preserve every file | Media items are all retained and receive distinct numeric names. New conformance tests cover cross-wrapper `001.jpg` homonyms. | Implemented in preview; new test CI running |
| Foreign occupied targets must block; never overwrite or adopt empty foreign buckets | Generic planner checks occupied destination files/folders; manifest freezes wrapper identities; publish preflight rejects foreign occupants. | Implemented in preview/preflight; grouped publication still gated |
| Freeze, validate, stage, publish, cleanup only emptied classification wrappers, recover interruption | Generic mode has frozen manifest, FD-pinned staging/public links, WorkJob recovery and deferred-cleanup evidence. | Partial: no generic final cleanup/finalization yet |
| Second canonical scan after completion must be zero changes | Current generic Worker deliberately retains originals, stage links and wrappers, records `manual_cleanup_required`, and does not finalize. | **Not implemented** |
| UI must show status, media counts, bytes, moves, renames, wrapper cleanup and full paginated mappings | Unit list is paginated; each ready unit now has a private full mapping JSONL sidecar, admin-only paginated API and a UI full-mapping table. Samples remain in the summary for quick review. Wrapper cleanup/finalization is still absent. | Mapping implemented; cleanup partial |

## Luolcy vs non-Luolcy boundary

- **Luolcy:** existing MediaPackage implementation remains the fixed-path resource-package pipeline. Its code and regression suite were not replaced by generic semantic traversal. It already contains separate discovery, 200-file batching, shared numbering, no-op planning, execution and recovery tests.
- **Non-Luolcy:** new semantic traversal preserves arbitrary author/collection/work/version/topic directory layers and plans each independent unit separately. It reuses the shared numbering, grouping and size-label functions without forcing the MediaPackage fixed path.

## What is still preventing the complete V1.6

1. **SEC-12 / #402 — P/V group publication:** the direct-mkdir helper avoids renaming a private source directory, but `mkdirat → openat` still needs a demonstrated exclusive namespace boundary. Mode checks of the unit and immediate parent are necessary but do not exclude same-UID, root, higher-ancestor, SMB/NAS ACL or privileged writers. API, Worker and UI therefore still reject grouped plans.
2. **#400 / #399 — cleanup and finalization:** generic mode retains original source names, private stage links and old wrappers. There is no approved crash-journaled cleanup operation that safely unlinks originals and retires wrappers under verified custody.
3. **#401 — file source custody:** FD-pinned hardlink publication is covered by synthetic race tests, but actual supported NAS mount/ACL behavior still requires same-mount evidence.
4. **Idempotence after real execution:** because generic finalization is incomplete, a real completed operation followed by a canonical second scan returning 0 changes is not yet established.
5. **NAS acceptance:** no SATA same-mount run has yet been completed. GitHub-hosted CI cannot substitute for that filesystem evidence.

## Current engineering estimate

This is an engineering estimate, not a CI score:

- Semantic discovery + preview rules: **~85%**
- Shared naming / threshold / size labels / no-op planning: **~95%**
- Generic file staging/publication and recovery: **~60%**
- Safe grouped publication: **~25%**
- Generic old-wrapper cleanup/finalization: **~10%**
- Full second-scan-zero and same-mount acceptance: **~0%**

**Weighted overall completion estimate: ~59%.** The rule-driven read-only plan is substantially implemented; the complete, safe end-to-end mutation workflow is not.

## New V1.6 conformance tests

`tests/test_media_organizer_v16_rule_conformance.py` adds synthetic checks for:
- 401 P → 200 + 200 + 1, each bucket starts at 001;
- 200 P + 1 V → independent P/V groups;
- root + P + P1 + photos merged to one P series without losing homonyms;
- last-extension classification and original extension case;
- identical media basenames across historical wrappers preserved as separate files.

These tests only inspect disposable preview plans. They do not imply that grouped execution is enabled.


## Subsequent mapping implementation (after the initial traceability review)

At candidate `53ac80b`, the previously missing full mapping rule has been implemented:
- `write_semantic_preview` writes each ready unit's complete `source/target/target_name/kind/bytes` mapping to a private 0600 JSONL sidecar under a 0700 per-job directory.
- The unit summary stores a deterministic SHA-256 mapping ID while retaining only a bounded sample.
- The admin-only `GET /api/media-organizer/previews/{job_id}/mappings/{mapping_id}` endpoint verifies the completed preview and pages the full mapping (maximum 100 rows/page).
- The Batch UI now offers **查看完整映射** for each ready unit and displays all pages without loading the whole mapping into browser memory.
- Backend and frontend focused V1.6 TDD jobs passed on this candidate. Full UI/Release/C5/Gate6-D checks were still running when this note was added.

This closes the full mapping visibility gap in the confirmed rule. It does **not** close #402 grouped execution or #400 finalization.
