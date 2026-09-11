# Gate5-G / G7-hotfix3 Review Status

**Stage:** G7-hotfix3  
**Baseline HEAD:** `fe4ba01d578d9df23a9492c59196146f95e238c6`  
**Candidate HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Status:** **FAILED INDEPENDENT REVIEW**  

## Findings
1. The check-then-unlink pattern implemented in `_execute_safe_noreplace_fallback()` is inherently racy:
   - Sequence: `link(src, dst)` $\rightarrow$ `lstat(dst)` $\rightarrow$ `unlink(src)`.
   - If an external process replaces `dst` after `lstat` verification but before `unlink(src)`, the original `src` file is deleted from the filesystem namespace, `dst` points to unrelated data, and the function returns success.
2. Symlink ownership check based on `readlink(dst) == target_val` does not prove generation ownership.
3. Decision: Stop applying check-then-unlink patches in `fs_ops`. Formally evaluate whether linearizability can be achieved or if G7 is architecturally blocked.
