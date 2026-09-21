# Gate6-D Architecture Freeze — Media Metadata + Integrity

Status: FROZEN FOR IMPLEMENTATION  
Baseline: `main@c25e1c2daac221ebe56781ccea0776ec65ee760a`  
Canonical branch: `gate6d/media-metadata-integrity`  
Scope: TASK-036-01 through TASK-036-05 plus the approved manual corrupt-media permanent-delete amendment.

## 1. Source audit

Current baseline has:

- generic `IndexedPath` rows only: path/name/suffix/size/mtime/device/inode/type/generation;
- no Pillow/PIL dependency;
- no ffprobe runtime;
- no EXIF/media metadata model;
- no media integrity result model;
- no media-specific API/UI;
- one Worker authority and existing BatchPlan/BatchPlanItem execution;
- existing permanent deletion support, but the generic `unlink` operation is not sufficient authority for corrupt-media deletion;
- Gate6-A2 durable unlink semantics are quarantine-path scoped and MUST NOT be repurposed to authorize arbitrary source-path deletion.

Normal indexing must stay independent from media parsing. A broken/unsupported media file must never make an index-root job fail.

## 2. Product scope

### D1 — Image metadata

Supported V1 image candidates are extension-classified regular files:

`.jpg .jpeg .png .gif .webp .bmp .tif .tiff`

Extract when available:

- width
- height
- format
- date_taken
- camera
- orientation

Pillow parsing/EXIF absence must not affect generic indexing. Missing metadata is represented as nullable fields and rendered as `unknown`.

HEIC/HEIF/AVIF are not falsely classified as corrupt when the runtime has no decoder. They are outside V1 unless a decoder is explicitly added and tested.

### D2 — Video metadata

Use `ffprobe` via argv only, never shell interpolation.

Extract when available:

- duration
- width
- height
- codec
- bitrate
- fps
- audio_codec

V1 video candidates:

`.mp4 .mkv .mov .avi .webm .m4v .ts .mts .m2ts .wmv .flv .mpeg .mpg .3gp .ogv`

ffprobe output must be bounded and requested with explicit `-show_entries` fields.

### D3 — Runtime

Docker linux/amd64 runtime must contain `ffprobe`.

Build evidence must include:

`ffprobe -version`

Python runtime adds Pillow for V1 image decode/EXIF.

### D4 — Integrity classification

Per media asset:

- `healthy`
- `corrupt`
- `unknown`

Image:
- supported image candidate + successful verify/decode = healthy;
- supported image candidate + deterministic decode/format failure = corrupt;
- runtime unavailable, permission/read race, unsupported decoder, cancellation, or ambiguous resource-limit failure = unknown.

Video:
- ffprobe success + coherent video metadata = healthy;
- deterministic ffprobe invalid-data failure, or impossible metadata on an identified video stream = corrupt;
- ffprobe missing, timeout/cancellation, permission/read race, no-video-stream ambiguity, or unsupported runtime condition = unknown.

Impossible video metadata includes negative duration, non-positive dimensions on an identified video stream, and invalid negative bitrate/fps. Zero/unknown bitrate alone is not corrupt.

Detection is report-only: there is NO automatic deletion, quarantine, rename, repair, or mutation.

## 3. Media analysis lifecycle

Media probing is a separate Worker task, not part of `reindex_root`.

Flow:

`Index Root completed -> user starts Media Analysis -> Worker reads IndexedPath candidates -> probe outside DB write lock -> short fenced DB result writes`

This preserves the roadmap invariant that metadata failures do not affect normal indexing.

Work job kind: `media-analysis`.

The task is checkpoint/cancel aware and uses bounded subprocess output. It never holds a SQLite write transaction while decoding an image or waiting for ffprobe.

## 4. Data model

Add table `media_assets` with one current row per `indexed_path_id`:

- id
- indexed_path_id UNIQUE FK -> indexed_paths.id ON DELETE CASCADE
- media_kind: image | video
- width
- height
- format
- date_taken
- camera
- orientation
- duration_seconds
- codec
- bitrate
- fps
- audio_codec
- integrity_status: healthy | corrupt | unknown
- integrity_reason_code
- integrity_detail
- observed_device
- observed_inode
- observed_size
- observed_mtime_ns
- corrupt_sha256 nullable
- source_scan_generation
- probe_generation
- probed_at
- updated_at

Indexes:
- media_kind
- integrity_status
- indexed_path_id unique
- probed_at

For `corrupt` only, the Worker computes and persists SHA256 after the corruption classification while the same source identity is still bound. This hash is deletion authority, not Gate6-E similarity/integrity-verification scope.

TASK-036-11 stored-hash-vs-current-hash integrity verification remains deferred; Gate6-D does not silently absorb Gate6-E work.

## 5. Manual permanent deletion of detected corrupt media

User-approved amendment:

A media row with `integrity_status=corrupt` may be explicitly selected for PERMANENT DELETE.

"Direct delete" means:

- unlink the original source pathname;
- DO NOT create QuarantineEntry;
- DO NOT copy/move into `.nas-file-center-trash`;
- DO NOT create a recovery copy;
- deletion is irreversible at the application level.

It does NOT mean bypassing Preview/Freeze/Validate/Worker fencing.

### 5.1 Operation identity

New operation:

`media_corrupt_unlink_delete`

Semantics:

`media_corrupt_unlink_v1`

Plan kind:

`media-corrupt-delete`

This operation reuses the existing Worker and BatchPlan engine but has dedicated corrupt-evidence authority and durable journal/recovery. It must not call Gate6-A2 quarantine-purge authority.

### 5.2 Eligibility

A row is selectable only if all are true:

- media asset exists;
- `integrity_status == corrupt`;
- `corrupt_sha256` is a valid SHA256;
- source IndexedPath still exists;
- source is a regular file;
- source is under ALLOWED_ROOTS;
- source is outside QUARANTINE_ROOT;
- source path is not a symlink;
- media evidence identity equals current indexed identity.

`healthy` and `unknown` can never be permanently deleted through this Gate6-D action.

### 5.3 Preview / freeze authority

Deletion preview freezes:

- media_asset_id
- indexed_path_id
- absolute_path
- device
- inode
- size
- mtime_ns
- corrupt_sha256
- probe_generation
- integrity_reason_code
- evidence digest

The final BatchPlanItem copies the exact frozen identity and SHA256.

No live filesystem discovery may add extra paths.

### 5.4 Confirmation

Permanent deletion is admin-only and requires `ALLOW_MUTATION=true` and `ALLOW_DELETE=true`.

Confirmation token:

`DELETE_CORRUPT_FILES`

UI must explicitly say:

- files are permanently unlinked;
- files are NOT moved to quarantine;
- there is no application restore;
- only selected rows classified corrupt are included.

### 5.5 Validate / Execute

Validate must re-check:

- same media row/generation/evidence digest;
- same path;
- same regular-file type;
- same dev/inode/size/mtime;
- SHA256 still equals frozen `corrupt_sha256`;
- path remains allowed and outside quarantine.

Any drift -> stale/fail closed.

Immediately before unlink Worker must again:

- renew/assert lease;
- open parent safely;
- open leaf with no-follow semantics;
- fstat identity;
- re-hash the exact opened regular file;
- compare frozen SHA256;
- persist durable unlink intent;
- unlink only that leaf through the opened parent;
- fsync parent;
- persist terminal success.

No glob, recursive deletion, inode search, sibling cleanup, directory removal, or path widening is allowed.

### 5.6 Crash recovery

Recovery is authority-subtractive only.

- durable intent + path still present with exact frozen identity/hash -> retry that exact unlink;
- durable intent + exact path absent -> converge to completed;
- path exists but identity/hash changed -> fail closed;
- no durable intent -> recovery may not unlink anything.

A stale Worker may never publish success.

### 5.7 Post-delete DB state

After durable terminal success:

- remove the matching IndexedPath row (MediaAsset cascades);
- preserve BatchPlan/BatchPlanItem history;
- preserve AuditEvent;
- Audit includes media asset id, path, frozen identity, evidence reason, evidence digest and direct-delete semantics;
- no QuarantineEntry is created.

## 6. API

Add read APIs:

- `GET /api/media` with pagination/filter by root/kind/integrity/search
- `GET /api/media/summary`
- `POST /api/media/analyze` to enqueue media-analysis for selected indexed roots

Add corrupt-delete APIs:

- `POST /api/media/corrupt-delete/preview`
- `POST /api/media/corrupt-delete/plan`

Plan creation requires expected preview digest and `DELETE_CORRUPT_FILES`.

Execution continues through the existing Plan Validate / Execute task path.

## 7. UI

Add `/media` page using the current v0.4.9 workspace design language.

Capabilities:

- summary: analyzed / healthy / corrupt / unknown;
- root, image/video, integrity filters;
- metadata columns/detail drawer;
- explicit unknown reason;
- analyze action by index root;
- corrupt-only selection;
- single/bulk "永久删除" action creates the direct-delete plan;
- confirmation makes clear that quarantine is bypassed.

No delete control appears for healthy or unknown rows.

## 8. Migration

`media_assets` is additive.

Existing databases are backed up under the current `init_db` migration policy before the new required table is created.

No existing IndexedPath, QuarantineEntry, Plan, Audit or Task semantics are rewritten.

Deleting an index root cascades its media metadata only; it never deletes real files.

## 9. Mandatory TDD matrix

### Metadata / image
- JPEG metadata + EXIF
- PNG metadata without EXIF
- no EXIF -> nullable/unknown fields
- truncated image -> corrupt
- unsupported decoder -> unknown
- permission/read race -> unknown
- image corruption never fails generic index

### Video / ffprobe
- valid video metadata
- rational fps parsing
- audio codec extraction
- ffprobe invalid-data -> corrupt
- impossible metadata -> corrupt
- ffprobe missing -> unknown
- timeout/cancel -> unknown
- no-video-stream ambiguity -> unknown
- bounded stdout/stderr

### Worker / DB
- media-analysis pause/cancel/checkpoint
- no long DB transaction during probe
- lease loss -> no stale result write
- upsert by indexed_path_id
- old media rows disappear when IndexedPath is removed/reindexed away

### Permanent corrupt delete
- healthy rejected
- unknown rejected
- corrupt without SHA256 rejected
- selected-only
- ALLOW_DELETE=false rejected
- non-admin rejected
- confirmation mismatch rejected
- symlink rejected
- source outside allowed root rejected
- quarantine path rejected
- dev/inode/size/mtime drift rejected
- hash drift rejected
- pathname ABA rejected
- durable intent before unlink
- crash before intent -> no unlink authority
- crash after intent/before unlink -> exact retry
- crash after unlink/before DB terminal -> converges completed
- Worker lease loss -> no unauthorized success
- DB commit failure recovery
- no QuarantineEntry created
- restored/quarantine/purge regressions unchanged

### Docker / release
- Pillow import
- `ffprobe -version`
- full backend regression
- frontend tests/typecheck/build
- linux/amd64 Docker
- real-NAS read-only media probe fixture
- direct-delete acceptance only under NAS_TEST_ROOT, never production DATA

## 10. Non-negotiable invariants

- media parsing cannot make generic indexing fail;
- integrity detection never automatically mutates files;
- `unknown` is never promoted to `corrupt` merely to make deletion possible;
- direct deletion is selected-only and path-scoped;
- no quarantine copy is created for `media_corrupt_unlink_delete`;
- no second Worker or filesystem executor;
- no delete authority derived from filename/extension alone;
- no recovery path may add deletion authority;
- source replacement/ABA always fails closed;
- production DATA is never used as a Gate6-D destructive test fixture.

## 11. Implementation order

1. schema + migration tests
2. media candidate classifier / typed result model
3. Pillow image metadata + integrity
4. ffprobe runner + video metadata + integrity
5. media-analysis Worker job
6. media list/summary/analyze API
7. frontend Media page
8. corrupt-delete preview/evidence digest
9. dedicated durable direct-unlink operation + recovery
10. corrupt-delete plan API + UI
11. focused regression
12. full regression + frontend + linux/amd64 Docker
13. isolated NAS_TEST_ROOT acceptance
14. source review / closure

Gate6-E Similarity does not start until Gate6-D source closure criteria are met.
