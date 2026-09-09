import pytest
from pydantic import ValidationError
from app.batch_utilities.schema import FlattenOneLevelAction, BatchUtilityAction, BatchUtilityPreviewRequest

def test_flatten_one_level_action_valid():
    action = FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=["/a/b", "/c/d"])
    assert action.type == "flatten_one_level"
    assert action.wrapper_paths == ["/a/b", "/c/d"]

def test_flatten_one_level_action_empty_list():
    with pytest.raises(ValidationError, match="wrapper_paths must be a non-empty list"):
        FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=[])

def test_flatten_one_level_action_not_absolute():
    with pytest.raises(ValidationError, match="must be absolute path"):
        FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=["a/b"])

def test_flatten_one_level_action_duplicate():
    with pytest.raises(ValidationError, match="duplicate"):
        FlattenOneLevelAction(type="flatten_one_level", wrapper_paths=["/a/b", "/a/b"])

def test_flatten_one_level_action_discriminator():
    req = BatchUtilityPreviewRequest(
        action={"type": "flatten_one_level", "wrapper_paths": ["/a"]}
    )
    assert isinstance(req.action, FlattenOneLevelAction)
    assert req.action.wrapper_paths == ["/a"]
