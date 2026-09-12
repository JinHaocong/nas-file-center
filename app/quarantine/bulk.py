from __future__ import annotations

import hashlib
import json
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


def canonical_preview_digest(material: Mapping[str, Any]) -> str:
    """Hash stable UTF-8 JSON for Gate6-A Preview identity binding."""
    payload = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
