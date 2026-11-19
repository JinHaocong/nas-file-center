# V1.6 in-place organizer: maintenance-window proposal

Status: **PROPOSED — OWNER DECISION REQUIRED — NOT IMPLEMENTED**
Date: 2026-11-19
Baseline: `3500e51b8472340e3a61032434c3ab68c0bdfee5`, Draft PR #397

This document does not supersede the accepted execution safety contract,
authorize media writes, enable a feature flag, or grant namespace custody.
It records a concrete alternative requiring an explicit product decision.

## Goal and evidence

Deliver the requested in-place organizer: recursive units, P/V separation,
bounded groups, stable numbering, collision handling, separately confirmed
cleanup, interruption recovery and a zero-change second scan. A preview-only
or copy-only product is not a substitute for that goal.

The owner executed the pinned disposable Worker permission helper on the
actual SATA `zfuse.zfsv3` mount. It returned terminal
`PASS_LOCAL_PERMISSION_BOUNDARY` and exit code 0. Worker 10002:10000 succeeded;
API and foreign identities were denied as specified; each negative probe
retained the frozen inventory. Live services still had read-only canonical
data binds. The acceptance runbook records the exact scope of that result.

That observation proves the tested local access behavior. It does not
establish exclusion of remote services, same-UID peers, already-open writable
handles, other hardlinks or backing paths for the duration of a production
job. It does not show that existing media directories have the tested
Worker-owned layout.

## Why the strict issuer cannot yet be implemented for this deployment

The current production `verified_namespace_custody()` deliberately refuses
every request. Its contract requires effective namespace and content-writer
exclusion, not permission snapshots or a cooperative lock.

No currently demonstrated NAS facility controls all relevant write paths
over the original dataset. A root broker without that control would move
the unsupported assertion into another process. Mount namespaces change
mount visibility; applying Landlock to the Worker restricts that process
and its descendants. Neither makes an independent NAS service unable to
write the same underlying data. Linux leases concern regular files and
can be forcibly broken; they do not provide a permanent directory-entry
exclusion primitive. See the primary references below.

Host kernel, storage administration and mount control must be trusted in
any supported deployment. Declaring that trust does not establish that
every remote client or other privileged service has been excluded from a
selected unit. The current strict in-place route therefore remains
unsupported pending an actual storage/OS enforcement mechanism.

## Approaches considered

| Approach | What it requires | Assessment |
| --- | --- | --- |
| Preserve the strict custody contract | A storage/host mechanism controlling all write paths and incompatible existing access throughout execution and recovery | No such capability has been demonstrated on this deployment; no defensible delivery estimate |
| Explicit maintenance-window execution | The operator stops other writes to the selected unit; the application validates its own access and serializes cooperating mutations | Recommended for owner consideration; materially weaker concurrency guarantee and requires acceptance |
| New private filesystem or copy/import workspace | Independently controlled destination and additional storage/workflow | Does not satisfy in-place cleanup of the original share; not adopted as a substitute |

The recommendation is a proposal, not a decision already made by the owner.
The instruction to continue implementation is not acceptance of a weaker
concurrency guarantee.

## Proposed operating contract

The mode would organize the same explicitly selected unit in place. It
would require a maintenance window lasting through execution, separate
cleanup confirmation, and any recovery. The operator must pause writers
to that unit, including relevant NAS/SMB clients, upload/download/sync jobs,
other applications and administrative changes. Reads are allowed only when
their service does not change metadata or content as a side effect.
The window must also cover writes to the same data through other pathnames,
hardlinks, existing writable handles or backing shares, not just the path
visible in the organizer.

The application would enforce serialization of its own cooperating media
mutation jobs and validate the configured Worker identity, mounts, access,
frozen names/inodes and journal state. These checks are operational controls;
they cannot independently verify that all external writers have stopped.

Worker access remains a prerequisite. This proposal does not authorize a
recursive ownership/ACL change or assume that the accepted disposable
fixture's permissions apply to existing media. Any deployment permission
migration would require a reviewed, specifically selected scope and rollback
instructions before execution.

### The material guarantee change

| Current strict contract | Proposed maintenance-window contract |
| --- | --- |
| OS/storage-enforced exclusion of other relevant writers is required before mutation | The operator is responsible for stopping external writers during the declared window |
| No foreign source entry may be removed or relocated even when a writer replaces it after the last check | Ordinary correct results are required while the window is respected; the absolute guarantee against violating concurrent writers is not offered |
| An ACK or cooperative lease cannot authorize execution | Explicit per-unit approval may authorize this separately named operational mode, but never constitute proof of exclusive custody |

**Residual risk requiring acceptance:** if another privileged, same-UID or
remote writer continues modifying the unit, a source entry can be replaced
between a check and a name-based cleanup operation. The program may then
affect that replacement before detecting the discrepancy. In particular,
cleanup could delete a different file substituted at the checked name.
Detection, stopping and journal recovery do not guarantee that the file
can be restored. This mode must not be marketed as protection against that
race.

## Protections retained and result semantics

- No overwriting an existing destination; unknown objects must not be adopted.
- Pinned regular-file source descriptors, no-follow traversal, frozen inode
  bindings and current stage/publication checks remain required.
- Cleanup requires separate, unit-bound confirmation; crash/recovery checks
  and the durable finalization journal remain required.
- Detected permission, identity, inventory or journal changes stop the task
  and preserve evidence rather than triggering broad cleanup or repair.
- Actual NAS acceptance must compare file counts and payload hashes. A
  metadata fingerprint must not be described as full-content verification.
- Finalization requires the real canonical second scan to reach zero moves
  and zero renames.

The strict provider remains a separate path and stays unavailable on an
unproven backend. An operational session must not implement or impersonate
`ScopedNamespaceCustody`, and the existing namespace ACK must not silently
start granting the strict proof.

Proposed result semantics include `assurance_level=maintenance_window` and
`namespace_exclusive_custody_proven=false`, even after a successful job.
`execution_authorized` would describe an explicitly approved operation in
that mode, not a release decision. All execution defaults remain disabled
until implementation, acceptance and release review have completed.

## Confirmed integration work after a decision

The baseline calls the same issuer from API preview/enqueue and from Worker
execution/cleanup. It has only `assert_exclusive(Path)` and no release
lifetime. The API cannot inspect a Worker's private 0700 stage. A working
implementation must separate API eligibility from Worker acquisition and
release, including exception, restart and lease-loss paths.

Scope validation must distinguish existing bound parents, planned future
P/V/stage parents, and directories retired by the cleanup journal. Accepting
every missing path or requiring every parent to exist would both be wrong.

A healthy Worker currently processes handlers serially, but organizer
enqueue exclusion covers only organizer kinds. The database lease commits
before filesystem operations and cannot fence a paused old process at a
syscall. A cooperative operation-lifetime lock must cover every relevant
application mutator, including takeover and recovery. It still must not be
described as excluding external clients or a hostile same-UID process.

## Completion criteria if this proposal is accepted

1. Record explicit acceptance of the changed operating condition and
   concurrency guarantee. Write the implementation plan from that decision.
2. Implement the named mode, API/Worker lifetime separation, cooperating
   mutation serialization, evidence/result labeling and failure handling.
   No permissive test issuer may appear in the production execution path.
3. Run the normal API/Worker flow on a newly approved disposable unit on
   the actual SATA mount: P/V, bounded groups, historical layouts,
   collisions, independent cleanup, interruption/recovery and final 0/0.
   Verify payload hashes and counts and test that unsupported modes stop.
4. Complete candidate CI and independent release review against the chosen
   guarantee. Then prepare the final image, deployment and rollback. Design
   approval alone is not release approval or authorization over real media.

## Owner decision

Does the owner accept in-place maintenance-window mode: other writes to the
selected unit are paused during execution, cleanup and recovery; existing
integrity/recovery controls are retained; absolute protection against writers
violating that window is not promised?

Until that decision, the strict safety contract and production refusal
remain in force. No executable authorization code is added by this document.

## Primary references

- [Current production custody provider](../../../app/batch/media_organizer_custody.py)
- [Existing complete-execution safety design](2026-11-18-media-organizer-v16-complete-execution-design.md)
- [Linux file leases](https://man7.org/linux/man-pages/man2/F_GETLEASE.2const.html)
- [Linux mount namespaces](https://man7.org/linux/man-pages/man7/mount_namespaces.7.html)
- [Linux Landlock documentation](https://docs.kernel.org/userspace-api/landlock.html)
