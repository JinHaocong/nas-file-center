# Media Organizer V1.6 — SDD Design (MediaPackage + semantic)

**Status:** Product behavior approved 2026-11-17; implementation design for review. This file intentionally uses synthetic examples only.
**Goal:** Give both organizer modes one deterministic numbering and 200-item grouping contract, while adding semantic-boundary-aware recursive organization for semantic trees.

## User outcomes

- Select a source root, preview all eligible independent units, inspect every proposed source → target mapping, and optionally execute a frozen plan.
- Preserve year/month, day, author, collection, source batch, numbered work, and meaningful resolution/version directories. Do not merge across those boundaries.
- Reuse the proven MediaPackage naming and collision-safe, crash-recoverable execution rules. semantic is **not** a blind recursive variant of generic Media Sort.
- Re-running a fully canonical unit performs **zero moves and zero renames**.

## Approaches considered

| Approach | Advantage | Defect |
|---|---|---|
| Modify generic media_sort.py | Smallest initial change | Its current suffix-on-collision and per-directory P/V semantics contradict V1.6. |
| Relax MediaPackage fixed-layout validator | Reuses engine fast | Risks MediaPackage regressions; cannot identify work/collection boundaries. |
| **Chosen: shared pure policy + separate semantic unit discovery** | Reuses numbering, sizes, bounded manifests and safety; isolates interpretation | Requires a new planner, explicit tests and a safe execution adapter. |

## Ubiquitous language

- **Organizing unit:** A work/package boundary where the media count and numbering restart; neither the author nor a collection container is automatically one large unit if it contains independent works.
- **Semantic boundary:** A meaningful directory (author, dated import, numbered work, collection, quality/version, etc.) kept intact.
- **Classification wrapper:** A directory confidently known to be an old P/V/image/video/photos/P1/V2 classification layer. Only wrappers may be collapsed into their owning unit.
- **Canonical target:** Deterministic final relative filename and directory within the unit; includes actual count/size bucket labels if grouping is required.
- **Already organized:** The complete frozen source→canonical-target mapping is identity, labels and counts match actual scanned bytes, and no stale wrapper or wrongly classified entry remains.
- **Blocked:** Unsafe paths, uncertainty about a boundary, foreign destination occupancy, unsupported special files, or permission/authorization concerns. No mutation generated for the affected scope.

## Normative media policy (both MediaPackage and semantic)

1. Classify by **last extension**, case-insensitively. Preserve original extension case on renamed files. Images enter P and videos V; unrelated regular files are Other.
2. Exactly one media kind, no Other, 1–200 media files (including 200): **flatten into the unit root**, allocate consecutive names 001.ext, 002.ext, …, without P/V subfolders. Existing P/P1/photos/V wrappers are inputs and migrate out.
3. One media kind with **201+** files: chunk into groups of at most 200. Mixed P+V, even 1P+1V: create independent P/V groups, each at most 200.
4. First group P or V, subsequent groups P_1/V_1, P_2/V_2, etc. Publish as e.g. P [200 600MiB], P_1 [35 50MiB], V [4 2.1GiB]. Counts and sizes are from scanned file metadata and the existing MediaPackage size formatter.
5. Number **every media item** in every final group independently from 001 in stable order, regardless of initial filename or whether names collide. Mixed extensions share a single ordinal sequence within their media group. For pure small units, numbering is directly in the root. Files with identical original basenames all survive.
6. Other uses the existing MediaPackage policy: preserve original names; resolve Other-name collisions deterministically without replacing any entry. Media+Other is handled by MediaPackage-style P/V/Other grouping; do not infer that an Other sidecar belongs to a video from its stem.
7. **Idempotency is structural**: calculate complete canonical layout before deciding to mutate. If paths, numbering, real size/count labels and wrapper cleanup already match, return already_organized with zero I/O. Numbering alone does not make an otherwise wrong location canonical.
8. A canonical unit that later receives extra files may need regrouping; execute only the new frozen, validated plan. Never renumber arbitrarily on each scan. Changes are explained in preview.

## semantic semantic traversal

1. Scanner can start at month/day/author/work or an independent topic root; Else can contain non-month branches. Do not force all roots into YYMM/YYMMDD.
2. Continue recursively through collection/batch folders and meaningful work directories, keeping boundaries. Each work/numbered pack uses its own media statistics, threshold and 001 series.
3. Known old media wrappers (P/p, V/v, 图片/视频, photos/videos, image/picture, P1/P2/V1/V2, etc.) are **candidates**, not sufficient proof of semantics. Confirm by structure, content and absence of independent works or quality/version markers; a P directory containing independent works must not be flattened destructively.
4. Wrong-way folders (videos under P and images under V) are reclassified by extension within that unit. Do not swap the directory names directly.
5. Keep meaningful version directories (4K, PT, raw/original, enhanced, repaired), date batches, New/Old and independent package directories, even if they each contain only one media kind. Process each independently.
6. Unknown roles (e.g. numerical or unnamed folder containing potential works) produce review statuses rather than unsafe cross-boundary moves. No cross-author, cross-day or cross-version consolidation.

## Safety, performance and UX

- Preview is read-only; bounded traversal, stable ordering, no full media reads or hashes. Never dump private media filenames as test fixtures, docs or public logs.
- Execute through existing frozen manifest / identity verification / no-replace staging and publishing, worker lease, permission gates, audit/recovery; protect path roots and symlinks. Never overwrite a foreign target. Reassigning names requires staging to avoid cycles.
- Only successfully emptied **classification wrappers** may be removed after verification; never remove a work/collection/author/version or an unknown folder.
- Exclude scopes with suspicious or uncertain authorization, especially indications of illegal or nonconsensual material, from automatic handling and public indexing; folder names do not establish underlying facts.
- UI: new semantic entry separate from existing media_sort and MediaPackage; scope picker, read-only preview, paginated source→target mapping, group P/V/Other actual count and bytes, statuses already_organized/ready/blocked/skipped, source file count, affected paths, reasons and audit. No auto-execute.
- Observe large-root limits (~millions of entries) with bounded memory and cancellation; a single blocked unit should not corrupt other plans.

## Non-goals

No automatic content deduplication, deletion of duplicates, transcoding, watermark removal, cross-work consolidation, content-based guesswork, rescoring dates, or wholesale rewrite of stable MediaPackage execution.

## Behavioral acceptance matrix (synthetic only)

| Input unit | Expected output |
|---|---|
| 1P / 1V | Root 001.ext |
| 200P | Root 001–200, no P |
| 201P | P [200 actual size] + P_1 [1 actual size] |
| 401P | P[200], P_1[200], P_2[1] |
| 1P+1V | P [1 actual size]/001.ext + V [1 actual size]/001.ext |
| Root 28P + P1/7P | Root 001–035, safely remove empty P1 |
| Root 70P + V/120V | P [70 actual size] + V [120 actual size], renumber all |
| photos/1183P + videos/66V | P chunks 200×5 +183, V [66], renumber |
| P/22 videos + V/1003 images | P chunks 200×5 +3, V [22], no data loss |
| Root 10P+5V; P/80P, P1/40P, photos/30P | P [160] + V [5] |
| Nested P/P/3P | Root 001–003 if both are verified wrappers |
| 4K/220V + PT/50V | 4K groups 200+20; PT root 001–050; never merge versions |
| Collection with distinct numbered works | Each work numbered independently, no parent merge |
| Same filenames in two wrappers | Preserve both, allocate separate numbers |
| video.mp4.png + video.mp4 + subtitle.srt | Last-extension image/video classification; Other retained |
| Already canonical names, placement, labels, sizes | already_organized, zero changes |
| Numbered but still under P1 | Move/flatten as required, numbering only no-op when target ordinal identical |
| Target exists outside frozen set, symlink, worker interruption | Block safely / recover from journal; never overwrite |

## Code seams (proposed, not yet implemented)

- Preserve: app/batch/media_package_naming.py and app/batch/media_package_organizer.py fixed MediaPackage scope.
- Add: app/batch/media_organizer_units.py (read-only boundary discovery/classification).
- Add: app/batch/media_organizer_planner.py (canonical mapping, grouping, idempotency).
- Add: app/batch/media_organizer_jobs.py (bounded read-only worker preview and results).
- Add safe execution integration only after frozen manifests and recovery requirements are proven; prefer reusing existing MediaPackage execution primitives, not copying unsafe os.rename paths.
- API integration: app/api/router.py and worker registration; frontend: frontend/src/pages/Batch/index.tsx + a separate semantic editor. Build tests in tests/test_media_organizer_*.py plus existing MediaPackage regression suites.

## Delivery and review gates

- Follow Matt Pocock: inspect and align → SDD spec → tracer-bullet tickets with dependency links → each ticket TDD red/green/refactor → fresh-context code review → safe sandbox QA → controlled NAS pilot.
- Red must be observed failing for the expected reason. Green must be observed passing, and full affected regression tests and frontend checks must pass in CI.
- No merge until tests, code review, security review, and human approval. No real NAS mutation from development tasks.
- This document is a sanitized development mirror of the approved V1.6 product rule held privately in ChatGPT's 资料空间; do not paste the user's full private file tree into public repository artifacts.
