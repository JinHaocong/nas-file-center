"""NAS API deferred read-only selection is never a Worker permission bypass."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from app.batch import media_organizer_deferred_selection as deferred
from app.batch import media_organizer_authority as authority
from app.batch import media_organizer_jobs as jobs


def settings(media: Path, *, enabled: bool = True, mode: str = "maintenance_window"):
    return SimpleNamespace(
        allowed_roots=[media], quarantine_root=media / ".trash",
        media_organizer_excluded_dir_names_raw="",
        nas_compat_api_deferred_selection_enabled=enabled,
        media_organizer_execution_mode=mode,
        media_organizer_execution_enabled=True,
        allow_mutation=True, allow_delete=True,
    )


@pytest.fixture
def private_tree(tmp_path, monkeypatch):
    media = tmp_path / "data"
    unit = media / "locked" / "作品"
    unit.mkdir(parents=True)
    real_lstat = os.lstat

    def restricted_lstat(p, *args, **kwargs):
        if str(p) == str(unit):
            raise PermissionError(errno.EACCES, "simulated API EACCES", str(p))
        return real_lstat(p, *args, **kwargs)

    # The queueing API is non-root; the Worker must still use real open/stat.
    monkeypatch.setattr(deferred.os, "geteuid", lambda: 10001)
    monkeypatch.delenv("NFC_NAS_COMPAT_ROOT_WORKER_ENABLED", raising=False)
    return media, unit, restricted_lstat


def test_private_subdirectory_only_deferred_in_explicit_api_mode(private_tree, monkeypatch):
    media, unit, restricted_lstat = private_tree
    original = jobs._check_scope
    def deny(path, *args):
        raise ValueError("missing or inaccessible directory")
    monkeypatch.setattr(jobs, "_check_scope", deny)
    monkeypatch.setattr(deferred.os, "lstat", restricted_lstat)
    assert jobs._validate_selection(str(unit), settings(media)) == unit
    for opt in (settings(media, enabled=False), settings(media, mode="strict")):
        with pytest.raises(ValueError, match="inaccessible"):
            jobs._validate_selection(str(unit), opt)
    monkeypatch.setenv("NFC_NAS_COMPAT_ROOT_WORKER_ENABLED", "true")
    with pytest.raises(ValueError, match="inaccessible"):
        jobs._validate_selection(str(unit), settings(media))
    monkeypatch.setattr(jobs, "_check_scope", original)


def test_denied_tail_never_approves_symlink_missing_or_reserved(tmp_path, monkeypatch):
    media = tmp_path / "data"
    media.mkdir()
    private = media / "secret"
    private.mkdir()
    alias = media / "alias"
    alias.symlink_to(private, target_is_directory=True)
    restricted = media / "secret" / "child"
    restricted.mkdir()
    real_lstat = os.lstat

    def deny_child(p, *args, **kwargs):
        if str(p) == str(restricted):
            raise PermissionError(errno.EACCES, "simulated", str(p))
        return real_lstat(p, *args, **kwargs)

    monkeypatch.setattr(deferred.os, "lstat", deny_child)
    assert deferred.has_permission_denied_tail(restricted, [media], media / ".trash")
    assert not deferred.has_permission_denied_tail(alias / "child", [media], None)
    assert not deferred.has_permission_denied_tail(media / "missing", [media], None)
    assert not deferred.has_permission_denied_tail(media / ".trash" / "child", [media], media / ".trash")
    assert not deferred.has_permission_denied_tail(media.parent / "elsewhere", [media], None)
    assert not deferred.has_permission_denied_tail(media / "secret" / ".." / "child", [media], None)


def test_deferred_eligibility_handles_only_permission_denied(private_tree, monkeypatch):
    media, unit, restricted_lstat = private_tree
    config = settings(media)
    monkeypatch.setattr(deferred.os, "lstat", restricted_lstat)
    monkeypatch.setattr(authority, "_open_directory_nofollow",
        lambda *_: (_ for _ in ()).throw(PermissionError(errno.EACCES, "private")))
    authority.check_api_eligibility(config, unit, (unit,))
    monkeypatch.setattr(authority, "_open_directory_nofollow",
        lambda *_: (_ for _ in ()).throw(FileNotFoundError(errno.ENOENT, "gone")))
    with pytest.raises(FileNotFoundError):
        authority.check_api_eligibility(config, unit, (unit,))
    config.nas_compat_api_deferred_selection_enabled = False
    monkeypatch.setattr(authority, "_open_directory_nofollow",
        lambda *_: (_ for _ in ()).throw(PermissionError(errno.EACCES, "private")))
    # With the opt-in disabled, the strict scope verifier must reject the
    # inaccessible path before the API reaches the directory-open fallback.
    # _check_scope wraps EACCES as a ValueError, not PermissionError.
    monkeypatch.setattr(authority, "_open_directory_nofollow",
        lambda *_: pytest.fail("disabled compatibility unexpectedly opened a directory"))
    with pytest.raises(ValueError, match="missing or inaccessible directory"):
        authority.check_api_eligibility(config, unit, (unit,))
