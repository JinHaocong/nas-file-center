import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from app.batch_utilities.schema import QuarantineFilteredAction, SuffixTransformAction, FlattenOneLevelAction
from app.batch_utilities.errors import BatchUtilityScopeOverlapError
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


def canonicalize_suffix_transform_action(action: SuffixTransformAction) -> dict[str, Any]:
    sorted_root_ids = sorted(action.root_ids)
    filter_dict = None
    if action.filter is not None:
        validated = validate_filter_ast(action.filter)
        filter_dict = validated.model_dump(mode="json")
    return {
        "type": "suffix_transform",
        "root_ids": sorted_root_ids,
        "mode": action.mode.lower(),
        "suffix": action.suffix,
        "recursive": True,
        "filter": filter_dict,
    }


def canonicalize_wrapper_path(path: str) -> str:
    """Canonicalize a wrapper directory path for batch utilities.
    Normalizes redundant lexical separators, trailing slashes, '.', and '..'.
    If the path exists on disk and is a real directory without being a symlink,
    resolves to strict canonical path. Preserves raw symlink paths so no-follow
    safety checks can detect and reject them.
    """
    raw = str(path).strip()
    norm = os.path.normpath(raw)
    try:
        st = os.lstat(norm)
        if stat.S_ISLNK(st.st_mode):
            return norm
        return str(Path(norm).resolve(strict=True))
    except (OSError, FileNotFoundError, RuntimeError):
        return norm


def canonicalize_flatten_one_level_action(action: FlattenOneLevelAction) -> dict[str, Any]:
    canon_paths = [canonicalize_wrapper_path(w) for w in action.wrapper_paths]
    if len(canon_paths) != len(set(canon_paths)):
        raise BatchUtilityScopeOverlapError(
            "Duplicate wrapper paths detected in action configuration",
            details={"wrapper_paths": action.wrapper_paths},
        )
    return {
        "type": "flatten_one_level",
        "wrapper_paths": sorted(canon_paths),
    }


def canonicalize_batch_utility_action(action: Any) -> dict[str, Any]:
    if isinstance(action, QuarantineFilteredAction) or (isinstance(action, dict) and action.get("type") == "quarantine_filtered"):
        if isinstance(action, dict):
            action = QuarantineFilteredAction.model_validate(action)
        return canonicalize_quarantine_filtered_action(action)
    if isinstance(action, SuffixTransformAction) or (isinstance(action, dict) and action.get("type") == "suffix_transform"):
        if isinstance(action, dict):
            action = SuffixTransformAction.model_validate(action)
        return canonicalize_suffix_transform_action(action)
    if isinstance(action, FlattenOneLevelAction) or (isinstance(action, dict) and action.get("type") == "flatten_one_level"):
        if isinstance(action, dict):
            action = FlattenOneLevelAction.model_validate(action)
        return canonicalize_flatten_one_level_action(action)
    raise ValueError(f"Unsupported batch utility action: {action}")


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
