from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


def canonicalize_entry_ids(entry_ids: Iterable[int]) -> list[int]:
    """Return the canonical ascending Gate6-A selection order."""
    return sorted(entry_ids)


def canonical_preview_digest(material: Mapping[str, Any]) -> str:
    """Hash stable UTF-8 JSON for Gate6-A Preview identity binding."""
    payload = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
