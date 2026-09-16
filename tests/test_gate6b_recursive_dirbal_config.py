from __future__ import annotations

from app.planning.dedupe_config import (
    canonical_config_dict,
    validate_and_canonicalize_config,
)


def test_recursive_directory_balanced_by_bytes_token_validates_and_canonicalizes():
    config = validate_and_canonicalize_config(
        {
            "schema_version": 1,
            "selection_mode": "recursive_directory_balanced_by_bytes",
            "factors": {},
        }
    )

    assert config.selection_mode == "recursive_directory_balanced_by_bytes"
    assert canonical_config_dict(config)["selection_mode"] == "recursive_directory_balanced_by_bytes"


def test_historical_selection_mode_tokens_remain_unchanged():
    weighted = validate_and_canonicalize_config(
        {"schema_version": 1, "selection_mode": "weighted", "factors": {}}
    )
    balanced = validate_and_canonicalize_config(
        {"schema_version": 1, "selection_mode": "balanced_by_bytes", "factors": {}}
    )

    assert weighted.selection_mode == "weighted"
    assert balanced.selection_mode == "balanced_by_bytes"
    assert canonical_config_dict(weighted)["selection_mode"] == "weighted"
    assert canonical_config_dict(balanced)["selection_mode"] == "balanced_by_bytes"
