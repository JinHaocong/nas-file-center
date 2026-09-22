# Gate6-D / TASK-036-11 — SHA256 Integrity Verification

Status: IMPLEMENTED SOURCE CANDIDATE (PR #72)

## Product scope

TASK-036-11 is the final approved feature in the 036 track.

The product decision for the remaining historical 036 backlog is:

- Similarity / pHash / video similarity: OUT OF SCOPE
- Webhook / Notifications: OUT OF SCOPE
- Advanced Auth (API Token / TOTP / Recovery Codes): DEFERRED, not part of 036 closure
- Hardlink / Reflink capability expansion: DEFERRED, not part of 036 closure

After this integrity-verification candidate passes CI and is merged, the 036
feature track is source-complete. Production-verified closure still requires the
normal exact-image / real-NAS acceptance boundary.

## Integrity semantics

Integrity Verification is read-only. It does not quarantine, unlink, rename,
overwrite, or otherwise mutate a user payload.

For each analyzed media asset under explicitly selected indexed roots:

1. If no SHA256 baseline exists, the Worker first requires the live regular-file
   dev/inode/size/mtime identity to match the indexed snapshot.
2. It opens the source with no-follow semantics, hashes through the bound
   descriptor, and revalidates descriptor/path identity before accepting the
   baseline.
3. The established baseline hash and baseline physical identity are not
   automatically overwritten by later verification runs.
4. Later runs compare the live identity to the stored baseline. Identity drift
   is reported as changed.
5. If identity is unchanged, SHA256 is recomputed. A mismatch is reported as
   changed even when dev/inode/size/mtime are unchanged, covering silent content
   corruption or unexpected same-metadata modification.
6. Missing/unreadable/non-regular/unsafe paths and unstable reads are reported as
   unknown; they never create or replace a baseline.

Statuses:

- unverified
- baseline
- verified
- changed
- unknown

Important reason codes include:

- BASELINE_ESTABLISHED
- SHA256_MATCH
- SHA256_MISMATCH
- IDENTITY_CHANGED
- INDEX_IDENTITY_CHANGED
- SOURCE_UNAVAILABLE
- SOURCE_NOT_REGULAR
- SOURCE_CHANGED_DURING_HASH
- HASH_READ_FAILED
- PATH_UNSAFE

## Execution model

The operation is a checkpointed WorkJob:

`media-integrity-verify`

It reuses the existing Worker lease/fencing model, runs in bounded batches, and
checkpoints during large-file hashing. Database writes are short
`BEGIN IMMEDIATE` transactions fenced by the active Worker lease.

The Media workspace exposes root selection, SHA256 verification status,
filtering, summary counts, and Task Center progress.

## Closure boundary

Source/CI completion does not equal production verification. Final production
closure requires the exact merged image to be deployed to both API and Worker
and a small-data NAS acceptance under the isolated NAS_TEST_ROOT.
