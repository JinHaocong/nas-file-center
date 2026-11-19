"""Isolated filesystem capability tests; only synthetic disposable folders."""
import errno
from pathlib import Path

import pytest

from app.batch.media_organizer_capability_probe import (
    probe_semantic_organizer_mount,
)


def test_temporary_probe_checks_directory_noreplace_without_touching_neighbor(tmp_path):
    neighbor = tmp_path / "user-data-sentinel.txt"
    neighbor.write_bytes(b"do-not-touch")
    report = probe_semantic_organizer_mount(tmp_path)
    assert report["directory_noreplace"] is True
    assert report["directory_cross_parent_noreplace"] is True
    assert report["collision_preserved"] is True
    assert report["directory_fsync"] is True
    assert report["source_fd_hardlink_noreplace"] is True
    assert report["source_fd_name_swap_safe"] is True
    assert report["cleanup_complete"] is True
    assert report["compatible"] is True
    assert list(tmp_path.iterdir()) == [neighbor]
    assert neighbor.read_bytes() == b"do-not-touch"


def test_unsupported_directory_noreplace_reports_failure_without_deleting_neighbors(
    tmp_path, monkeypatch,
):
    from app.batch import media_organizer_capability_probe as probe_module
    sentinel = tmp_path / "real-user-file.txt"
    sentinel.write_bytes(b"retain")
    def unsupported(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "test-only no-replace unsupported")
    monkeypatch.setattr(probe_module, "rename_noreplace_at", unsupported)
    report = probe_semantic_organizer_mount(tmp_path)
    assert report["directory_noreplace"] is False
    assert report["group_directory_noreplace_compatible"] is False
    # Flat publication does not promote a public directory; a directory
    # rename limitation must not mask independent pinned-file link support.
    assert report["flat_filesystem_capabilities_compatible"] is True
    assert report["compatible"] is True
    assert report["cleanup_complete"] is True
    assert sentinel.read_bytes() == b"retain"
    assert list(tmp_path.iterdir()) == [sentinel]


def test_probe_rejects_symlink_parent_before_any_creation(tmp_path):
    link = tmp_path / "shortcut"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="literal|symlink|parent"):
        probe_semantic_organizer_mount(link)
    assert list(tmp_path.iterdir()) == [link]


def test_probe_main_requires_explicit_scratch_write_optin(tmp_path, monkeypatch):
    import sys
    from app.batch.media_organizer_capability_probe import main
    monkeypatch.setattr(sys, "argv", ["fs-probe", "--parent", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_probe_exercises_stage_child_to_unit_parent_noreplace(tmp_path, monkeypatch):
    from app.batch import media_organizer_capability_probe as probe_module
    actual = probe_module.rename_noreplace_at
    checked = []

    def record(src_fd, src, dst_fd, dst):
        checked.append((src_fd != dst_fd, src, dst))
        return actual(src_fd, src, dst_fd, dst)

    monkeypatch.setattr(probe_module, "rename_noreplace_at", record)
    result = probe_semantic_organizer_mount(tmp_path)
    assert result["directory_cross_parent_noreplace"] is True
    assert result["compatible"] is True
    assert any(other_parent and src == "pending" and dst == "occupied"
               for other_parent, src, dst in checked)
    assert any(other_parent and src == "pending" and dst == "published"
               for other_parent, src, dst in checked)
    assert list(tmp_path.iterdir()) == []


def test_missing_pinned_inode_link_is_not_mistaken_for_ordinary_hardlink_support(
    tmp_path, monkeypatch,
):
    """Fail closed on filesystems that lack Linux source-FD linkat semantics."""
    from app.batch import media_organizer_capability_probe as probe_module

    original = tmp_path / "unrelated-media.jpg"
    original.write_bytes(b"keep-me")

    def unsupported(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "synthetic missing linkat AT_EMPTY_PATH")

    monkeypatch.setattr(probe_module, "link_pinned_inode_noreplace", unsupported)
    report = probe_semantic_organizer_mount(tmp_path)
    assert report["source_fd_hardlink_noreplace"] is False
    assert report["source_fd_name_swap_safe"] is False
    assert report["compatible"] is False
    assert report["cleanup_complete"] is True
    assert original.read_bytes() == b"keep-me"
    assert list(tmp_path.iterdir()) == [original]


def test_probe_distinguishes_basic_filesystem_support_from_grouped_security(tmp_path):
    """A successful NOREPLACE probe MUST NOT promise safe source-dir promotion."""
    report = probe_semantic_organizer_mount(tmp_path)
    assert report["compatible"] is True
    assert report["flat_filesystem_capabilities_compatible"] is True
    assert report["private_stage_owner_verified"] is True
    assert report["private_stage_mode_verified"] is True
    assert report["grouped_promotion_proven"] is False
    assert report["grouped_publication_authorized"] is False
    assert report["namespace_exclusive_custody_proven"] is False
    assert list(tmp_path.iterdir()) == []


def test_probe_rejects_widened_private_stage_even_with_noreplace(tmp_path, monkeypatch):
    """Mode-0777 stage cannot count as private, even if rename/link work."""
    import os
    from app.batch import media_organizer_capability_probe as probe_module

    original_mkdir = probe_module.os.mkdir
    widened = []

    def widen_stage_after_creation(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if path == "stage" and kwargs.get("dir_fd") is not None:
            os.chmod(path, 0o777, dir_fd=kwargs["dir_fd"])
            widened.append(True)
        return result

    monkeypatch.setattr(probe_module.os, "mkdir", widen_stage_after_creation)
    report = probe_semantic_organizer_mount(tmp_path)
    assert widened
    assert report["private_stage_mode_verified"] is False
    assert report["compatible"] is False
    assert report["grouped_publication_authorized"] is False
    assert report["cleanup_complete"] is True
    assert list(tmp_path.iterdir()) == []



def test_probe_reports_directory_promotion_separately_from_flat_file_support(tmp_path, monkeypatch):
    from app.batch import media_organizer_capability_probe as probe_module

    def unsupported_directory_rename(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "synthetic renameat2 unsupported")

    monkeypatch.setattr(probe_module, "rename_noreplace_at", unsupported_directory_rename)
    report = probe_semantic_organizer_mount(tmp_path)
    assert report["group_directory_noreplace_compatible"] is False
    assert report["flat_filesystem_capabilities_compatible"] is True
    assert report["compatible"] is True
    assert report["grouped_publication_authorized"] is False
    assert report["namespace_exclusive_custody_proven"] is False
    assert list(tmp_path.iterdir()) == []
