"""ZOS/FUSE grouped publication safety: synthetic files only, never NAS media."""
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from app.batch import media_package_execution as executor
from app.batch.media_package_organizer import preview_media_package_package


def frozen(tmp_path: Path, *, job_id: int = 720) -> tuple[Path, Path, dict]:
    root = tmp_path / "data" / "Else" / "Collection"
    package = root / "2611" / "261116" / "ExampleAuthor" / "ExampleBundle"
    inputs = package / "clips"
    inputs.mkdir(parents=True)
    for index in range(51):
        (inputs / f"{index:03d}.mp4").write_bytes(f"movie-{index}".encode())
    roots = [root.parent.parent]
    preview = preview_media_package_package(
        package, media_package_root=root, allowed_roots=roots,
    )
    assert preview["status"] == "ready"
    manifest = executor.prepare_media_package_manifest(
        package, media_package_root=root, allowed_roots=roots,
        quarantine_root=None, preview_record=preview, job_id=job_id,
    )
    assert len(manifest["groups"]) == 2
    return root, package, manifest


def force_zos_no_directory_rename(monkeypatch):
    native = executor.rename_noreplace_at

    def no_native_group_rename(srcfd, srcname, dstfd, dstname):
        if srcname.startswith(".nfc-media_package-stage-"):
            raise OSError(errno.EOPNOTSUPP, "zfuse cannot rename whole group")
        return native(srcfd, srcname, dstfd, dstname)

    def no_safe_plain_rename(src, _dst):
        raise OSError(
            errno.EOPNOTSUPP,
            "Plain directory rename no-clobber semantics are not positively proven",
            str(src),
        )

    monkeypatch.setattr(executor, "rename_noreplace_at", no_native_group_rename)
    monkeypatch.setattr(executor, "rename_directory_noreplace_compat", no_safe_plain_rename)


def assert_published(package: Path, manifest: dict):
    assert sorted(p.name for p in package.iterdir()) == sorted(
        g["final"] for g in manifest["groups"]
    )
    for index, group in enumerate(manifest["groups"]):
        directory = package / group["final"]
        actual_names = sorted(p.name for p in directory.iterdir())
        assert actual_names == sorted(
            row["target_name"]
            for row in manifest["moves"]
            if row["group"] == index
        )
        assert not any(x.startswith(".nfc-") for x in actual_names)
    assert (package / manifest["groups"][0]["final"] / "001.mp4").read_bytes() == b"movie-0"
    assert (package / manifest["groups"][1]["final"] / "001.mp4").read_bytes() == b"movie-50"
    assert not (package / "clips").exists()


def test_zfuse_without_either_safe_directory_rename_publishes_all_groups(tmp_path, monkeypatch):
    _root, package, manifest = frozen(tmp_path)
    force_zos_no_directory_rename(monkeypatch)
    result = executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert result["files_moved"] == 51
    assert result["groups_published"] == 2
    assert_published(package, manifest)
    again = executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert again["files_moved"] == 0
    assert again["files_reconciled"] == 51


def test_old_labelled_video_bucket_rebuilds_with_safe_fuse_publication(
    tmp_path, monkeypatch,
):
    root = tmp_path / "data" / "Else" / "Collection"
    package = root / "2611" / "261116" / "ExampleAuthor" / "ExampleBundle"
    old = package / "V [200 200B]"
    old.mkdir(parents=True)
    for index in range(200):
        (old / f"{index + 1:03d}.mp4").write_bytes(bytes([index % 251]))
    (package / "new.mp4").write_bytes(b"z")
    roots = [root.parent.parent]
    preview = preview_media_package_package(
        package, media_package_root=root, allowed_roots=roots,
    )
    assert preview["status"] == "ready", preview
    assert preview["conflicts"] == []
    manifest = executor.prepare_media_package_manifest(
        package, media_package_root=root, allowed_roots=roots,
        quarantine_root=None, preview_record=preview, job_id=730,
    )
    force_zos_no_directory_rename(monkeypatch)
    result = executor.execute_frozen_manifest(
        manifest, lease_fence=lambda: None, allow_fuse_compat=True,
    )
    assert result["files_moved"] == 201
    assert result["groups_published"] == 5
    assert sorted(p.name for p in package.iterdir()) == [
        "V [50 50B]", "V_1 [50 50B]", "V_2 [50 50B]", "V_3 [50 50B]", "V_4 [1 1B]",
    ]
    files = sorted(package.glob("V*/*.mp4"))
    assert len(files) == 201
    assert sorted(p.read_bytes() for p in files) == sorted(
        [bytes([index % 251]) for index in range(200)] + [b"z"]
    )
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())
    replay = executor.execute_frozen_manifest(
        manifest, lease_fence=lambda: None, allow_fuse_compat=True,
    )
    assert replay["files_moved"] == 0
    assert replay["files_reconciled"] == 201


def test_crash_after_partial_final_hardlinks_resumes_without_renaming_or_overwrite(
    tmp_path, monkeypatch,
):
    _root, package, manifest = frozen(tmp_path, job_id=721)
    force_zos_no_directory_rename(monkeypatch)
    real_link = os.link
    linked = {"count": 0}

    def crash_on_fourth_link(src, dst, *args, **kwargs):
        if str(src).endswith(".mp4") and kwargs.get("dst_dir_fd") is not None:
            linked["count"] += 1
            if linked["count"] == 4:
                raise RuntimeError("power lost during per-file publication")
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(executor.os, "link", crash_on_fourth_link)
    with pytest.raises(RuntimeError, match="power lost"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    stage = package / manifest["groups"][0]["stage"]
    final = package / manifest["groups"][0]["final"]
    assert stage.exists() and final.exists()
    assert len(list(stage.iterdir())) == 50
    assert len([p for p in final.iterdir() if p.suffix == ".mp4"]) == 3
    monkeypatch.setattr(executor.os, "link", real_link)
    recovered = executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert recovered["files_reconciled"] == 51
    assert_published(package, manifest)


def test_crash_during_stage_cleanup_keeps_final_links_and_reconciles(
    tmp_path, monkeypatch,
):
    _root, package, manifest = frozen(tmp_path, job_id=722)
    force_zos_no_directory_rename(monkeypatch)
    real_unlink = os.unlink
    removed = {"count": 0}

    def fail_on_third_stage_retirement(name, *args, **kwargs):
        if str(name).endswith(".mp4") and kwargs.get("dir_fd") is not None:
            removed["count"] += 1
            if removed["count"] == 3:
                raise RuntimeError("crash during stage hardlink retirement")
        return real_unlink(name, *args, **kwargs)

    monkeypatch.setattr(executor.os, "unlink", fail_on_third_stage_retirement)
    with pytest.raises(RuntimeError, match="stage hardlink retirement"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    stage = package / manifest["groups"][0]["stage"]
    final = package / manifest["groups"][0]["final"]
    assert stage.exists() and final.exists()
    assert len([p for p in final.iterdir() if p.suffix == ".mp4"]) == 50
    assert (final / executor._COMPAT_COMPLETE_MARKER).exists()
    monkeypatch.setattr(executor.os, "unlink", real_unlink)
    executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert_published(package, manifest)


def test_crash_after_exclusive_mkdir_before_owner_witness_is_not_adopted(
    tmp_path, monkeypatch,
):
    _root, package, manifest = frozen(tmp_path, job_id=723)
    force_zos_no_directory_rename(monkeypatch)
    original = executor._compat_create_marker

    def fail_on_owner(fd, name, data):
        if name == executor._COMPAT_OWNER_MARKER:
            raise RuntimeError("crash before durable owner witness")
        return original(fd, name, data)

    monkeypatch.setattr(executor, "_compat_create_marker", fail_on_owner)
    with pytest.raises(RuntimeError, match="before durable owner"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    stage = package / manifest["groups"][0]["stage"]
    final = package / manifest["groups"][0]["final"]
    assert stage.exists() and final.is_dir()
    assert list(final.iterdir()) == []
    monkeypatch.setattr(executor, "_compat_create_marker", original)
    with pytest.raises(executor.MediaPackageExecutionConflict, match="foreign published"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert len(list(stage.iterdir())) == 50
    assert list(final.iterdir()) == []


def test_foreign_preexisting_final_directory_is_not_adopted(tmp_path, monkeypatch):
    _root, package, manifest = frozen(tmp_path, job_id=724)
    force_zos_no_directory_rename(monkeypatch)
    original = executor._publish_group

    def create_foreign_final(frozen, index, lease_fence, **kwargs):
        final = package / frozen["groups"][index]["final"]
        final.mkdir()
        (final / "foreign.txt").write_bytes(b"do not replace")
        return original(frozen, index, lease_fence, **kwargs)

    monkeypatch.setattr(executor, "_publish_group", create_foreign_final)
    with pytest.raises(executor.MediaPackageExecutionConflict, match="foreign"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert (package / manifest["groups"][0]["final"] / "foreign.txt").read_bytes() == b"do not replace"
    assert len(list((package / manifest["groups"][0]["stage"]).iterdir())) == 50


def test_owned_marker_tampering_or_foreign_public_file_blocks_resume(tmp_path, monkeypatch):
    _root, package, manifest = frozen(tmp_path, job_id=725)
    force_zos_no_directory_rename(monkeypatch)
    original = executor._compat_create_marker

    def stop_after_owner(fd, name, data):
        original(fd, name, data)
        if name == executor._COMPAT_OWNER_MARKER:
            raise RuntimeError("intentional stop after durable owner")

    monkeypatch.setattr(executor, "_compat_create_marker", stop_after_owner)
    with pytest.raises(RuntimeError, match="durable owner"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    monkeypatch.setattr(executor, "_compat_create_marker", original)
    final = package / manifest["groups"][0]["final"]
    (final / "foreign.txt").write_bytes(b"do not touch")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="Foreign entry"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    (final / "foreign.txt").unlink()
    (final / executor._COMPAT_OWNER_MARKER).write_bytes(b"tampered")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="witness"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert len(list((package / manifest["groups"][0]["stage"]).iterdir())) == 50


def test_unsupported_directory_fsync_stops_before_creating_final_name(
    tmp_path, monkeypatch,
):
    _root, package, manifest = frozen(tmp_path, job_id=726)
    force_zos_no_directory_rename(monkeypatch)
    real_fsync = os.fsync

    def no_directory_fsync(fd):
        if os.path.isdir(f"/proc/self/fd/{fd}"):
            raise OSError(errno.EOPNOTSUPP, "zfuse directory fsync unsupported")
        return real_fsync(fd)

    monkeypatch.setattr(executor.os, "fsync", no_directory_fsync)
    with pytest.raises(OSError, match="fsync unsupported"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=True,
        )
    assert not (package / manifest["groups"][0]["final"]).exists()
    assert len(list((package / manifest["groups"][0]["stage"]).iterdir())) == 50


def test_disabled_fuse_compatibility_blocks_before_first_target_mkdir(
    tmp_path, monkeypatch,
):
    _root, package, manifest = frozen(tmp_path, job_id=727)
    force_zos_no_directory_rename(monkeypatch)
    with pytest.raises(executor.MediaPackageExecutionConflict,
                       match="FUSE grouped publication disabled"):
        executor.execute_frozen_manifest(
            manifest, lease_fence=lambda: None, allow_fuse_compat=False,
        )
    assert not (package / manifest["groups"][0]["final"]).exists()
    assert len(list((package / manifest["groups"][0]["stage"]).iterdir())) == 50
