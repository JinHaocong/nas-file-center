from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


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


def _private_owner_id(path: Path, tx_root: Path) -> int | None:
    try:
        relative = path.relative_to(tx_root)
    except ValueError:
        return None
    if len(relative.parts) < 3:
        return None
    entry_match = re.fullmatch(r"entry-(\d+)", relative.parts[0])
    attempt_match = re.fullmatch(r"attempt-(\d+)", relative.parts[1])
    if not entry_match or not attempt_match:
        return None
    return int(entry_match.group(1))


def _same_persisted_payload_identity(left: Any, right: Any) -> bool:
    left_hash = (left.content_hash or "").lower()
    right_hash = (right.content_hash or "").lower()
    return (
        left.device == right.device
        and left.inode == right.inode
        and left.size == right.size
        and left.mtime_ns == right.mtime_ns
        and bool(left_hash)
        and left_hash == right_hash
    )


def _expected_historical_candidate_path(owner: Any, tx_root: Path) -> Path | None:
    generation = int(owner.active_attempt_generation or 0)
    if generation <= 0:
        return None
    return tx_root / f"entry-{owner.id}" / f"attempt-{generation}" / "anchor"


def build_purge_topology_manifest(
    entry: Any,
    quarantine_root: Path | str,
    *,
    owner_lookup: Callable[[int], Any | None] | None = None,
) -> dict[str, Any]:
    """Build a read-only, fail-closed manifest for one transactional purge Preview."""
    root = _absolute_lexical(quarantine_root)
    tx_root = root / ".tx"
    generation = int(entry.active_attempt_generation or 0)
    attempt = tx_root / f"entry-{entry.id}" / f"attempt-{generation}"
    expected_anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = _absolute_lexical(entry.quarantine_path)
    blockers: list[str] = []
    blocking_owner_entry_ids: set[int] = set()
    historical_conflict_entry_ids: set[int] = set()

    def add_blocker(code: str) -> None:
        if code not in blockers:
            blockers.append(code)

    if root.is_symlink() or tx_root.is_symlink():
        add_blocker("UNSAFE_QUARANTINE_NAMESPACE")

    if not entry.content_hash:
        add_blocker("MISSING_AUTHORITATIVE_HASH")
    if generation <= 0:
        add_blocker("INVALID_ACTIVE_GENERATION")

    if not entry.authoritative_anchor_path:
        add_blocker("MISSING_AUTHORITATIVE_ANCHOR")
    elif _absolute_lexical(entry.authoritative_anchor_path) != expected_anchor:
        add_blocker("ANCHOR_PATH_MISMATCH")

    try:
        public_view.relative_to(root)
    except ValueError:
        add_blocker("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    else:
        try:
            public_view.relative_to(tx_root)
        except ValueError:
            pass
        else:
            add_blocker("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    aliases = [
        {"role": "authoritative_anchor", "owner_entry_id": entry.id, "path": str(expected_anchor)},
        {"role": "captured_source", "owner_entry_id": entry.id, "path": str(captured_source)},
        {"role": "public_view", "owner_entry_id": entry.id, "path": str(public_view)},
    ]

    known_paths = {expected_anchor, captured_source, public_view}
    for alias in aliases:
        if not _matches_persisted_identity(Path(alias["path"]), entry):
            add_blocker(f"IDENTITY_MISMATCH:{alias['role']}")

    # Discover additional aliases only inside NFC's private transaction namespace.
    # st_nlink is intentionally not used as authority on zfuse.
    if tx_root.exists() and not tx_root.is_symlink():
        for dirpath, dirnames, filenames in os.walk(tx_root, followlinks=False):
            dirnames[:] = sorted(dirnames)
            for filename in sorted(filenames):
                candidate = _absolute_lexical(Path(dirpath) / filename)
                if candidate in known_paths:
                    continue
                if candidate.is_symlink():
                    if _private_owner_id(candidate, tx_root) == entry.id:
                        add_blocker("SYMLINK_IN_PAYLOAD_ALIAS_SET")
                    continue
                try:
                    st = candidate.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not (stat.S_ISREG(st.st_mode) and st.st_dev == entry.device and st.st_ino == entry.inode):
                    continue

                owner_id = _private_owner_id(candidate, tx_root)
                if owner_id is None:
                    add_blocker("UNRECOGNIZED_PRIVATE_PATH")
                    continue
                if owner_id == entry.id:
                    add_blocker("UNRECOGNIZED_PRIVATE_PATH")
                    continue

                owner = owner_lookup(owner_id) if owner_lookup is not None else None
                if owner is None:
                    add_blocker("UNKNOWN_PAYLOAD_OWNER")
                    continue

                if owner.state == "active":
                    add_blocker("SHARED_ACTIVE_PAYLOAD")
                    blocking_owner_entry_ids.add(owner_id)
                elif owner.state == "restoring":
                    add_blocker("SHARED_RESTORING_PAYLOAD")
                    blocking_owner_entry_ids.add(owner_id)
                elif owner.state == "restored":
                    add_blocker("SHARED_RESTORED_PAYLOAD")
                    blocking_owner_entry_ids.add(owner_id)
                elif (
                    owner.state == "conflict"
                    and owner.tx_phase == "conflict"
                    and owner.authoritative_anchor_path is None
                ):
                    expected_candidate = _expected_historical_candidate_path(owner, tx_root)
                    if expected_candidate is None or candidate != expected_candidate:
                        add_blocker("HISTORICAL_CONFLICT_PATH_MISMATCH")
                        blocking_owner_entry_ids.add(owner_id)
                        continue
                    if not _same_persisted_payload_identity(owner, entry):
                        add_blocker("HISTORICAL_CONFLICT_IDENTITY_MISMATCH")
                        blocking_owner_entry_ids.add(owner_id)
                        continue
                    if not _matches_persisted_identity(candidate, entry):
                        add_blocker("HISTORICAL_CONFLICT_IDENTITY_MISMATCH")
                        blocking_owner_entry_ids.add(owner_id)
                        continue
                    aliases.append(
                        {
                            "role": "historical_conflict_candidate",
                            "owner_entry_id": owner_id,
                            "path": str(candidate),
                        }
                    )
                    historical_conflict_entry_ids.add(owner_id)
                else:
                    add_blocker("UNKNOWN_PAYLOAD_OWNER_STATE")
                    blocking_owner_entry_ids.add(owner_id)

    return {
        "selected_entry_id": entry.id,
        "aliases": aliases,
        "historical_conflict_entry_ids": sorted(historical_conflict_entry_ids),
        "blocking_owner_entry_ids": sorted(blocking_owner_entry_ids),
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
