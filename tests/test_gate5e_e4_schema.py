import os
import pytest
from pydantic import ValidationError
from app.batch_utilities.schema import (
    RemoveEmptyDirsAction,
    BatchUtilityPreviewRequest,
    BatchUtilityPreviewRow,
    BatchUtilityPreviewResponse,
)
from app.batch_utilities.digest import (
    canonicalize_remove_empty_dirs_action,
    canonicalize_batch_utility_action,
    compute_action_config_digest,
)
from app.batch_utilities.errors import BatchUtilityScopeOverlapError


def test_remove_empty_dirs_schema_accepts_absolute_scope():
    action = RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=["/srv/data"], recursive=True)
    assert action.scope_paths == ["/srv/data"]
    assert action.recursive is True

    # Default recursive should be True
    action2 = RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=["/srv/data"])
    assert action2.recursive is True


def test_remove_empty_dirs_schema_rejects_empty_list():
    with pytest.raises(ValidationError):
        RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=[])


def test_remove_empty_dirs_schema_rejects_non_string():
    with pytest.raises(ValidationError):
        RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=[123])


def test_remove_empty_dirs_schema_rejects_relative_path():
    with pytest.raises(ValidationError):
        RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=["relative/path"])


def test_remove_empty_dirs_schema_rejects_exact_duplicate_only():
    with pytest.raises(ValidationError):
        RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=["/srv/data", "/srv/data"])


def test_remove_empty_dirs_schema_does_not_normpath_dedupe():
    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=["/srv/a/../b", "/srv/b"],
        recursive=True,
    )
    assert len(action.scope_paths) == 2


def test_remove_empty_dirs_schema_rejects_more_than_16_paths():
    paths = [f"/srv/path_{i}" for i in range(17)]
    with pytest.raises(ValidationError):
        RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=paths)


def test_remove_empty_dirs_schema_rejects_recursive_false():
    with pytest.raises(ValidationError):
        RemoveEmptyDirsAction(type="remove_empty_dirs", scope_paths=["/srv/data"], recursive=False)


def test_remove_empty_dirs_schema_rejects_unknown_field():
    with pytest.raises(ValidationError):
        RemoveEmptyDirsAction.model_validate({
            "type": "remove_empty_dirs",
            "scope_paths": ["/srv/data"],
            "unknown_field": "bad",
        })


def test_batch_utility_preview_request_discriminator():
    req = BatchUtilityPreviewRequest.model_validate({
        "action": {
            "type": "remove_empty_dirs",
            "scope_paths": ["/srv/data"],
        }
    })
    assert isinstance(req.action, RemoveEmptyDirsAction)
    assert req.action.type == "remove_empty_dirs"


def test_preview_row_decision_accepts_remove_empty_dir():
    row = BatchUtilityPreviewRow(
        source_path="/srv/data/empty",
        relative_path="empty",
        object_type="directory",
        decision="REMOVE_EMPTY_DIR",
    )
    assert row.decision == "REMOVE_EMPTY_DIR"


def test_canonicalize_remove_empty_dirs_action(tmp_path):
    root = tmp_path / "srv"
    root.mkdir()
    d1 = root / "b"
    d1.mkdir()
    d2 = root / "a"
    d2.mkdir()

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(d1), str(d2)],
    )
    canon = canonicalize_remove_empty_dirs_action(action)
    assert canon["type"] == "remove_empty_dirs"
    assert canon["recursive"] is True
    # Must be sorted
    assert canon["scope_paths"] == sorted([str(d1.resolve()), str(d2.resolve())])

    # Test polymorphic canonicalize_batch_utility_action
    canon_poly = canonicalize_batch_utility_action(action)
    assert canon_poly == canon

    # Test digest computation is deterministic
    digest1 = compute_action_config_digest(canon)
    digest2 = compute_action_config_digest(canon)
    assert len(digest1) == 64
    assert digest1 == digest2


def test_canonicalize_remove_empty_dirs_duplicate_physical_paths_rejected(tmp_path):
    root = tmp_path / "srv"
    root.mkdir()
    d = root / "data"
    d.mkdir()

    # Two textually different paths resolving to same physical directory
    link = root / "link_to_data"
    os.symlink(str(d), str(link))

    action = RemoveEmptyDirsAction(
        type="remove_empty_dirs",
        scope_paths=[str(d), str(link) + "/../data"],
    )
    with pytest.raises(BatchUtilityScopeOverlapError):
        canonicalize_remove_empty_dirs_action(action)
