import pytest
from pathlib import Path
import os
from app.batch_utilities.flatten import discover_flatten_one_level

def test_discover_flatten_success(tmp_path):
    wrapper = tmp_path / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    (wrapper / "b.txt").write_text("b")
    
    # Discovery
    items, errors = discover_flatten_one_level(wrapper_paths=[str(wrapper)])
    assert not errors
    assert len(items) == 2
    # Ensure targets are wrapper.parent / child.name
    targets = [item.target_path for item in items]
    assert str(tmp_path / "a.txt") in targets
    assert str(tmp_path / "b.txt") in targets

def test_discover_flatten_symlink_conflict(tmp_path):
    wrapper = tmp_path / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    os.symlink("a.txt", wrapper / "b.link")
    
    items, errors = discover_flatten_one_level(wrapper_paths=[str(wrapper)])
    assert len(items) == 1
    assert items[0].source_path.endswith("a.txt")
    assert len(errors) == 1
    assert errors[0].conflict_type == "WRAPPER_CHILD_SYMLINK"

def test_discover_flatten_oserror(tmp_path):
    # Non-existent path or unreadable directory raises BatchUtilityInvalidConfigError
    missing = tmp_path / "missing"
    from app.batch_utilities.errors import BatchUtilityInvalidConfigError
    with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
        discover_flatten_one_level(wrapper_paths=[str(missing)])
    assert exc_info.value.details.get("wrapper_path") == str(missing)
