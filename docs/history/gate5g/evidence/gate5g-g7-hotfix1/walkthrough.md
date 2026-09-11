# Gate5-G / G7-hotfix1 Walkthrough: Initial zfuse Fallback Attempt

## 1. Objective
Implement strict no-replace rename fallback for filesystems where `renameat2(..., RENAME_NOREPLACE)` returns `EINVAL` (specifically `zfuse.zfsv3` on 极空间 NAS).

## 2. Changes Made
- Introduced `_execute_safe_noreplace_fallback()` in `app/fs_ops.py` using `os.link()` + `os.unlink()`.
- Added `_probe_rename_noreplace_supported()` attempting to probe capability by calling `renameat2(RENAME_NOREPLACE)` with a non-existent temporary source path (`.__probe_noreplace_<token>`).

## 3. Real-NAS Validation Outcome
- **FAILED on 极空间 NAS**.
- Real-NAS behavior:
  - `os.rename()` = PASS
  - `rename_noreplace(existing_src, absent_dst)` = `EINVAL (errno 22)`
  - Fallback was NOT executed.

## 4. Root Cause
Linux VFS dcache lookup returned `ENOENT` for the non-existent probe path without ever calling the underlying `zfuse` FUSE driver's `rename2` callback. The probe interpreted `ENOENT` as "kernel understood the flag", wrongly caching capability as supported (`True`), thus bypassing fallback when real operations hit `EINVAL`.
