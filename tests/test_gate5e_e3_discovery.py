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


def test_discover_flatten_leaf_symlink_blocked(tmp_path):
    """E3-hotfix9 Discovery regression:
    discover_flatten_one_level must not follow leaf symlink.
    It must raise BatchUtilitySymlinkBlockedError and not enumerate symlink target children.
    """
    from app.batch_utilities.errors import BatchUtilitySymlinkBlockedError
    root = tmp_path / "root"
    root.mkdir()
    real_dir = root / "real"
    real_dir.mkdir()
    (real_dir / "secret.txt").write_text("secret")

    symlink_dir = root / "w_link"
    os.symlink(str(real_dir), str(symlink_dir))

    with pytest.raises(BatchUtilitySymlinkBlockedError) as exc_info:
        discover_flatten_one_level([str(symlink_dir)])
    assert exc_info.value.code == "BATCH_UTILITY_SYMLINK_BLOCKED"

    # Also with trailing slash
    with pytest.raises(BatchUtilitySymlinkBlockedError) as exc_info:
        discover_flatten_one_level([str(symlink_dir) + "/"])
    assert exc_info.value.code == "BATCH_UTILITY_SYMLINK_BLOCKED"


def test_discover_flatten_wrapper_identity_mismatch_fails_closed(tmp_path):
    """Gate5-E / E3-hotfix10 Discovery unit test:
    discover_flatten_one_level with expected_identities fails closed immediately
    on ordinary directory replacement with 0 children enumerated.
    """
    from app.batch_utilities.errors import BatchUtilityInvalidConfigError

    root = tmp_path / "root"
    root.mkdir()
    wrapper = root / "w"
    wrapper.mkdir()
    (wrapper / "before.txt").write_text("before")
    st = os.stat(wrapper)

    # Replace wrapper with new directory identity containing secret.txt
    w_old = root / "w_old"
    os.rename(str(wrapper), str(w_old))
    wrapper.mkdir()
    (wrapper / "secret.txt").write_text("secret")

    with pytest.raises(BatchUtilityInvalidConfigError) as exc_info:
        discover_flatten_one_level(
            [str(wrapper)],
            expected_identities={str(wrapper): (st.st_dev, st.st_ino)},
        )
    assert "WRAPPER_IDENTITY_CHANGED" in str(exc_info.value) or exc_info.value.details.get("error") == "WRAPPER_IDENTITY_CHANGED"


