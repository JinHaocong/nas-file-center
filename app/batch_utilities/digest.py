import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from app.batch_utilities.schema import (
    QuarantineFilteredAction,
    SuffixTransformAction,
    FlattenOneLevelAction,
    RemoveEmptyDirsAction,
)
from app.batch_utilities.errors import (
    BatchUtilityScopeOverlapError,
    BatchUtilityScopeNotFoundError,
    BatchUtilityInvalidConfigError,
    BatchUtilitySymlinkBlockedError,
)
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
    Derives canonical identity from the original validated path's actual filesystem resolution.
    Does not call strip() or normpath() on the input path string.
    Preserves raw symlink leaf representation so preflight checks can detect symlinks.
    If strict resolution fails, fails closed with structured error.
    """
    raw = str(path)
    raw_leaf = raw.rstrip("/") or "/"
    try:
        st = os.lstat(raw_leaf)
        if stat.S_ISLNK(st.st_mode):
            raise BatchUtilitySymlinkBlockedError(
                f"Wrapper path '{raw}' is a symlink",
                details={"wrapper_path": raw},
            )
    except FileNotFoundError:
        raise BatchUtilityScopeNotFoundError(
            f"Wrapper directory '{raw}' does not exist",
            details={"wrapper_path": raw},
        )
    except OSError as e:
        raise BatchUtilityInvalidConfigError(
            f"Failed to access wrapper '{raw}': {e}",
            details={"wrapper_path": raw, "errno": getattr(e, "errno", None)},
        )

    try:
        resolved = Path(raw).resolve(strict=True)
        return str(resolved)
    except FileNotFoundError:
        raise BatchUtilityScopeNotFoundError(
            f"Wrapper directory '{raw}' does not exist",
            details={"wrapper_path": raw},
        )
    except OSError as e:
        raise BatchUtilityInvalidConfigError(
            f"Failed to resolve wrapper path '{raw}': {e}",
            details={"wrapper_path": raw, "errno": getattr(e, "errno", None)},
        )


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


def canonicalize_remove_empty_scope_path(path: str) -> str:
    """Canonicalize a scope directory path for remove_empty_dirs.
    Derives canonical identity from the original validated path's actual filesystem resolution.
    Does not call strip() or normpath() on the input path string.
    If leaf is a symlink (including trailing slash), fails closed with BatchUtilitySymlinkBlockedError.
    If strict resolution fails, fails closed with structured error.
    """
    raw = str(path)
    raw_leaf = raw.rstrip("/") or "/"
    try:
        st = os.lstat(raw_leaf)
        if stat.S_ISLNK(st.st_mode):
            raise BatchUtilitySymlinkBlockedError(
                f"Scope path '{raw}' is a symlink",
                details={"scope_path": raw},
            )
    except FileNotFoundError:
        raise BatchUtilityScopeNotFoundError(
            f"Scope directory '{raw}' does not exist",
            details={"scope_path": raw},
        )
    except OSError as e:
        raise BatchUtilityInvalidConfigError(
            f"Failed to access scope path '{raw}': {e}",
            details={"scope_path": raw, "errno": getattr(e, "errno", None)},
        )

    try:
        resolved = Path(raw).resolve(strict=True)
        return str(resolved)
    except FileNotFoundError:
        raise BatchUtilityScopeNotFoundError(
            f"Scope directory '{raw}' does not exist",
            details={"scope_path": raw},
        )
    except OSError as e:
        raise BatchUtilityInvalidConfigError(
            f"Failed to resolve scope path '{raw}': {e}",
            details={"scope_path": raw, "errno": getattr(e, "errno", None)},
        )


def canonicalize_remove_empty_dirs_action(action: RemoveEmptyDirsAction) -> dict[str, Any]:
    canon_paths = [canonicalize_remove_empty_scope_path(p) for p in action.scope_paths]
    if len(canon_paths) != len(set(canon_paths)):
        raise BatchUtilityScopeOverlapError(
            "Duplicate physical scope paths detected in action configuration",
            details={"scope_paths": action.scope_paths},
        )
    return {
        "type": "remove_empty_dirs",
        "scope_paths": sorted(canon_paths),
        "recursive": True,
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
    if isinstance(action, RemoveEmptyDirsAction) or (isinstance(action, dict) and action.get("type") == "remove_empty_dirs"):
        if isinstance(action, dict):
            action = RemoveEmptyDirsAction.model_validate(action)
        return canonicalize_remove_empty_dirs_action(action)
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
