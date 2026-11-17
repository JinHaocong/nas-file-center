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
    assert report["compatible"] is False
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
