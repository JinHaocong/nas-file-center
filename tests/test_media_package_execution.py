"""Real filesystem MediaPackage move tests use only pytest temporary directories."""
from pathlib import Path

import pytest

from app.batch.media_package_organizer import preview_media_package_package
from app.batch import media_package_execution as executor


def example(tmp_path):
    root = tmp_path / "data" / "Else" / "Collection"
    package = root / "2611" / "261115" / "SampleAuthor" / "SampleBundle"
    package.mkdir(parents=True)
    return root, package


def manifest_for(root, package, job_id=521):
    roots = [root.parent.parent]
    preview = preview_media_package_package(
        package, media_package_root=root, allowed_roots=roots,
    )
    assert preview["status"] == "ready", preview
    manifest = executor.prepare_media_package_manifest(
        package, media_package_root=root, allowed_roots=roots,
        quarantine_root=None, preview_record=preview, job_id=job_id,
    )
    assert manifest["input_fingerprint"] == preview["input_fingerprint"]
    return manifest


def test_pure_media_nested_200_moves_to_root_and_prunes_empty_subdirs(tmp_path):
    root, package = example(tmp_path)
    a = package / "视频A"
    b = package / "视频B"
    a.mkdir()
    b.mkdir()
    (a / "001.mp4").write_bytes(b"one")
    (b / "002.mp4").write_bytes(b"two")
    manifest = manifest_for(root, package)
    assert len(manifest["groups"]) == 0
    assert len(manifest["moves"]) == 2
    evidence = tmp_path / "config" / "plan.json"
    executor.save_frozen_manifest(evidence, manifest)
    loaded = executor.load_frozen_manifest(evidence, job_id=521, package=package)
    result = executor.execute_frozen_manifest(loaded, lease_fence=lambda: None)
    assert result["files_moved"] == 2
    assert result["empty_dirs_removed"] == 2
    assert (package / "001.mp4").read_bytes() == b"one"
    assert (package / "002.mp4").read_bytes() == b"two"
    assert package.exists()
    assert not a.exists()
    assert not b.exists()
    assert not any(p.name.startswith("V [") for p in package.iterdir())


def test_over_200_files_staged_and_published_with_exact_count_size(tmp_path):
    root, package = example(tmp_path)
    nested = package / "图包"
    nested.mkdir()
    for i in range(201):
        (nested / f"{i:03d}.jpg").write_bytes(b"123")
    manifest = manifest_for(root, package)
    assert len(manifest["groups"]) == 2
    assert [x["final"] for x in manifest["groups"]] == [
        "P [200 600B]", "P_1 [1 3B]",
    ]
    finished = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert finished["files_moved"] == 201
    assert (package / "P [200 600B]" / "200.jpg").read_bytes() == b"123"
    assert (package / "P_1 [1 3B]" / "001.jpg").read_bytes() == b"123"
    assert not nested.exists()
    assert sorted(p.name for p in package.iterdir()) == [
        "P [200 600B]", "P_1 [1 3B]",
    ]
    again = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert again["files_moved"] == 0
    assert again["files_reconciled"] == 201


def test_mixed_uses_p_v_other_and_preserves_package_name(tmp_path):
    root, package = example(tmp_path)
    inner = package / "不规范"
    inner.mkdir()
    (inner / "photo.jpg").write_bytes(b"photo")
    (inner / "video.mp4").write_bytes(b"movie")
    (inner / "info.txt").write_bytes(b"info")
    manifest = manifest_for(root, package)
    assert [x["kind"] for x in manifest["groups"]] == ["P", "V", "Other"]
    outcome = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert outcome["files_moved"] == 3
    assert (package / "P [1 5B]" / "001.jpg").read_bytes() == b"photo"
    assert (package / "V [1 5B]" / "001.mp4").read_bytes() == b"movie"
    assert (package / "Other [1 4B]" / "info.txt").read_bytes() == b"info"
    assert not inner.exists()
    assert package.name == "SampleBundle"


def test_changed_source_fails_closed_before_move(tmp_path):
    root, package = example(tmp_path)
    nested = package / "视频A"
    nested.mkdir()
    source = nested / "001.mp4"
    source.write_bytes(b"original")
    manifest = manifest_for(root, package)
    source.write_bytes(b"modified after plan")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="changed"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert source.read_bytes() == b"modified after plan"
    assert not (package / "001.mp4").exists()


def test_stale_preview_rejected_without_mutation(tmp_path):
    root, package = example(tmp_path)
    folder = package / "nested"
    folder.mkdir()
    (folder / "001.mp4").write_bytes(b"a")
    preview = preview_media_package_package(
        package, media_package_root=root, allowed_roots=[root.parent.parent],
    )
    (folder / "002.mp4").write_bytes(b"b")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="changed"):
        executor.prepare_media_package_manifest(
            package, media_package_root=root, allowed_roots=[root.parent.parent],
            quarantine_root=None, preview_record=preview, job_id=522,
        )
    assert (folder / "001.mp4").exists()


def test_preexisting_target_cannot_be_overwritten(tmp_path):
    root, package = example(tmp_path)
    child = package / "nested"
    child.mkdir()
    (child / "001.mp4").write_bytes(b"source")
    manifest = manifest_for(root, package)
    (package / "001.mp4").write_bytes(b"untouchable")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="changed since frozen preview"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (package / "001.mp4").read_bytes() == b"untouchable"
    assert (child / "001.mp4").read_bytes() == b"source"


def test_worker_interruption_after_one_move_is_reconciled(tmp_path, monkeypatch):
    root, package = example(tmp_path)
    nested = package / "视频"
    nested.mkdir()
    for i in range(201):
        (nested / f"{i:03d}.mp4").write_bytes(b"video")
    manifest = manifest_for(root, package, job_id=523)
    original = executor.rename_noreplace_at
    calls = {"n": 0}

    def fail_after_one(src_fd, src_name, dst_fd, dst_name):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("synthetic crash")
        return original(src_fd, src_name, dst_fd, dst_name)

    monkeypatch.setattr(executor, "rename_noreplace_at", fail_after_one)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "rename_noreplace_at", original)
    # A resumed job uses the SAME immutable manifest, not a new plan.
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_reconciled"] >= 1
    assert sum(1 for group in manifest["groups"]
               for item in (package / group["final"]).iterdir()) == 201
    assert not nested.exists()


def test_foreign_entry_in_staging_is_blocked_without_moving_source(tmp_path):
    root, package = example(tmp_path)
    folder = package / "nested"
    folder.mkdir()
    for i in range(201):
        (folder / f"{i:03d}.jpg").write_bytes(b"x")
    manifest = manifest_for(root, package, job_id=524)
    stage = package / manifest["groups"][0]["stage"]
    stage.mkdir()
    (stage / "unexpected.txt").write_bytes(b"foreign")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="Foreign entry"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (folder / "000.jpg").read_bytes() == b"x"
    assert (stage / "unexpected.txt").read_bytes() == b"foreign"


def test_manifest_tampering_is_rejected(tmp_path):
    root, package = example(tmp_path)
    inner = package / "photos"
    inner.mkdir()
    (inner / "001.jpg").write_bytes(b"one")
    manifest = manifest_for(root, package)
    path = tmp_path / "manifest.json"
    executor.save_frozen_manifest(path, manifest)
    payload = path.read_text(encoding="utf-8").replace("001.jpg", "002.jpg")
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="integrity"):
        executor.load_frozen_manifest(path, job_id=521, package=package)


def test_crashed_compat_link_is_not_unlinked_automatically(tmp_path):
    root, package = example(tmp_path)
    nested = package / "nested"
    nested.mkdir()
    src = nested / "001.mp4"
    src.write_bytes(b"test")
    manifest = manifest_for(root, package)
    # Simulates two hardlinks after a crash in a COMPAT publish path.
    (package / "001.mp4").hardlink_to(src)
    with pytest.raises(executor.MediaPackageExecutionConflict, match="changed since frozen preview"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert src.exists()
    assert (package / "001.mp4").exists()


def test_crash_during_group_publication_resumes_from_frozen_stage(tmp_path, monkeypatch):
    root, package = example(tmp_path)
    nested = package / "only-videos"
    nested.mkdir()
    for i in range(201):
        (nested / f"{i:03d}.mp4").write_bytes(b"clip")
    manifest = manifest_for(root, package, job_id=531)
    original = executor.rename_noreplace_at
    failed = {"value": False}

    def crash_before_publish(src_fd, src_name, dst_fd, dst_name):
        if src_name.startswith(".nfc-media_package-stage-") and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("synthetic publish failure")
        return original(src_fd, src_name, dst_fd, dst_name)

    monkeypatch.setattr(executor, "rename_noreplace_at", crash_before_publish)
    with pytest.raises(RuntimeError, match="publish failure"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "rename_noreplace_at", original)
    assert nested.exists()  # empty dirs are not pruned before publication
    assert not (package / manifest["groups"][0]["final"]).exists()
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_reconciled"] == 201
    assert (package / manifest["groups"][0]["final"]).is_dir()
    assert (package / manifest["groups"][1]["final"]).is_dir()
    assert not nested.exists()


def _old_labelled_mixed_package(tmp_path):
    root, package = example(tmp_path)
    bucket = package / "P [2 2B]"
    bucket.mkdir()
    (bucket / "old-a.jpg").write_bytes(b"a")
    (bucket / "old-b.jpg").write_bytes(b"b")
    (package / "movie.mp4").write_bytes(b"v")
    return root, package, bucket


def test_existing_labelled_bucket_with_same_final_name_is_safely_rebuilt(tmp_path):
    root, package, bucket = _old_labelled_mixed_package(tmp_path)
    manifest = manifest_for(root, package, job_id=821)
    assert [g["final"] for g in manifest["groups"]] == [
        "P [2 2B]", "V [1 1B]",
    ]
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_moved"] == 3
    assert result["empty_dirs_removed"] >= 1
    assert (bucket / "001.jpg").read_bytes() == b"a"
    assert (bucket / "002.jpg").read_bytes() == b"b"
    assert (package / "V [1 1B]" / "001.mp4").read_bytes() == b"v"
    assert not (bucket / "old-a.jpg").exists()
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())
    replay = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert replay["files_moved"] == 0
    assert replay["files_reconciled"] == 3


def test_complete_group_is_reused_without_replacing_its_directory(tmp_path):
    root, package = example(tmp_path)
    bucket = package / "P [2 2B]"
    bucket.mkdir()
    (bucket / "001.jpg").write_bytes(b"a")
    (bucket / "002.jpg").write_bytes(b"b")
    (package / "movie.mp4").write_bytes(b"v")
    inode = bucket.stat().st_ino
    manifest = manifest_for(root, package, job_id=822)
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_moved"] == 1
    assert result["files_reconciled"] == 2
    assert bucket.stat().st_ino == inode
    assert (bucket / "001.jpg").read_bytes() == b"a"
    assert (bucket / "002.jpg").read_bytes() == b"b"
    assert (package / "V [1 1B]" / "001.mp4").read_bytes() == b"v"


def test_crash_after_first_staged_move_reconciles_old_and_staged_bucket(
    tmp_path, monkeypatch,
):
    root, package, bucket = _old_labelled_mixed_package(tmp_path)
    manifest = manifest_for(root, package, job_id=823)
    original = executor._move_one
    calls = {"count": 0}

    def crash_after_move(*args, **kwargs):
        value = original(*args, **kwargs)
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("crash with old bucket and staging both present")
        return value

    monkeypatch.setattr(executor, "_move_one", crash_after_move)
    with pytest.raises(RuntimeError, match="old bucket and staging"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "_move_one", original)
    assert bucket.exists()
    assert (bucket / "old-b.jpg").exists()
    assert (package / manifest["groups"][0]["stage"] / "001.jpg").exists()
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_reconciled"] >= 1
    assert (bucket / "001.jpg").read_bytes() == b"a"
    assert (bucket / "002.jpg").read_bytes() == b"b"
    assert (package / "V [1 1B]" / "001.mp4").read_bytes() == b"v"


def test_crash_after_retiring_old_bucket_resumes_from_frozen_stage(
    tmp_path, monkeypatch,
):
    root, package, bucket = _old_labelled_mixed_package(tmp_path)
    manifest = manifest_for(root, package, job_id=824)
    original = executor._publish_group

    def crash_before_group_publication(*args, **kwargs):
        raise RuntimeError("crash after retired old grouped destination")

    monkeypatch.setattr(executor, "_publish_group", crash_before_group_publication)
    with pytest.raises(RuntimeError, match="retired old grouped"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "_publish_group", original)
    assert not bucket.exists()
    assert (package / manifest["groups"][0]["stage"] / "001.jpg").exists()
    assert (package / manifest["groups"][1]["stage"] / "001.mp4").exists()
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_reconciled"] == 3
    assert (bucket / "001.jpg").read_bytes() == b"a"
    assert (bucket / "002.jpg").read_bytes() == b"b"
    assert (package / "V [1 1B]" / "001.mp4").read_bytes() == b"v"


def test_unplanned_file_in_old_bucket_blocks_publication_without_loss(
    tmp_path, monkeypatch,
):
    root, package, bucket = _old_labelled_mixed_package(tmp_path)
    manifest = manifest_for(root, package, job_id=825)
    original = executor._move_one

    def crash_after_first(*args, **kwargs):
        value = original(*args, **kwargs)
        raise RuntimeError("crash before other source moves")

    monkeypatch.setattr(executor, "_move_one", crash_after_first)
    with pytest.raises(RuntimeError, match="crash before"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "_move_one", original)
    (bucket / "intruder.txt").write_bytes(b"do not delete")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="not safely empty"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (bucket / "intruder.txt").read_bytes() == b"do not delete"
    assert not (bucket / "001.jpg").exists()
    assert (package / manifest["groups"][0]["stage"] / "001.jpg").read_bytes() == b"a"
    assert (package / manifest["groups"][0]["stage"] / "002.jpg").read_bytes() == b"b"


def test_external_change_in_old_bucket_is_rejected_before_staging(tmp_path):
    root, package, bucket = _old_labelled_mixed_package(tmp_path)
    manifest = manifest_for(root, package, job_id=826)
    (bucket / "new.txt").write_bytes(b"extra")
    with pytest.raises(executor.MediaPackageExecutionConflict,
                       match="changed since frozen preview"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (bucket / "old-a.jpg").read_bytes() == b"a"
    assert (bucket / "old-b.jpg").read_bytes() == b"b"
    assert (bucket / "new.txt").read_bytes() == b"extra"
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())


def test_201_video_files_regroup_without_filename_loss(tmp_path):
    root, package = example(tmp_path)
    old = package / "V [200 200B]"
    old.mkdir()
    for index in range(200):
        (old / f"{index + 1:03d}.mp4").write_bytes(bytes([index % 251]))
    (package / "new.mp4").write_bytes(b"z")
    manifest = manifest_for(root, package, job_id=827)
    assert [g["count"] for g in manifest["groups"]] == [200, 1]
    assert [g["final"] for g in manifest["groups"]] == [
        "V [200 200B]", "V_1 [1 1B]",
    ]
    executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    files = sorted(package.glob("V*/*.mp4"))
    assert len(files) == 201
    assert sorted(path.read_bytes() for path in files) == sorted(
        [bytes([index % 251]) for index in range(200)] + [b"z"]
    )
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())


def test_multigroup_crash_after_first_publish_does_not_move_reused_source(
    tmp_path, monkeypatch,
):
    root, package = example(tmp_path)
    old = package / "V [200 200B]"
    old.mkdir()
    for index in range(200):
        (old / f"{index + 1:03d}.mp4").write_bytes(bytes([index % 251]))
    (package / "new.mp4").write_bytes(b"z")
    manifest = manifest_for(root, package, job_id=828)
    publish = executor._publish_group
    calls = {"done": False}

    def crash_after_first_group(frozen, group_index, lease_fence, **kwargs):
        if group_index == 1 and not calls["done"]:
            calls["done"] = True
            raise RuntimeError("interrupted between grouped publications")
        return publish(frozen, group_index, lease_fence, **kwargs)

    monkeypatch.setattr(executor, "_publish_group", crash_after_first_group)
    with pytest.raises(RuntimeError, match="between grouped publications"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "_publish_group", publish)

    first = package / "V [200 200B]"
    second_stage = package / manifest["groups"][1]["stage"]
    assert first.is_dir()
    assert second_stage.is_dir()
    # 200.mp4 was originally the other group's source, but is now a
    # published file with a DIFFERENT frozen identity.
    assert (first / "200.mp4").read_bytes() == bytes([198])
    assert (second_stage / "001.mp4").read_bytes() == bytes([199])
    replay = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert replay["files_moved"] == 0
    assert replay["files_reconciled"] == 201
    files = sorted(package.glob("V*/*.mp4"))
    assert len(files) == 201
    assert sorted(path.read_bytes() for path in files) == sorted(
        [bytes([index % 251]) for index in range(200)] + [b"z"]
    )


def test_tampered_target_outside_package_is_rejected_before_mutation(tmp_path):
    root, package = example(tmp_path)
    nested = package / "video"
    nested.mkdir()
    (nested / "one.mp4").write_bytes(b"movie")
    manifest = manifest_for(root, package)
    manifest["moves"][0]["target"] = str(tmp_path / "outside.mp4")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="escaped"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (nested / "one.mp4").read_bytes() == b"movie"
    assert not (tmp_path / "outside.mp4").exists()


def test_new_file_after_freeze_blocks_before_mutation_or_cleanup(tmp_path):
    root, package = example(tmp_path)
    inner = package / "images"
    inner.mkdir()
    (inner / "001.jpg").write_bytes(b"pic")
    manifest = manifest_for(root, package)
    # New files anywhere inside the package invalidate the frozen snapshot.
    (inner / "user-readme.txt").write_bytes(b"preserve me")
    with pytest.raises(executor.MediaPackageExecutionConflict, match="changed since frozen preview"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (inner / "user-readme.txt").read_bytes() == b"preserve me"
    assert (inner / "001.jpg").read_bytes() == b"pic"
    assert not (package / "001.jpg").exists()


def test_symlink_parent_replacement_does_not_escape_package(tmp_path):
    root, package = example(tmp_path)
    inner = package / "gallery"
    inner.mkdir()
    (inner / "01.jpg").write_bytes(b"image")
    manifest = manifest_for(root, package)
    other = tmp_path / "other"
    other.mkdir()
    (inner / "01.jpg").rename(other / "01.jpg")
    inner.rmdir()
    inner.symlink_to(other, target_is_directory=True)
    with pytest.raises((OSError, executor.MediaPackageExecutionConflict)):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (other / "01.jpg").read_bytes() == b"image"
    assert not (package / "001.jpg").exists()


def test_existing_plain_p_and_v_are_migrated_into_count_size_folders(tmp_path):
    root, package = example(tmp_path)
    legacy_p = package / "P"
    legacy_v = package / "V"
    legacy_p.mkdir()
    legacy_v.mkdir()
    (legacy_p / "001.jpg").write_bytes(b"image")
    (legacy_v / "001.mp4").write_bytes(b"video")
    manifest = manifest_for(root, package, job_id=532)
    assert [g["final"] for g in manifest["groups"]] == [
        "P [1 5B]", "V [1 5B]",
    ]
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_moved"] == 2
    assert result["empty_dirs_removed"] == 2
    assert not legacy_p.exists()
    assert not legacy_v.exists()
    assert (package / "P [1 5B]" / "001.jpg").read_bytes() == b"image"
    assert (package / "V [1 5B]" / "001.mp4").read_bytes() == b"video"


def test_root_cycle_stages_all_files_before_publish(tmp_path):
    root, package = example(tmp_path)
    (package / "001.mp4").write_bytes(b"one")
    (package / "clips").mkdir()
    (package / "clips" / "001.mp4").write_bytes(b"two")
    manifest = manifest_for(root, package, job_id=641)
    assert len(manifest["moves"]) == 2
    assert [row["original_relative_path"] for row in manifest["moves"]] == [
        "001.mp4", "clips/001.mp4",
    ]
    assert [row["target_name"] for row in manifest["moves"]] == [
        "001.mp4", "002.mp4",
    ]
    results = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert results["files_moved"] == 2
    assert (package / "001.mp4").read_bytes() == b"one"
    assert (package / "002.mp4").read_bytes() == b"two"
    assert not (package / "clips").exists()
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())


def test_flat_publish_interrupted_after_first_file_resumes_without_overwrite(tmp_path, monkeypatch):
    root, package = example(tmp_path)
    (package / "clips").mkdir()
    (package / "clips" / "001.mp4").write_bytes(b"first")
    (package / "clips" / "002.mp4").write_bytes(b"second")
    (package / "clips" / "003.mp4").write_bytes(b"third")
    manifest = manifest_for(root, package, job_id=642)
    move = executor.rename_noreplace_at
    seen = {"count": 0}

    def fail_on_second_publish(srcfd, srcname, dstfd, dstname):
        if srcname in ("001.mp4", "002.mp4", "003.mp4") and dstname == srcname:
            seen["count"] += 1
            if seen["count"] == 5:
                raise RuntimeError("inject post-publication crash")
        return move(srcfd, srcname, dstfd, dstname)

    monkeypatch.setattr(executor, "rename_noreplace_at", fail_on_second_publish)
    with pytest.raises(RuntimeError, match="post-publication crash"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "rename_noreplace_at", move)
    again = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert again["files_reconciled"] == 3
    assert (package / "001.mp4").read_bytes() == b"first"
    assert (package / "002.mp4").read_bytes() == b"second"
    assert (package / "003.mp4").read_bytes() == b"third"
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())


def test_complete_flat_permutation_has_idempotent_restart(tmp_path):
    root, package = example(tmp_path)
    (package / "002.mp4").write_bytes(b"first")
    (package / "clips").mkdir()
    (package / "clips" / "001.mp4").write_bytes(b"second")
    manifest = manifest_for(root, package, job_id=644)
    assert [row["target_name"] for row in manifest["moves"]] == [
        "001.mp4", "002.mp4",
    ]
    outcome = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert outcome["files_moved"] == 2
    assert (package / "001.mp4").read_bytes() == b"first"
    assert (package / "002.mp4").read_bytes() == b"second"
    replay = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert replay["files_moved"] == 0
    assert replay["files_reconciled"] == 2


def test_frozen_mapping_records_every_original_and_final_path(tmp_path):
    root, package = example(tmp_path)
    (package / "A").mkdir()
    (package / "B").mkdir()
    (package / "A" / "001.mp4").write_bytes(b"movie_a")
    (package / "B" / "001.mp4").write_bytes(b"movie_b")
    manifest = manifest_for(root, package, job_id=645)
    assert len(manifest["moves"]) == 2
    assert [row["original_relative_path"] for row in manifest["moves"]] == [
        "A/001.mp4", "B/001.mp4",
    ]
    assert [row["final_relative_path"] for row in manifest["moves"]] == [
        "001.mp4", "002.mp4",
    ]
    frozen = tmp_path / "config" / "mapping.json"
    executor.save_frozen_manifest(frozen, manifest)
    copy = executor.load_frozen_manifest(frozen, job_id=645, package=package)
    assert [(row["original_relative_path"], row["final_relative_path"])
            for row in copy["moves"]] == [
        ("A/001.mp4", "001.mp4"), ("B/001.mp4", "002.mp4"),
    ]


def test_other_duplicate_names_are_suffixed_without_loss(tmp_path):
    root, package = example(tmp_path)
    (package / "A").mkdir()
    (package / "B").mkdir()
    (package / "A" / "notes.txt").write_bytes(b"note_a")
    (package / "B" / "notes.txt").write_bytes(b"note_b")
    (package / "A" / "image.jpg").write_bytes(b"img")
    manifest = manifest_for(root, package, job_id=646)
    result = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert result["files_moved"] == 3
    folder = package / "Other [2 12B]"
    assert sorted(p.name for p in folder.iterdir()) == [
        "notes.txt", "notes__dup002.txt",
    ]
    assert (folder / "notes.txt").read_bytes() == b"note_a"
    assert (folder / "notes__dup002.txt").read_bytes() == b"note_b"


def test_nas_directory_inode_drift_after_staging_uses_original_frozen_file_proof(tmp_path, monkeypatch):
    """Only trusted frozen-stage files can authorize an inode-drift publication."""
    root, package = example(tmp_path)
    nested = package / "nested"
    nested.mkdir()
    for i in range(201):
        (nested / f"{i:03d}.mp4").write_bytes(f"movie-{i}".encode())
    manifest = manifest_for(root, package, job_id=789)
    publish = executor._publish_group
    hit = {"count": 0}

    def virtual_inode_shift(frozen, index, lease_fence):
        hit["count"] += 1
        # Simulate NAS/FUSE changing the visible package directory inode
        # AFTER files were staged, while the original file IDs remain valid.
        frozen["package_ino"] = -1
        return publish(frozen, index, lease_fence)

    monkeypatch.setattr(executor, "_publish_group", virtual_inode_shift)
    outcome = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert hit["count"] == 2
    assert outcome["files_moved"] == 201
    assert (package / manifest["groups"][0]["final"] / "001.mp4").read_bytes() == b"movie-0"
    assert sorted(p.name for p in package.iterdir()) == [
        group["final"] for group in manifest["groups"]
    ]
    # The same frozen manifest remains resumable with a changed directory ID.
    again = executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert again["files_reconciled"] == 201
    assert not nested.exists()


def test_nas_inode_drift_without_stage_evidence_refuses_initial_mutation(tmp_path):
    root, package = example(tmp_path)
    nested = package / "clips"
    nested.mkdir()
    (nested / "movie.mp4").write_bytes(b"original")
    manifest = manifest_for(root, package, job_id=790)
    manifest["package_ino"] = -1
    with pytest.raises(executor.MediaPackageExecutionConflict,
                       match="without trusted frozen files"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (nested / "movie.mp4").read_bytes() == b"original"
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())


def test_nas_inode_drift_rejects_foreign_file_in_recovery_stage(tmp_path, monkeypatch):
    root, package = example(tmp_path)
    nested = package / "clips"
    nested.mkdir()
    for i in range(201):
        (nested / f"{i:03d}.jpg").write_bytes(b"x")
    manifest = manifest_for(root, package, job_id=791)
    publish = executor._publish_group

    def crash_before_publish(*args, **kwargs):
        raise RuntimeError("crash after staging")

    monkeypatch.setattr(executor, "_publish_group", crash_before_publish)
    with pytest.raises(RuntimeError, match="crash after staging"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    monkeypatch.setattr(executor, "_publish_group", publish)
    stage = package / manifest["groups"][0]["stage"]
    (stage / "foreign.txt").write_bytes(b"unexpected")
    manifest["package_ino"] = -1
    with pytest.raises(executor.MediaPackageExecutionConflict, match="Unknown"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert (stage / "foreign.txt").read_bytes() == b"unexpected"
    assert not (package / manifest["groups"][0]["final"]).exists()
