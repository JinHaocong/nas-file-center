# V1.6 NAS preflight diagnostic correction

Scope: continue the approved read-only NAS evidence work in #403 / PR #397.
This diagnostic correction does not change the production custody issuer,
media mutation permissions, release gates, or the full organizer design.

## Evidence and intent

The owner supplied a host metadata report for the existing disposable
primitive-harness root and organizer child. Both are API UID 10001, shared
GID 10000, mode 2770; visible POSIX access/default ACL xattrs are absent.
The preceding data-root chain is root-owned 0755, with a root-owned sticky
1777 temporary-directory ancestor, on a writable zfuse.zfsv3 mount. The
ordinary login UID 1001 cannot open the acceptance-root component; a root
metadata collection succeeds. No media changes were reported.

The existing harness deliberately uses UID 10001, so its setup is not a
failed Worker provisioning attempt. Its API ownership/shared write access
still makes it unsuitable as a Worker-exclusive namespace. A new Worker
fixture must be a sibling below the trusted data parent, not a descendant
of the mutable old harness root.

The current diagnostic incorrectly reports that Worker creation is denied
because it considers only ownership and a named-user ACL. Shared-group
permission is omitted. Its top-level exception report also hides the errno
and directory depth needed to locate an inaccessible ancestor.

## Chosen correction

Evaluate directory write-plus-search permissions under an explicit POSIX
metadata model: Worker UID, primary/shared GID from --shared-gid, and no
assumed supplementary groups. Apply owner, named-user, matching-group, then
other precedence. Apply ACL masks; a matching group entry must contain the
whole requested permission set. Do not combine partial permissions from
different matching entries. Unavailable/malformed access ACL metadata is
unknown, not a definitive access denial.

Report the model and its limits alongside the inferred permission field.
This is not an access syscall, a runtime FUSE test, a traversal guarantee,
a container UID-map validation, or an exclusive-custody assertion. Shared
group grants must leave group-write/untrusted-owner release blockers intact.

On collection failure, expose the exception type, numeric/symbolic errno,
operation, path role (data root or unit), directory depth and invoking UID.
Do not include absolute paths, component names, or exception text that could
disclose private NAS naming. Preserve no-follow directory opening and cleanup.

## Alternatives and boundaries

Changing old directory ownership would alter the previous harness and does
not address misleading diagnostics. Treating shared-group permission as
exclusive authority would weaken the existing design. Both are rejected.
Correct only the report; keep namespace_exclusive_custody_proven and
release_ready false, and keep remote/same-UID/root exclusion unproven.

Container identity/maps and actual multi-UID FUSE enforcement remain the
next NAS evidence to obtain. No fresh fixture is provisioned by this change.
