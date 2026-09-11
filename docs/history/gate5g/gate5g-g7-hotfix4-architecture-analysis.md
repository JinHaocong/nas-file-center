# Gate5-G / G7-hotfix4 Architecture Analysis: The Linearization & Ownership Gap on zfuse

**Document Status:** HISTORICAL ARCHITECTURE ANALYSIS / PROBLEM SPECIFICATION  
**Authoritative Baseline HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Target Platform:** 极空间 NAS (ZSpace) / Linux amd64 / Docker / `zfuse.zfsv3`  
**Current State:** Gate5-G G7 BLOCKED / Gate5-G G8 NOT EXECUTED / v0.3.5 NOT CLOSED  

---

## 1. Executive Summary

During Gate5-G real-world validation on the target 极空间 NAS (ZSpace), production quarantine execution failed immediately upon encountering the underlying `zfuse.zfsv3` filesystem.

Subsequent investigations and hotfixes exposed a progressive chain of defects in attempting to provide atomic no-replace filesystem rename semantics:
- **G7-hotfix1**: Attempted naive fallback via `link()` + `unlink()`. Failed real-NAS validation because `renameat2(RENAME_NOREPLACE)` failed with `EINVAL` (errno 22) and capability probe misfired.
- **G7-hotfix2**: Fixed capability probe false-positives where probing non-existent paths returned `ENOENT` from Linux VFS dcache without reaching the FUSE driver. Switched to disposable existing object probe.
- **G7-hotfix3**: Independent code review found two data-safety blockers:
  - *Blocker A*: Blind `unlink(destination)` on source unlink failure risked deleting concurrent third-party replacement objects.
  - *Blocker B*: Destination replacement race between `link()` and `unlink(source)`.
  Hotfix3 patched this by removing blind destination cleanup and adding `lstat(destination)` identity verification before unlinking source.
- **G7-hotfix4**: Independent review conclusively demonstrated that `lstat(destination)` followed by `unlink(source)` remains inherently vulnerable to a **Time-of-Check to Time-of-Use (TOCTOU) race window**. Furthermore, symlink verification based on `readlink()` content equality is mathematically incapable of proving destination symlink generation ownership.

This document establishes the formal mathematical and operating-system proof that **no userspace compound sequence of standard POSIX system calls within a single `fs_ops` primitive can guarantee linearizable atomic no-replace semantics against concurrent hostile namespace writers without kernel VFS locking or durable application-level transactional state**.

---

## 2. Real-NAS Environment and Failure Evidence

### 2.1 Target Environment Telemetry
- **Host OS / Device**: 极空间 NAS (ZSpace OS, Linux kernel 5.10.x / amd64).
- **Filesystem**: `zfuse.zfsv3` (a proprietary user-space FUSE implementation managing storage pools and user data directories).
- **Runtime Topology**: Docker container with host mounts:
  - Host `/tmp/gate5g-safety-fixture/mutable/data` -> Container `/workspace/data`
  - Host `/tmp/gate5g-safety-fixture/mutable/quarantine` -> Container `/workspace/quarantine`
  - Both mounts share identical physical device: `st_dev` matches across source and quarantine.
- **Standard POSIX Operations**:
  - `os.rename(src, dst)`: **PASS** (POSIX standard overwrite rename succeeds).
  - `os.link(src, dst)`: **PASS** for regular files on same `st_dev`.
  - `os.unlink(path)`: **PASS**.
  - `os.lstat(path)`: **PASS**.
- **Kernel Atomic Extension**:
  - `renameat2(AT_FDCWD, src, AT_FDCWD, dst, RENAME_NOREPLACE)`: **FAILS** with:
    ```text
    errno = 22 (EINVAL: Invalid argument)
    ```
  - Direct reproduction: Calling `renameat2` with `flags=RENAME_NOREPLACE` on an existing regular file and non-existent destination immediately yields `EINVAL`. The `zfuse.zfsv3` FUSE daemon does not implement `FUSE_RENAME2` with non-zero flags.

### 2.2 The Inadequacy of Kernel Primitive Assumption
Prior to Gate5-G, NAS File Center assumed that modern Linux kernels always support `renameat2(..., RENAME_NOREPLACE)`. While true for standard kernel filesystems (ext4, XFS, Btrfs, tmpfs), FUSE-based storage daemons frequently reject unrecognized syscall flags with `EINVAL`. 

Because `nas-file-center` prioritizes data safety above all else (`数据安全 > 正确性 > 可恢复性 > 性能 > UI > 功能`), falling back to ordinary `os.rename()` is strictly prohibited as it would silently overwrite destination files if they exist or appear concurrently.

---

## 3. The TOCTOU Linearization Gap: Detailed Mechanics

### 3.1 Regular File Sequence in G7-hotfix3
The Hotfix3 regular file compatibility path executed the following sequence:
```text
Step 1: os.link(source, destination)
Step 2: st_dst = os.lstat(destination)
        assert st_dst.st_ino == st_src.st_ino and st_dst.st_dev == st_src.st_dev
Step 3: os.unlink(source)
Step 4: return success
```

### 3.2 The Uncloseable TOCTOU Window
Consider an independent concurrent actor $A$ (e.g., an SMB client, external process, or user running on the NAS host):
```text
Timeline:
t1:   Process P calls os.link(source, destination) -> SUCCESS
      (inode hard-link count = 2; source -> inode_1, destination -> inode_1)

t2:   Process P calls os.lstat(destination) -> SUCCESS
      (P observes st_dst.st_ino == inode_1; identity check passes)

t2.5: Actor A executes:
      unlink(destination)
      open(destination, O_CREAT | O_WRONLY) -> writes UNRELATED_DATA
      (destination now refers to inode_2; inode_1 hard-link count drops to 1)

t3:   Process P executes os.unlink(source) -> SUCCESS
      (source directory entry removed; inode_1 hard-link count drops to 0!)
      (Physical blocks of inode_1 freed/unlinked from filesystem namespace)

t4:   Process P returns None (SUCCESS)
```

**Consequences of the Race:**
1. **Original Data Loss**: The user's original payload (`inode_1`) is completely unlinked from the directory tree.
2. **False Success**: The application reports that the file was successfully quarantined at `destination`.
3. **Namespace Corruption**: `destination` now contains unrelated third-party data (`inode_2`).
4. **Permanent Inconsistency**: The database records `destination` as holding the quarantined item, pointing to foreign data.

### 3.3 The Symlink Ownership Illusion
When attempting fallback for symbolic links, if `os.link()` fails with `EPERM` (as standard on Linux when hard-linking symlinks is restricted), the fallback attempted:
```python
target_val = os.readlink(source)
os.symlink(target_val, destination)
# Verification:
assert os.readlink(destination) == target_val
os.unlink(source)
```

**The Fatal Flaw:**
- `os.symlink()` creates a brand-new inode ($I_{dst} \neq I_{src}$).
- `os.readlink(destination)` reads only the public target path string.
- If actor $A$ removes `destination` and creates its own symlink pointing to the same string, `os.readlink()` returns identical text.
- Content equality does **not** prove ownership or generation identity. Process $P$ cannot determine whether `destination` was created by itself or by an adversary.

---

## 4. Mathematical & OS Proof: Impossibility within `fs_ops-only` Scope

### 4.1 Theorem (Impossibility of Userspace Linearizable No-Replace Move)
*Let $S$ and $D$ be pathnames on a filesystem providing only discrete POSIX primitives `link`, `unlink`, `lstat`, and `open`. In the absence of a kernel-level atomic operation (`renameat2(RENAME_NOREPLACE)`) or userspace-held directory locks, it is impossible for an algorithm executing in userspace to guarantee all three of the following invariants against an arbitrary concurrent namespace writer:*
1. **No Overwrite**: Never overwrite pre-existing or concurrently appearing $D$.
2. **No Data Loss**: Never leave the payload of $S$ unlinked from the namespace if $D$ does not contain it.
3. **No False Success**: Never return success if $D$ refers to an object other than $S$'s payload.

### 4.2 Proof
1. **Discrete System Call Boundary**: By definition, any userspace sequence requires at least two distinct mutation calls: one to establish $D$ (`link`), and one to retire $S$ (`unlink`).
2. **Kernel VFS Inode Lock Scope**: The Linux kernel holds `inode_lock()` on directory inodes only for the duration of a single system call. When `link(S, D)` completes and returns control to userspace, `inode_lock` on the parent directory of $D$ is released.
3. **Advisory Locking Inefficacy**: POSIX file locks (`flock`, `fcntl(F_SETLK)`) apply solely to open file descriptions or byte ranges. Linux VFS `unlink` and `rename` implementations explicitly ignore advisory locks. No userspace process can prevent another process from calling `unlink(D)` or `rename(X, D)`.
4. **Arbitrary Interleaving**: Under preemptive multitasking, a concurrent writer can execute an arbitrary sequence of filesystem modifications between any two userspace instructions or system calls of process $P$.
5. **Irrevocability of Unlink**: Suppose $P$ performs verification of $D$ at time $t_v$, and executes `unlink(S)` at time $t_u > t_v$.
   - A concurrent writer can replace $D$ at $t_r \in (t_v, t_u)$.
   - At $t_u$, `unlink(S)` executes unconditionally. Inode $S$ has its last directory entry removed ($i\_nlink = 0$).
   - Even if $P$ retains an open file descriptor $fd_S$:
     - On Linux, resurrecting an unlinked file descriptor to a directory path via `linkat(fd, "", dirfd, path, AT_EMPTY_PATH)` requires `CAP_DAC_READ_SEARCH`, which is dropped in standard unprivileged Docker containers.
     - `zfuse.zfsv3` does not support `linkat(AT_EMPTY_PATH)`.
     - Path $S$ may have already been re-occupied by another actor, causing `linkat` to fail with `EEXIST`.
6. **Failure of Repeated Checks**: Adding additional `lstat` checks immediately before `unlink(S)` simply shifts the race window from $\Delta t = t_u - t_v$ to $\Delta t' = t_u - t_{v'}$. Because $\Delta t' > 0$, the probability of race is non-zero, violating the deterministic safety contract. $\blacksquare$

---

## 5. Architectural Conclusion: The Requirement for a Persistent Two-Phase Transaction

Because single-operation atomicity cannot be emulated inside `app/fs_ops.py`, NAS File Center must abandon the assumption that publication and source retirement can be compressed into a single transparent function call.

### 5.1 The Missing Architectural Entity: The Recovery Anchor
To guarantee that the original payload is **never lost**, even if `destination` is maliciously unlinked or replaced after publication, there must exist a **Private Recovery Anchor**:
- A private directory entry located in a restricted internal namespace (`quarantine/.tx/<tx_id>/anchor`).
- Established via `link(source, anchor)` **before** source retirement.
- Inaccessible to external users and SMB clients.
- Maintained until the transaction is fully committed to SQLite.
- If `destination` is attacked or replaced, `anchor` retains the original inode unharmed.

### 5.2 The Requirement for State Machine & Reconciliation Support
Because the move operation now spans multiple distinct filesystem phases, the database and worker lifecycle must support intermediate states:
- Durable intent logged.
- Anchor established.
- Public destination published.
- Source retired.
- Active / Committed.
- Conflict / Reconciliation Required.

If the system crashes at any intermediate step, a **deterministic reconciliation engine** running on worker startup can inspect the persisted database state and observed filesystem facts to converge safely without data loss.

---

## 6. Authoritative Status Declaration

```text
G7-hotfix1 = FAILED REAL-NAS VALIDATION
G7-hotfix2 = PASS CAPABILITY DISCOVERY
G7-hotfix3 = FAILED INDEPENDENT CODE REVIEW
G7-hotfix4 = BLOCKED / OPTION B MATHEMATICALLY CONFIRMED

Gate5-G G7 = BLOCKED
Gate5-G G8 = NOT EXECUTED
v0.3.5 = NOT CLOSED
```

The accompanying document `docs/superpowers/specs/2026-09-11-gate5g-zfuse-transactional-mutation-architecture-amendment.md` defines the complete specification for the Persistent Two-Phase Mutation Transaction Architecture.
