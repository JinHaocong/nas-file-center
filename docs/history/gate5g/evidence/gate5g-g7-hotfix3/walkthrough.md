# Gate5-G / G7-hotfix3 Walkthrough: Fallback Ownership Hardening

## 1. Objective
Remediate Blocker A (blind destination unlinking on error) and Blocker B (destination replacement before source unlink) in `app/fs_ops.py`.

## 2. Technical Changes
1. **Blocker A Remediation**: Removed blind `os.unlink(target)` on source retirement failure. Followed "data safety over formal rollback" principle: retain both files and propagate error.
2. **Blocker B Remediation**: Added `st_dst = os.lstat(target)` verification before `os.unlink(source)`. Checked `st_dst.st_ino == st_src.st_ino` and `st_dst.st_dev == st_src.st_dev`.
3. **Special Inode Policy**: Directories and non-regular files strictly fail closed with `OSError(errno.EOPNOTSUPP)`.
4. **Contractual Docstring Accuracy**: Updated docstrings to accurately distinguish kernel atomic rename from Unix link+unlink fallback.

## 3. Independent Review Finding
Independent Code Review conclusively demonstrated that the implementation **remained vulnerable to TOCTOU**:
- If destination is replaced **after** `lstat(destination)` verification but **before** `os.unlink(source)`, `source` is deleted, destination refers to foreign data, and the function returns false success.
- Symlink `readlink()` equality check does not prove ownership because third parties can create identical symlinks.
- Result: Hotfix3 FAILED review.
