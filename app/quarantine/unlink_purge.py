from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any


SEMANTICS_VERSION = "unlink_v1"


def _absolute_lexical(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _identity_item(role: str, path: Path, entry: Any) -> tuple[dict[str, Any] | None, str | None]:
    if path.is_symlink() or os.path.islink(path):
        return None, f"SYMLINK:{role}"

    try:
        st = path.stat(follow_symlinks=False)
    except OSError:
        return None, f"MISSING_OR_UNREADABLE:{role}"

    if not stat.S_ISREG(st.st_mode):
        return None, f"NOT_REGULAR_FILE:{role}"

    if (
        st.st_dev != entry.device
        or st.st_ino != entry.inode
        or st.st_size != entry.size
        or st.st_mtime_ns != entry.mtime_ns
    ):
        return None, f"IDENTITY_MISMATCH:{role}"

    return (
        {
            "role": role,
            "path": str(path),
            "object_type": "regular_file",
            "device": st.st_dev,
            "inode": st.st_ino,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "content_hash": entry.content_hash,
        },
        None,
    )


def build_unlink_manifest(entry: Any, quarantine_root: Path | str) -> dict[str, Any]:
    """Build pathname-scoped unlink authority for one selected quarantine entry.

    This helper is intentionally read-only. It derives authority only from the
    selected entry's current NFC transaction namespace and public quarantine
    path. It never searches by inode and therefore cannot widen authority to a
    same-inode path owned by another entry.
    """
    root = _absolute_lexical(quarantine_root)
    tx_root = root / ".tx"
    generation = int(entry.active_attempt_generation or 0)
    attempt = tx_root / f"entry-{entry.id}" / f"attempt-{generation}"
    expected_anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = _absolute_lexical(entry.quarantine_path)

    blockers: list[str] = []

    def add_blocker(code: str) -> None:
        if code not in blockers:
            blockers.append(code)

    if generation <= 0:
        add_blocker("INVALID_ACTIVE_GENERATION")

    if entry.state != "active" or entry.tx_phase != "active":
        add_blocker("ENTRY_NOT_ACTIVE")

    if root.is_symlink() or tx_root.is_symlink():
        add_blocker("UNSAFE_QUARANTINE_NAMESPACE")

    if not entry.authoritative_anchor_path:
        add_blocker("MISSING_AUTHORITATIVE_ANCHOR")
    elif _absolute_lexical(entry.authoritative_anchor_path) != expected_anchor:
        add_blocker("ANCHOR_PATH_MISMATCH")

    if not _is_within(public_view, root):
        add_blocker("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    elif _is_within(public_view, tx_root):
        add_blocker("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    # Mutation authority is selected-entry pathname scoped. Inspect only the
    # selected entry's current attempt directory so an unknown private object
    # fails closed without scanning sibling entries or widening by inode.
    if attempt.exists() and not attempt.is_symlink():
        try:
            for child in sorted(attempt.iterdir(), key=lambda path: path.name):
                if child.name not in {"anchor", "captured_source"}:
                    add_blocker("UNRECOGNIZED_PRIVATE_PATH")
        except OSError:
            add_blocker("PRIVATE_NAMESPACE_UNREADABLE")

    owned_paths: list[dict[str, Any]] = []
    for role, path in (
        ("authoritative_anchor", expected_anchor),
        ("captured_source", captured_source),
        ("public_view", public_view),
    ):
        item, blocker = _identity_item(role, path, entry)
        if blocker is not None:
            add_blocker(blocker)
            continue
        assert item is not None
        owned_paths.append(item)

    return {
        "purge_semantics": SEMANTICS_VERSION,
        "selected_entry_id": entry.id,
        "active_attempt_generation": generation,
        "owned_paths": owned_paths,
        "blockers": blockers,
    }
