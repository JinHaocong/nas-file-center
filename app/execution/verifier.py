from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from app.path_safety import UnsafePathError, require_allowed_path


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: str
    sha256: str | None = None


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_duplicate_pair(
    keep: Path | str,
    delete: Path | str,
    *,
    allowed_roots: Iterable[Path | str],
    expected_size: int = 0,
    expected_hash: str | None = None,
) -> VerificationResult:
    keep_path = Path(keep)
    delete_path = Path(delete)
    if keep_path.is_symlink() or delete_path.is_symlink():
        return VerificationResult(False, "symlink is not allowed")
    try:
        keep_path = require_allowed_path(keep_path, allowed_roots)
        delete_path = require_allowed_path(delete_path, allowed_roots)
    except UnsafePathError as exc:
        return VerificationResult(False, str(exc))
    if not keep_path.is_file() or not delete_path.is_file():
        return VerificationResult(False, "both replicas must exist as regular files")
    try:
        ks = keep_path.stat(follow_symlinks=False)
        ds = delete_path.stat(follow_symlinks=False)
    except OSError as exc:
        return VerificationResult(False, f"stat failed: {exc}")
    if (ks.st_dev, ks.st_ino) == (ds.st_dev, ds.st_ino):
        return VerificationResult(False, "replicas are the same filesystem entry")
    if expected_size and (ks.st_size != expected_size or ds.st_size != expected_size):
        return VerificationResult(False, "size changed")
    if ks.st_size != ds.st_size:
        return VerificationResult(False, "replica sizes differ")
    try:
        keep_hash = sha256_file(keep_path)
        delete_hash = sha256_file(delete_path)
    except OSError as exc:
        return VerificationResult(False, f"hash read failed: {exc}")
    if keep_hash != delete_hash:
        return VerificationResult(False, "SHA256 mismatch")
    if expected_hash and keep_hash.lower() != expected_hash.lower():
        return VerificationResult(False, "SHA256 differs from frozen plan")
    return VerificationResult(True, "verified", keep_hash)
