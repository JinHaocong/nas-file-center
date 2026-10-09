"""Bounded read-only filename quality audit for immediate regular files.

Conservative rules: all findings are advisory. Only trimming ASCII spaces
has an automatic rename suggestion, still subject to Plan review and execution.
"""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
import stat
import unicodedata

from app.batch.file_rename import _open_directory_nofollow
from app.path_safety import (
    require_allowed_path,
    require_unreserved_path,
    validate_mutation_destination,
)

MAX_AUDIT_ENTRIES = 10_000
# Warning threshold, not a guarantee of another filesystem's NAME_MAX.
LONG_NAME_WARNING_BYTES = 240
_WINDOWS_INVALID = re.compile(r'[<>:"/\\|?*]')
_WINDOWS_DEVICE = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
_DOCUMENT_EXTENSIONS = frozenset({
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".jpg", ".jpeg",
    ".png", ".gif", ".mp4", ".mkv", ".zip", ".rar",
})
_EXECUTABLE_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".scr", ".com", ".ps1", ".vbs", ".js",
})


def _inspect_name(name: str) -> list[str]:
    issues: list[str] = []
    if name != name.strip():
        issues.append("edge_whitespace")
    if name.endswith((".", " ")):
        issues.append("windows_trailing_dot_space")
    if _WINDOWS_INVALID.search(name):
        issues.append("windows_invalid_character")
    if _WINDOWS_DEVICE.fullmatch(name.split(".")[0]):
        issues.append("windows_reserved_device")
    # C0/C1 controls, directionality marks, zero-width format characters.
    if any(unicodedata.category(ch) in {"Cc", "Cf", "Cs"} for ch in name):
        issues.append("invisible_or_control")
    if name != unicodedata.normalize("NFC", name):
        issues.append("unicode_non_nfc")
    if len(os.fsencode(name)) > LONG_NAME_WARNING_BYTES:
        issues.append("long_name")
    suffix = Path(name).suffix
    if suffix and name[:-len(suffix)].lower().endswith(suffix.lower()):
        issues.append("repeated_extension")
    suffixes = [part.lower() for part in Path(name).suffixes]
    if (
        len(suffixes) >= 2
        and suffixes[-1] in _EXECUTABLE_EXTENSIONS
        and suffixes[-2] in _DOCUMENT_EXTENSIONS
    ):
        issues.append("suspicious_double_extension")
    return issues


def _safe_trim_suggestion(
    name: str, parent: Path, existing: set[str],
    proposed: set[str], allowed_roots: list[Path | str],
    quarantine_root: Path | str | None,
) -> tuple[str | None, str | None]:
    """Suggest only unambiguous ASCII-space trimming; no auto execution."""
    cleaned = name.strip(" ")
    if cleaned == name:
        return None, None
    try:
        if cleaned in {"", ".", ".."}:
            raise ValueError("Resulting filename is empty or reserved")
        target = validate_mutation_destination(
            parent / cleaned, allowed_roots, quarantine_root=quarantine_root,
        )
        if target.parent != parent:
            raise ValueError("Rename must stay within the selected directory")
        folded = cleaned.casefold()
        if folded in existing or folded in proposed:
            raise ValueError("Proposed name conflicts with an existing or suggested name")
        # If trimming leaves other control/invisible characters, do not
        # claim this is a complete or safe correction.
        if any(unicodedata.category(ch) in {"Cc", "Cf", "Cs"} for ch in cleaned):
            raise ValueError("File contains control/invisible characters; manual review needed")
        proposed.add(folded)
        return str(target), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def audit_immediate_filenames(
    parent: str | Path, *,
    allowed_roots: list[Path | str],
    quarantine_root: Path | str | None = None,
) -> dict:
    """Return issue findings and optional non-mutating file rename suggestions.

    Symlinks, directories, special files and quarantine content are excluded.
    Bounded one-level directory enumeration; no contents are opened/read.
    """
    raw = Path(parent).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise ValueError("Selected parent must be an absolute non-symlink directory")
    safe = require_unreserved_path(require_allowed_path(raw, allowed_roots), quarantine_root)
    if not safe.is_dir():
        raise ValueError("Selected directory does not exist")

    scanned = 0
    ignored = 0
    names: list[tuple[str, tuple[int, ...]]] = []
    occupied: set[str] = set()
    fd = _open_directory_nofollow(safe)
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                scanned += 1
                if scanned > MAX_AUDIT_ENTRIES:
                    raise ValueError(
                        f"Too many immediate entries (limit: {MAX_AUDIT_ENTRIES}); "
                        "choose a smaller directory"
                    )
                occupied.add(entry.name.casefold())
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    ignored += 1
                    continue
                # Invalid UTF-8 Unix paths cannot be represented safely by
                # JSON; report that they were skipped instead of truncating.
                try:
                    entry.name.encode("utf-8")
                except UnicodeEncodeError:
                    ignored += 1
                    continue
                names.append((
                    entry.name,
                    (int(info.st_dev), int(info.st_ino), int(info.st_size),
                     int(info.st_mtime_ns)),
                ))
    finally:
        os.close(fd)

    counts: Counter[str] = Counter()
    proposals: set[str] = set()
    results: list[dict] = []
    for name, snapshot in sorted(names):
        issues = _inspect_name(name)
        if not issues:
            continue
        counts.update(issues)
        source = safe / name
        suggestion, reason = _safe_trim_suggestion(
            name, safe, occupied, proposals, allowed_roots, quarantine_root,
        )
        # Check that the source still refers to the same regular file.
        try:
            latest = os.lstat(source)
            identity = (
                int(latest.st_dev), int(latest.st_ino),
                int(latest.st_size), int(latest.st_mtime_ns),
            )
            if not stat.S_ISREG(latest.st_mode) or identity != snapshot:
                suggestion, reason = None, "Source changed during inspection"
        except OSError:
            suggestion, reason = None, "Source cannot be verified"
        results.append({
            "name": name, "path": str(source),
            "issues": issues,
            "suggested_target": suggestion,
            "suggestion_block_reason": reason,
        })
    return {
        "parent": str(safe),
        "scanned": scanned,
        "checked_regular_files": len(names),
        "ignored_entries": ignored,
        "issues_total": sum(counts.values()),
        "counts": dict(counts),
        "items": results,
        "total": len(results),
    }
