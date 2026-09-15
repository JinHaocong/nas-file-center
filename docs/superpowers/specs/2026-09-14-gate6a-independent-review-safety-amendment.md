# Gate6-A Independent Review Safety Amendment

**Status:** Required amendment after independent Implementation + Security Review FAIL on candidate `9fb3f92fad653f73944832f8d13a8bdf801e9701`.

**Applies to:** Gate6-A COMPAT transactional permanent purge only. Gate5-A..G and the v0.3.5.1 production baseline remain closed/read-only.

This amendment supersedes only the affected Gate6-A purge mechanics in §§6.3, 6.5, and 7.2 of `2026-09-13-gate6a-quarantine-bulk-operations-architecture-freeze.md`. All other frozen Gate6-A requirements remain unchanged.

## 1. Capture: atomic no-overwrite witness

Each frozen NFC-owned payload alias is captured into its deterministic logical private slot (`current-anchor`, `captured-source`, `public-view`, or `linked-conflict-<entry>-anchor`) with descriptor-relative `link()` using `follow_symlinks=False`.

The destination creation itself is the no-overwrite fence: hard-link creation MUST fail atomically if the private slot already exists. There is no `stat(destination) -> rename(destination)` authority window and no operation may replace an existing private slot.

If a source pathname is replaced before the link syscall, the replacement is linked into the private slot, then descriptor qualification detects the foreign identity and preserves/fails closed. If the source changes after the link syscall, the private slot continues to bind the inode observed by the syscall; the later source replacement is never selected for destruction merely by pathname.

An existing private slot is never overwritten or reused. On restart it is treated only as recovery evidence and must be classified by qualification/marker rules before any further payload mutation.

## 2. Destruction: descriptor-bound zeroization, zero payload unlink

Gate6-A COMPAT purge MUST NOT perform payload-bearing `unlink()`.

Before irreversible mutation, all expected private capture slots are descriptor-qualified against the frozen regular-file identity: device, inode, original size, mtime_ns, and SHA256. `ctime` remains diagnostic-only and `st_nlink` remains forbidden as authority.

After full qualification, one canonical expected capture descriptor is reopened `O_RDWR|O_NOFOLLOW` and requalified. Worker lease is renewed/asserted immediately before exactly one payload-affecting syscall:

```text
os.ftruncate(qualified_fd, 0)
```

Because the mutation targets the opened descriptor, a pathname replacement after qualification cannot redirect the destructive syscall to a foreign inode. All NFC-owned hard-link aliases of that inode become zero-length tombstones.

No payload-bearing capture leaf is unlinked after zeroization. Zero-length same-inode leaves are retained as recovery evidence. Unknown/foreign objects are always preserved and block terminal closure.

## 3. Durable destruction provenance

Before descriptor zeroization, the purge attempt must durably create or validate an exclusive non-payload `destroy-intent.json` marker inside the current purge generation. The marker binds at least:

- schema/version;
- selected entry id;
- purge generation;
- frozen device/inode/original size/mtime_ns/SHA256;
- canonical digest of the frozen purge manifest;
- exact logical capture slot names.

Marker creation is `O_CREAT|O_EXCL`; an already-existing marker must be parsed and exactly match the expected transaction identity. Malformed or mismatched marker content is preserved and fails closed.

The marker file is fsynced before the payload-affecting syscall. It may remain after terminal purge.

## 4. Recovery truth

Recovery never treats pathname absence alone as proof of destruction.

For the current purge generation:

- expected original-size, fully qualified private captures + no marker => destruction has not started;
- valid marker + original-size, fully qualified private captures => resume descriptor zeroization;
- valid marker + all exact private capture slots are regular files with frozen device/inode and size `0` => same-transaction destructive completion evidence;
- source alias absent after valid marker is allowed only when the complete private tombstone set proves the transaction;
- source alias present with frozen device/inode and size `0` is an expected tombstone;
- source or private slot containing foreign/unknown identity => preserve + fail closed;
- expected private capture slot missing => `PURGE_RECOVERY_REQUIRED`;
- both source and private capture missing without complete valid marker/tombstone evidence => `PURGE_RECOVERY_REQUIRED`.

## 5. Terminal closure

`state/tx_phase='purged'` may be committed only when:

1. the `destroy-intent.json` marker validates against the selected entry, current generation, and frozen manifest;
2. every expected private capture slot exists as the frozen inode with size `0`;
3. every still-existing frozen source alias is the same frozen inode with size `0`;
4. no unknown private namespace object is present other than the exact marker;
5. Worker lease remains authoritative at terminal DB commit.

This amendment intentionally prefers retained zero-byte evidence over filesystem tidiness. Data-safety and recovery truth take precedence over cleanup.
