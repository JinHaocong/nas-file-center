import hashlib
import json
from typing import Any, Mapping, Sequence

from app.batch_utilities.schema import QuarantineFilteredAction
from app.filters.validation import validate_filter_ast

BATCH_UTILITY_ENGINE_VERSION = 1


def canonical_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonicalize_quarantine_filtered_action(action: QuarantineFilteredAction) -> dict[str, Any]:
    sorted_root_ids = sorted(action.root_ids)
    filter_dict = None
    if action.filter is not None:
        validated = validate_filter_ast(action.filter)
        filter_dict = validated.model_dump(mode="json")
    return {
        "type": "quarantine_filtered",
        "root_ids": sorted_root_ids,
        "filter": filter_dict,
    }


def compute_action_config_digest(canonical_action: Mapping[str, Any]) -> str:
    payload = canonical_json_dumps(canonical_action)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_preview_digest(
    *,
    action_config_digest: str,
    source_snapshot_digest: str,
    effective_safety_policy: Mapping[str, Any],
    decision_rows: Sequence[Mapping[str, Any]],
    intents: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "utility_engine_version": BATCH_UTILITY_ENGINE_VERSION,
        "action_config_digest": action_config_digest,
        "source_snapshot_digest": source_snapshot_digest,
        "effective_safety_policy": dict(effective_safety_policy),
        "decision_rows": list(decision_rows),
        "intents": list(intents),
    }
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()
