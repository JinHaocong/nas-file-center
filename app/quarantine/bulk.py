from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Iterable, Mapping


def canonicalize_entry_ids(entry_ids: Iterable[int]) -> list[int]:
    """Return the canonical ascending Gate6-A selection order."""
    return sorted(entry_ids)


def quarantine_entry_identity_material(entry: Any) -> dict[str, Any]:
    """Capture the persisted Gate6-A identity facts bound into Preview identity."""
    return {
        "entry_id": entry.id,
        "state": entry.state,
        "tx_phase": entry.tx_phase,
        "original_path": entry.original_path,
        "quarantine_path": entry.quarantine_path,
        "authoritative_anchor_path": entry.authoritative_anchor_path,
        "active_attempt_generation": entry.active_attempt_generation,
        "device": entry.device,
        "inode": entry.inode,
        "size": entry.size,
        "mtime_ns": entry.mtime_ns,
        "content_hash": entry.content_hash,
    }


def _absolute_lexical(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _matches_persisted_identity(path: Path, entry: Any) -> bool:
    if path.is_symlink() or os.path.islink(path):
        return False
    try:
        st = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISREG(st.st_mode)
        and st.st_dev == entry.device
        and st.st_ino == entry.inode
        and st.st_size == entry.size
        and st.st_mtime_ns == entry.mtime_ns
    )


def build_purge_topology_manifest(entry: Any, quarantine_root: Path | str) -> dict[str, Any]:
    """Build a read-only, fail-closed manifest for one transactional purge Preview."""
    root = _absolute_lexical(quarantine_root)
    tx_root = root / ".tx"
    generation = int(entry.active_attempt_generation or 0)
    attempt = tx_root / f"entry-{entry.id}" / f"attempt-{generation}"
    expected_anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = _absolute_lexical(entry.quarantine_path)
    blockers: list[str] = []

    if root.is_symlink() or tx_root.is_symlink():
        blockers.append("UNSAFE_QUARANTINE_NAMESPACE")

    if not entry.content_hash:
        blockers.append("MISSING_AUTHORITATIVE_HASH")
    if generation <= 0:
        blockers.append("INVALID_ACTIVE_GENERATION")

    if not entry.authoritative_anchor_path:
        blockers.append("MISSING_AUTHORITATIVE_ANCHOR")
    elif _absolute_lexical(entry.authoritative_anchor_path) != expected_anchor:
        blockers.append("ANCHOR_PATH_MISMATCH")

    try:
        public_view.relative_to(root)
    except ValueError:
        blockers.append("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    else:
        try:
            public_view.relative_to(tx_root)
        except ValueError:
            pass
        else:
            blockers.append("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    aliases = [
        {"role": "authoritative_anchor", "owner_entry_id": entry.id, "path": str(expected_anchor)},
        {"role": "captured_source", "owner_entry_id": entry.id, "path": str(captured_source)},
        {"role": "public_view", "owner_entry_id": entry.id, "path": str(public_view)},
    ]

    known_paths = {expected_anchor, captured_source, public_view}
    for alias in aliases:
        if not _matches_persisted_identity(Path(alias["path"]), entry):
            blockers.append(f"IDENTITY_MISMATCH:{alias['role']}")

    # Discover additional aliases only inside NFC's private transaction namespace.
    # st_nlink is intentionally not used as authority on zfuse.
    if tx_root.exists() and not tx_root.is_symlink():
        for dirpath, dirnames, filenames in os.walk(tx_root, followlinks=False):
            dirnames[:] = sorted(dirnames)
            for filename in sorted(filenames):
                candidate = _absolute_lexical(Path(dirpath) / filename)
                if candidate in known_paths or candidate.is_symlink():
                    continue
                try:
                    st = candidate.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and st.st_dev == entry.device and st.st_ino == entry.inode:
                    blockers.append(f"UNCLASSIFIED_PAYLOAD_ALIAS:{candidate}")

    return {
        "selected_entry_id": entry.id,
        "aliases": aliases,
        "historical_conflict_entry_ids": [],
        "blockers": blockers,
    }


def canonical_preview_digest(material: Mapping[str, Any]) -> str:
    """Hash stable UTF-8 JSON for Gate6-A Preview identity binding."""
    payload = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
