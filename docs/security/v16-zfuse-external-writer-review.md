# V1.6 ZFuse external-writer custody: verification decision (2026-11-20)

**Current decision: BLOCKED.** PR #397 remains Draft. This is a falsifiable
review plan, **not** a production custody certificate or a substitute for a
non-author GitHub security review. No NAS, production mounts, ACLs, original
media, or Komodo resources have been changed for this decision.

## What the current evidence establishes

- The old disposable SATA/ZFuse maintenance lifecycle returned
  `PASS_MAINTENANCE_LIFECYCLE` only at `f93f9d74d4992c291b685a177acc72941f6e8325`.
  It explicitly returned `namespace_exclusive_custody_proven=false`,
  `strict_custody_refused=true`, and `release_ready=false`.
- The exact current implementation at this review baseline
  `2f39de2810ecbebd8654a3a888bf02001d1ebbb0` has nine green
  non-release CI workflows and an unavailable production issuer.
- The active deferred group path creates a public directory with exclusive
  `mkdir` and then opens it by name. A different writer able to rebind that
  name between calls can cause foreign adoption. Cleanup `unlink/rmdir` of
  child names has an analogous last-check-to-syscall race. Current production
  entry points refuse without a separately issued custody resource.
- ZFuse previously returned `EOPNOTSUPP` for cross-parent
  `renameat2(RENAME_NOREPLACE)`. Do not use an ordinary rename fallback.
- The existing `scripts/v16_nas_namespace_custody_preflight.py` is
  **read-only** and checks only point-in-time POSIX/ACL/mount metadata along a
  chosen unit and ancestors. Its new FUSE option indicators are evidence
  hints, not proof: `default_permissions` may be activated through ACL
  negotiation; even a visible option cannot exclude alternate host paths
  or remote/privileged writers.

## Why the simple candidates do not establish exclusivity

| Candidate control | What it can constrain | Why it cannot issue production custody alone |
| --- | --- | --- |
| Worker UID 10002 and directory 0700/ACL | Different unprivileged local identities *if actually enforced* | Same-UID, root, mapping aliases, FUSE/NAS policy and SMB server identities are unverified |
| API read-only bind | Writes through that API mount | Other bind mounts, host namespace and remote services still have access |
| SQLite lease, `flock`, operator maintenance acknowledgement | Cooperating app instances and intended operations | An uncooperative process can ignore these, and a name can change before its syscall |
| `renameat2(RENAME_NOREPLACE)`, no-follow, FD/inode checks | Destination collision and selected descriptor identity | No-replace does not condition the *source* pathname on an inode; ZFuse support is also limited |
| inotify/fanotify observation | Report some changes | Notifications are not an atomic deny policy for unlink/rename, and cannot establish all remote aliases |
| Samba share `read only = yes` | Writes through the verified share | Other shares, NFS, local host tasks and export aliases remain outside that share policy |

References: [Linux FUSE semantics](https://www.kernel.org/doc/html/latest/filesystems/fuse/fuse.html),
[Samba share read-only semantics](https://www.samba.org/samba/docs/current/man-html/smb.conf.5),
[flock advisory behavior](https://man7.org/linux/man-pages/man2/flock.2.html),
[fanotify limitations](https://man7.org/linux/man-pages/man7/fanotify.7.html),
[renameat2 no-replace semantics](https://man7.org/linux/man-pages/man2/rename.2.html).

## Evidence still required before implementing a live issuer

1. **Threat model and trust:** identify which host administrators are trusted,
   all NAS/SMB/NFS/same-UID services able to write the exact unit and ancestors,
   all alternate exports/bind mounts, and any process capable of changing
   directory ACLs. If this cannot be exhaustively bounded, refuse.
2. **Host-owned policy:** an independently approved host control must exclude
   other untrusted writers for the *whole* execution, independent cleanup
   wait, cleanup and interruption recovery. It must bind the selected mount,
   directory inodes and all affected public/source/stage parent namespaces.
   An app-level boolean or synthetic test callback must not create this proof.
3. **Disposable-only adversarial verification (separate owner authorization):**
   use a newly created, designated scratch tree on the same ZFuse mount.
   While the proposed control is held, attempt create, rename, unlink,
   empty-dir replacement and same-inode content writes from a different
   host UID, a mapped SMB identity, each alternate export, and any in-scope
   same-UID service. These must be *prevented before mutation*, not merely
   observed afterwards. Confirm Worker writes still succeed and the
   originals/foreign sentinels retain identity and SHA-256. Test policy
   revocation and process crash before cleanup; preserve uncertain evidence.
4. **No privileged-actor illusion:** if host root is in the attacker model,
   POSIX modes/ACLs cannot demonstrate exclusion. Either explicitly define
   a trustworthy host administrator boundary with independently enforced
   policy or declare the platform unsupported.
5. **Review before activation:** a non-author reviewer must inspect the
   policy implementation, host proof lifetime/revocation, FUSE/SMB
   evidence, all last-check syscall boundaries and cleanup recovery.
   Request an actual GitHub review on PR #397 and document the decision
   in #398. Only then consider an issuer implementation and owner-authorized
   same-mount acceptance on a new commit.

## Safe current action and non-actions

The existing read-only metadata preflight may be applied to a **separately
approved existing disposable unit**, with an explicit `--data-root` and
`--unit`. It opens directory descriptors and reads metadata, not media
content. A green POSIX scope result is **not** authority to operate.

Do not run mutating capability probes, change ACLs, stop NAS shares or
run the full organizer acceptance on the owner's NAS without a separate
scoped authorization. Do not reuse the historical fixture as new evidence.
Do not change production 1.4.6 or the Komodo repository. Leave the live
`verified_namespace_custody()` issuer deny-only and Issues #398/#399/#402
open until the above independent evidence exists.

**Reviewer decision requested:** approve a concrete host isolation design
with its explicit exclusions and tests, or record `UNSUPPORTED / FAIL-CLOSED`.
No interpretation of CI green or FUSE mount flags may substitute for that decision.
