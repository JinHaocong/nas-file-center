# Gate5-G / G7-hotfix2 Walkthrough: Disposable Existing-Object Probe

## 1. Objective
Eliminate false-positive capability detection by replacing non-existent probe paths with disposable existing temporary files.

## 2. Technical Implementation
- In `app/fs_ops.py`, `_probe_rename_noreplace_supported()` creates `.__probe_noreplace_src_<hex>` via `O_CREAT | O_EXCL` in the target directory.
- Invokes `renameat2(RENAME_NOREPLACE)` to non-existent `.__probe_noreplace_dst_<hex>`.
- Supported filesystems return `0` (cached as `True`).
- Filesystems rejecting the flag (such as `zfuse.zfsv3`) return `EINVAL` (cached as `False`).
- Unconditional cleanup of temporary probe files in `finally` block.
- Inconclusive results (e.g. read-only, permission denied) fail closed without fallback.

## 3. Independent Review Finding
Independent Code Review approved the capability probe fix, but identified two critical data-safety blockers in the fallback implementation itself:
- **Blocker A**: On source `unlink` failure, blind `unlink(destination)` could delete a concurrent third-party file.
- **Blocker B**: Race condition where destination is replaced before source retirement.
Real-NAS execution was halted pending G7-hotfix3.
