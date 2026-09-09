import pytest
from pydantic import ValidationError

from app.batch_utilities.schema import (
    SuffixTransformAction,
    BatchUtilityPreviewRequest,
    BatchUtilityGenerateRequest,
)
from app.batch_utilities.digest import (
    canonicalize_suffix_transform_action,
    compute_action_config_digest,
)
from app.batch_utilities.transform import (
    canonicalize_suffix,
    compute_transformed_basename,
    TransformDecision,
)


def test_canonicalize_suffix_valid():
    assert canonicalize_suffix("txt") == ".txt"
    assert canonicalize_suffix(".txt") == ".txt"
    assert canonicalize_suffix("  .tar.gz  ") == ".tar.gz"
    assert canonicalize_suffix("tar.gz") == ".tar.gz"
    assert canonicalize_suffix("bak") == ".bak"
    assert canonicalize_suffix("TXT") == ".TXT"
    assert canonicalize_suffix(".TAR.GZ") == ".TAR.GZ"


def test_canonicalize_suffix_invalid():
    bad_suffixes = [
        "",
        "   ",
        ".",
        "..",
        "..txt",
        "txt..gz",
        ".tar..gz",
        "a/../b",
        "a/b",
        "a\\b",
        "x\0y",
    ]
    for bad in bad_suffixes:
        with pytest.raises(ValueError):
            canonicalize_suffix(bad)



def test_suffix_transform_action_validation():
    # Valid action
    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[2, 1],
        mode="append",
        suffix="txt",
    )
    assert action.type == "suffix_transform"
    assert action.root_ids == [2, 1]  # Raw list, canonicalize sorts it
    assert action.mode == "append"
    assert action.suffix == ".txt"
    assert action.recursive is True

    # Valid change mode
    action_change = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[1],
        mode="change",
        suffix=".md",
    )
    assert action_change.mode == "change"
    assert action_change.suffix == ".md"

    # Invalid mode
    with pytest.raises(ValidationError):
        SuffixTransformAction(
            type="suffix_transform",
            root_ids=[1],
            mode="delete",  # type: ignore
            suffix="txt",
        )

    # Invalid recursive (must be True)
    with pytest.raises(ValidationError):
        SuffixTransformAction(
            type="suffix_transform",
            root_ids=[1],
            mode="append",
            suffix="txt",
            recursive=False,  # type: ignore
        )

    # Invalid suffix
    with pytest.raises(ValidationError):
        SuffixTransformAction(
            type="suffix_transform",
            root_ids=[1],
            mode="append",
            suffix="",
        )


def test_preview_and_generate_request_polymorphism():
    # Preview request with SuffixTransformAction
    req = BatchUtilityPreviewRequest.model_validate({
        "action": {
            "type": "suffix_transform",
            "root_ids": [1],
            "mode": "append",
            "suffix": "txt",
        }
    })
    assert isinstance(req.action, SuffixTransformAction)
    assert req.action.suffix == ".txt"

    # Generate request with SuffixTransformAction
    digest = "a" * 64
    gen_req = BatchUtilityGenerateRequest.model_validate({
        "action": {
            "type": "suffix_transform",
            "root_ids": [1],
            "mode": "change",
            "suffix": ".bak",
        },
        "expected_preview_digest": digest,
    })
    assert isinstance(gen_req.action, SuffixTransformAction)
    assert gen_req.action.mode == "change"
    assert gen_req.action.suffix == ".bak"


def test_compute_transformed_basename_append():
    res1 = compute_transformed_basename("a", mode="append", target_suffix=".txt")
    assert res1.decision == TransformDecision.ACTIONABLE
    assert res1.target_basename == "a.txt"

    res2 = compute_transformed_basename("a.jpg", mode="append", target_suffix=".txt")
    assert res2.decision == TransformDecision.ACTIONABLE
    assert res2.target_basename == "a.jpg.txt"

    res3 = compute_transformed_basename("archive.tar.gz", mode="append", target_suffix=".txt")
    assert res3.decision == TransformDecision.ACTIONABLE
    assert res3.target_basename == "archive.tar.gz.txt"


def test_compute_transformed_basename_change():
    # Normal change
    res1 = compute_transformed_basename("a.jpg", mode="change", target_suffix=".txt")
    assert res1.decision == TransformDecision.ACTIONABLE
    assert res1.target_basename == "a.txt"

    # Multi-dot file: replaces final suffix
    res2 = compute_transformed_basename("archive.tar.gz", mode="change", target_suffix=".txt")
    assert res2.decision == TransformDecision.ACTIONABLE
    assert res2.target_basename == "archive.tar.txt"

    # No existing suffix
    res3 = compute_transformed_basename("a", mode="change", target_suffix=".txt")
    assert res3.decision == TransformDecision.SKIPPED
    assert res3.reason_code == "NO_EXISTING_SUFFIX"
    assert res3.target_basename is None

    # Dotfile with no extension (.bashrc)
    res4 = compute_transformed_basename(".bashrc", mode="change", target_suffix=".txt")
    assert res4.decision == TransformDecision.SKIPPED
    assert res4.reason_code == "NO_EXISTING_SUFFIX"
    assert res4.target_basename is None

    # Already target suffix
    res5 = compute_transformed_basename("a.txt", mode="change", target_suffix=".txt")
    assert res5.decision == TransformDecision.SKIPPED
    assert res5.reason_code == "NO_CHANGE"
    assert res5.target_basename is None


def test_canonicalize_suffix_transform_action():
    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[3, 1, 2],
        mode="append",
        suffix="txt",
    )
    canon = canonicalize_suffix_transform_action(action)
    assert canon == {
        "type": "suffix_transform",
        "root_ids": [1, 2, 3],
        "mode": "append",
        "suffix": ".txt",
        "recursive": True,
        "filter": None,
    }
    digest = compute_action_config_digest(canon)
    assert len(digest) == 64
