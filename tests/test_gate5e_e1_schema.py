import json
import pytest
from pydantic import ValidationError

from app.batch_utilities.schema import (
    QuarantineFilteredAction,
    BatchUtilityPreviewRequest,
    BatchUtilityGenerateRequest,
    BatchUtilityPreviewRow,
    BatchUtilityPreviewResponse,
)
from app.batch_utilities.errors import (
    BatchUtilityError,
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
    BatchUtilityEmptyPlanError,
    BatchUtilityPreviewChangedError,
    BatchUtilityScopeNotFoundError,
)
from app.batch_utilities.digest import (
    BATCH_UTILITY_ENGINE_VERSION,
    canonical_json_dumps,
    canonicalize_quarantine_filtered_action,
    compute_action_config_digest,
    compute_preview_digest,
)
from app.filters.schema import FilterNode, LeafNode


def test_quarantine_filtered_root_ids_are_strict_positive_distinct_and_bounded():
    ok = QuarantineFilteredAction(type="quarantine_filtered", root_ids=[3, 1], filter=None)
    assert ok.root_ids == [3, 1]

    # Bad root_ids: empty, 0, negative, boolean, duplicate, >16 roots
    for bad_ids in ([], [0], [-1], [True], [1, 1], list(range(1, 18))):
        with pytest.raises(ValidationError):
            QuarantineFilteredAction.model_validate({
                "type": "quarantine_filtered",
                "root_ids": bad_ids,
                "filter": None,
            })


def test_e1_rejects_unimplemented_action_types():
    for action_type in ("suffix_transform", "flatten_one_level", "remove_empty_dirs", "unknown"):
        with pytest.raises(ValidationError):
            BatchUtilityPreviewRequest.model_validate({
                "action": {"type": action_type, "root_ids": [1]},
                "page": 1,
                "page_size": 50,
            })


def test_preview_page_bounds():
    base = {"action": {"type": "quarantine_filtered", "root_ids": [1]}}
    for bad in ({**base, "page": 0}, {**base, "page_size": 0}, {**base, "page_size": 501}):
        with pytest.raises(ValidationError):
            BatchUtilityPreviewRequest.model_validate(bad)

    ok = BatchUtilityPreviewRequest.model_validate(base)
    assert ok.page == 1
    assert ok.page_size == 50


def test_generate_requires_64_hex_preview_digest():
    base = {"action": {"type": "quarantine_filtered", "root_ids": [1]}}
    for bad_digest in ("abc", "z" * 64, "", 123, "0" * 63, "0" * 65):
        with pytest.raises(ValidationError):
            BatchUtilityGenerateRequest.model_validate({
                **base,
                "expected_preview_digest": bad_digest,
            })

    valid_digest = "aB" + "0" * 62
    req = BatchUtilityGenerateRequest.model_validate({
        **base,
        "expected_preview_digest": valid_digest,
    })
    assert req.expected_preview_digest == valid_digest.lower()


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        QuarantineFilteredAction.model_validate({
            "type": "quarantine_filtered",
            "root_ids": [1],
            "extra_field": "forbidden",
        })

    with pytest.raises(ValidationError):
        BatchUtilityPreviewRequest.model_validate({
            "action": {"type": "quarantine_filtered", "root_ids": [1]},
            "extra_field": "forbidden",
        })


def test_structured_error_classes_and_envelopes():
    err1 = BatchUtilityInvalidConfigError("bad config", details={"field": "roots"})
    assert err1.status_code == 422
    assert err1.code == "BATCH_UTILITY_INVALID_CONFIG"
    assert err1.to_dict() == {
        "error": {
            "code": "BATCH_UTILITY_INVALID_CONFIG",
            "message": "bad config",
            "details": {"field": "roots"},
        }
    }

    err2 = BatchUtilityLimitExceededError("too many", details={"count": 60000})
    assert err2.status_code == 422
    assert err2.code == "BATCH_UTILITY_LIMIT_EXCEEDED"

    err3 = BatchUtilityEmptyPlanError("empty plan")
    assert err3.status_code == 422
    assert err3.code == "BATCH_UTILITY_EMPTY_PLAN"

    err4 = BatchUtilityPreviewChangedError(details={"expected": "a", "actual": "b"})
    assert err4.status_code == 409
    assert err4.code == "PREVIEW_CHANGED"

    err5 = BatchUtilityScopeNotFoundError("root 999 not found", details={"root_id": 999})
    assert err5.status_code == 404
    assert err5.code == "BATCH_UTILITY_SCOPE_NOT_FOUND"


def test_canonicalize_and_digest_primitives():
    action1 = QuarantineFilteredAction(
        type="quarantine_filtered",
        root_ids=[2, 1],
        filter=LeafNode(field="extension", operator="in", value=["txt", "url"]),
    )
    action2 = QuarantineFilteredAction(
        type="quarantine_filtered",
        root_ids=[1, 2],
        filter=LeafNode(field="extension", operator="in", value=["txt", "url"]),
    )

    canonical1 = canonicalize_quarantine_filtered_action(action1)
    canonical2 = canonicalize_quarantine_filtered_action(action2)

    assert canonical1["root_ids"] == [1, 2]
    assert canonical2["root_ids"] == [1, 2]
    assert canonical1 == canonical2

    digest1 = compute_action_config_digest(canonical1)
    digest2 = compute_action_config_digest(canonical2)
    assert digest1 == digest2
    assert len(digest1) == 64

    # Changing filter changes digest
    action3 = QuarantineFilteredAction(
        type="quarantine_filtered",
        root_ids=[1, 2],
        filter=LeafNode(field="extension", operator="eq", value="txt"),
    )
    canonical3 = canonicalize_quarantine_filtered_action(action3)
    digest3 = compute_action_config_digest(canonical3)
    assert digest3 != digest1


def test_preview_digest_excludes_page_and_includes_intents_and_rows():
    action_digest = "a" * 64
    source_digest = "b" * 64
    policy = {"allowed_roots": ["/data"], "protect_last_file": True}
    rows = [{"source_path": "/data/a.txt", "decision": "QUARANTINE"}]
    intents = [{"sequence": 1, "operation": "quarantine", "source_path": "/data/a.txt"}]

    d1 = compute_preview_digest(
        action_config_digest=action_digest,
        source_snapshot_digest=source_digest,
        effective_safety_policy=policy,
        decision_rows=rows,
        intents=intents,
    )
    assert len(d1) == 64

    # Same inputs -> identical digest
    d2 = compute_preview_digest(
        action_config_digest=action_digest,
        source_snapshot_digest=source_digest,
        effective_safety_policy=policy,
        decision_rows=rows,
        intents=intents,
    )
    assert d1 == d2

    # Changing any decision row changes digest
    d3 = compute_preview_digest(
        action_config_digest=action_digest,
        source_snapshot_digest=source_digest,
        effective_safety_policy=policy,
        decision_rows=[{"source_path": "/data/a.txt", "decision": "SAFETY_EXCLUDED"}],
        intents=[],
    )
    assert d3 != d1
