"""Real filesystem Luolcy move tests use only pytest temporary directories."""
from pathlib import Path

import pytest

from app.batch.luolcy_organizer import preview_luolcy_package
from app.batch import luolcy_execution as executor


def example(tmp_path):
    root = tmp_path / "data" / "Else" / "Luolcy"
    package = root / "2611" / "261115" / "疑心病" / "New 1432.1MB"
    package.mkdir(parents=True)
    return root, package


def manifest_for(root, package, job_id=521):
    roots = [root.parent.parent]
    preview = preview_luolcy_package(
        package, luolcy_root=root, allowed_roots=roots,
    )
    assert preview["status"] == "ready", preview
    manifest = executor.prepare_luolcy_manifest(
        package, luolcy_root=root, allowed_roots=roots,
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
    assert (package / "P [200 600B]" / "199.jpg").read_bytes() == b"123"
    assert (package / "P_1 [1 3B]" / "200.jpg").read_bytes() == b"123"
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
    assert (package / "P [1 5B]" / "photo.jpg").read_bytes() == b"photo"
    assert (package / "V [1 5B]" / "video.mp4").read_bytes() == b"movie"
    assert (package / "Other [1 4B]" / "info.txt").read_bytes() == b"info"
    assert not inner.exists()
    assert package.name == "New 1432.1MB"


def test_changed_source_fails_closed_before_move(tmp_path):
    root, package = example(tmp_path)
    nested = package / "视频A"
    nested.mkdir()
    source = nested / "001.mp4"
    source.write_bytes(b"original")
    manifest = manifest_for(root, package)
    source.write_bytes(b"modified after plan")
    with pytest.raises(executor.LuolcyExecutionConflict, match="changed"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert source.read_bytes() == b"modified after plan"
    assert not (package / "001.mp4").exists()


def test_stale_preview_rejected_without_mutation(tmp_path):
    root, package = example(tmp_path)
    folder = package / "nested"
    folder.mkdir()
    (folder / "001.mp4").write_bytes(b"a")
    preview = preview_luolcy_package(
        package, luolcy_root=root, allowed_roots=[root.parent.parent],
    )
    (folder / "002.mp4").write_bytes(b"b")
    with pytest.raises(executor.LuolcyExecutionConflict, match="changed"):
        executor.prepare_luolcy_manifest(
            package, luolcy_root=root, allowed_roots=[root.parent.parent],
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
    with pytest.raises(executor.LuolcyExecutionConflict, match="changed"):
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
    with pytest.raises(executor.LuolcyExecutionConflict, match="Foreign entry"):
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
    with pytest.raises(executor.LuolcyExecutionConflict, match="integrity"):
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
    with pytest.raises(executor.LuolcyExecutionConflict, match="Both source"):
        executor.execute_frozen_manifest(manifest, lease_fence=lambda: None)
    assert src.exists()
    assert (package / "001.mp4").exists()
