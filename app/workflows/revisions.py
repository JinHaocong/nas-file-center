from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_dumps(data: Any) -> str:
    """Deterministic JSON serialization: sort_keys=True, compact separators, UTF-8."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_definition_sha256(data: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON serialization."""
    canonical_str = canonical_json_dumps(data)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
