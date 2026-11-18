"""SEC-12: public group creation without renaming a mutable source basename.

These are disposable tmp_path-only tests. A tested helper is NOT sufficient
to enable grouping under uncooperative same-UID/root NAS writers: the
mkdirat→openat gap still requires independently proven namespace custody.
"""
from pathlib import Path

import pytest

from app.batch import media_organizer_publish as publishing
from app.batch.media_organizer_stage import stage_frozen_sources, _authority
from tests.test_media_organizer_pending_group_race import _grouped


def _prepare(tmp_path):
    unit, manifest, frozen = _grouped(tmp_path)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    return unit, manifest, frozen


def test_public_group_direct_creation_never_moves_a_source_directory(
    tmp_path, monkeypatch,
):
    unit, manifest, frozen = _prepare(tmp_path)
    name = manifest["groups"][0]["name"]
    source_snapshot = {
        str(row["source"]): Path(row["source"]).read_bytes()
        for row in manifest["moves"]
    }

    def forbid_source_rename(*_args, **_kwargs):
        raise AssertionError(
            "production grouped publishing must never rename a source directory"
        )

    monkeypatch.setattr(publishing, "rename_noreplace_at", forbid_source_rename)
    publishing._create_public_group_direct(
        unit, name, manifest, _authority(manifest), lambda: None,
        frozen_manifest_path=frozen,
    )
    group = unit / name
    assert group.is_dir()
    assert publishing._owned_public(group, _authority(manifest))
    receipt = publishing._group_receipt_path(frozen, 1)
    bound = publishing._read_group_receipt(receipt, manifest, name, 1)
    assert (group.stat().st_dev, group.stat().st_ino) == bound
    assert all(Path(path).read_bytes() == value for path, value in source_snapshot.items())
    assert not list((unit / manifest["stage_directory"]).glob(".nfc-publish-pending-*"))


def test_public_group_direct_creation_refuses_existing_foreign_folder(
    tmp_path, monkeypatch,
):
    unit, manifest, frozen = _prepare(tmp_path)
    name = manifest["groups"][0]["name"]
    foreign = unit / name
    foreign.mkdir()
    (foreign / "keep.txt").write_bytes(b"foreign-bytes")
    original_rename = publishing.rename_noreplace_at

    def forbid_source_rename(*_args, **_kwargs):
        raise AssertionError("wrong source-directory rename")

    monkeypatch.setattr(publishing, "rename_noreplace_at", forbid_source_rename)
    with pytest.raises(publishing.PublishingConflict):
        publishing._create_public_group_direct(
            unit, name, manifest, _authority(manifest), lambda: None,
            frozen_manifest_path=frozen,
        )
    assert (foreign / "keep.txt").read_bytes() == b"foreign-bytes"
    assert not publishing._group_receipt_path(frozen, 1).exists()
    assert original_rename is not None


def test_direct_group_alone_does_not_bypass_sec12_execution_gate(tmp_path):
    unit, manifest, frozen = _prepare(tmp_path)
    with pytest.raises(publishing.PublishingConflict, match="SEC-12"):
        publishing.publish_frozen_stage(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            lease_fence=lambda: None, defer_directory_cleanup=True,
        )
    assert all(not Path(group["destination"]).exists() for group in manifest["groups"])


def test_deferred_grouped_publication_uses_direct_group_creation_in_synthetic_custody(
    tmp_path, monkeypatch,
):
    """Synthetic custody injection checks the grouped publication branch only.

    This is NOT evidence that a real NAS mount has exclusive custody. Runtime
    validation must remain fail-closed until an enforceable custody proof exists.
    """
    from app.batch import media_organizer_deferred_cleanup as guard

    unit, manifest, frozen = _prepare(tmp_path)
    monkeypatch.setattr(guard, "validate_deferred_publication", lambda _manifest: None)

    def forbid_source_directory_rename(*_args, **_kwargs):
        raise AssertionError("deferred Worker called name-based directory promotion")

    monkeypatch.setattr(publishing, "rename_noreplace_at", forbid_source_directory_rename)
    outcome = publishing.publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, defer_directory_cleanup=True,
    )
    assert outcome["file_count"] == len(manifest["moves"])
    assert outcome["published_files"] == len(manifest["moves"])
    for row in manifest["moves"]:
        original = Path(row["source"])
        staged = Path(row["target"])
        final = Path(row["final"])
        assert final.is_file()
        assert final.read_bytes() == staged.read_bytes() == original.read_bytes()
        assert (final.stat().st_dev, final.stat().st_ino) == (
            original.stat().st_dev, original.stat().st_ino
        )
    for group in manifest["groups"]:
        directory = Path(group["destination"])
        assert publishing._owned_public(directory, _authority(manifest))
        assert directory.is_dir()
    assert not list((unit / manifest["stage_directory"]).glob(".nfc-publish-pending-*"))


def test_direct_group_recovery_with_existing_valid_inode_receipt(tmp_path, monkeypatch):
    """Crash just after group provisioning may resume with its original receipt."""
    from app.batch import media_organizer_deferred_cleanup as guard

    unit, manifest, frozen = _prepare(tmp_path)
    first_group = manifest["groups"][0]["name"]
    publishing._create_public_group_direct(
        unit, first_group, manifest, _authority(manifest), lambda: None,
        frozen_manifest_path=frozen,
    )
    monkeypatch.setattr(guard, "validate_deferred_publication", lambda _m: None)

    def never_rename(*_args, **_kwargs):
        raise AssertionError("unexpected source-directory rename during recovery")

    monkeypatch.setattr(publishing, "rename_noreplace_at", never_rename)
    result = publishing.publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, defer_directory_cleanup=True, resume=True,
    )
    assert result["file_count"] == len(manifest["moves"])
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
    assert all(Path(row["source"]).is_file() for row in manifest["moves"])


def test_direct_group_rejects_replaced_public_name_after_inode_bound(
    tmp_path, monkeypatch,
):
    """A raced public basename cannot become the directory behind our receipt."""
    import os

    unit, manifest, frozen = _prepare(tmp_path)
    name = manifest["groups"][0]["name"]
    expected = unit / name
    detached = unit / "detached-public-owner-for-audit"
    original_write_receipt = publishing._write_group_receipt
    swapped = []

    def replace_name_after_receipt(*args, **kwargs):
        result = original_write_receipt(*args, **kwargs)
        if not swapped:
            expected.rename(detached)
            expected.mkdir()
            (expected / "foreign.txt").write_bytes(b"foreign-stays")
            swapped.append(True)
        return result

    monkeypatch.setattr(publishing, "_write_group_receipt", replace_name_after_receipt)
    with pytest.raises(publishing.PublishingConflict, match="binding|identity"):
        publishing._create_public_group_direct(
            unit, name, manifest, _authority(manifest), lambda: None,
            frozen_manifest_path=frozen,
        )
    assert swapped
    assert (expected / "foreign.txt").read_bytes() == b"foreign-stays"
    assert detached.is_dir()
    assert publishing._owned_public(detached, _authority(manifest))
    assert not (detached / "foreign.txt").exists()


@pytest.mark.parametrize("unsafe_mode", [0o777, 0o770, 0o1777])
def test_direct_group_refuses_group_or_world_writable_public_parent(
    tmp_path, unsafe_mode,
):
    """Even synthetic direct mkdir must not publish into an openly writable unit."""
    unit, manifest, frozen = _prepare(tmp_path)
    name = manifest["groups"][0]["name"]
    unit.chmod(unsafe_mode)
    try:
        with pytest.raises(publishing.PublishingConflict, match="public unit.*(owner|permission|writ)"):
            publishing._create_public_group_direct(
                unit, name, manifest, _authority(manifest), lambda: None,
                frozen_manifest_path=frozen,
            )
        assert not (unit / name).exists()
        assert not publishing._group_receipt_path(frozen, 1).exists()
        assert (unit / "picture.jpg").read_bytes() == b"picture-original"
        assert (unit / "movie.mp4").read_bytes() == b"movie-original"
    finally:
        unit.chmod(0o700)


def test_direct_group_rechecks_parent_mode_after_lease_fence(
    tmp_path,
):
    """A parent becoming writable immediately before mkdir must fail closed."""
    unit, manifest, frozen = _prepare(tmp_path)
    name = manifest["groups"][0]["name"]
    calls = 0

    def change_permissions_mid_operation():
        nonlocal calls
        calls += 1
        # _check_unit calls fence at entry. The helper calls it again
        # immediately before the exclusive mkdir.
        if calls == 2:
            unit.chmod(0o777)

    try:
        with pytest.raises(publishing.PublishingConflict, match="public unit.*(owner|permission|writ)"):
            publishing._create_public_group_direct(
                unit, name, manifest, _authority(manifest),
                change_permissions_mid_operation,
                frozen_manifest_path=frozen,
            )
        assert calls >= 2
        assert not (unit / name).exists()
        assert not publishing._group_receipt_path(frozen, 1).exists()
        assert (unit / "picture.jpg").read_bytes() == b"picture-original"
        assert (unit / "movie.mp4").read_bytes() == b"movie-original"
    finally:
        unit.chmod(0o700)
