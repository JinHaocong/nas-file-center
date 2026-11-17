"""Red/green acceptance for crash-safe, no-replace publication of staged files.

All tests use synthetic temporary files. No installed NAS paths are consulted.
"""
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_stage import stage_frozen_sources
from app.batch.media_organizer_publish import (
    PublishingConflict, publish_frozen_stage,
)


def prepared(tmp_path, files):
    root = tmp_path / "work"
    root.mkdir()
    for relative, value in files.items():
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value)
    preview = preview_semantic_unit(root, allowed_roots=[tmp_path])
    assert preview["status"] == "ready", preview
    manifest = build_frozen_preview_manifest(
        root, preview_record=preview, allowed_roots=[tmp_path], job_id=920,
    )
    frozen = tmp_path / "private" / "920.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    assert all(not Path(m["source"]).exists() for m in manifest["moves"])
    return root, manifest, frozen


def publish(tmp_path, manifest, frozen, *, resume=False, lease_fence=None):
    return publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lease_fence or (lambda: None), resume=resume,
    )


def test_mixed_buckets_publish_preserving_identity_and_bytes(tmp_path):
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    result = publish(tmp_path, manifest, frozen)
    assert result["published_files"] == 2
    assert result["ready_for_retirement"] is True
    for row in manifest["moves"]:
        final = Path(row["final"])
        staged = Path(row["target"])
        assert final.is_file()
        assert final.stat().st_ino == staged.stat().st_ino
        assert final.read_bytes() == (b"image" if row["group"] == "P" else b"video")
    assert len([p for p in root.iterdir() if p.is_dir() and p.name.startswith(("P [", "V ["))]) == 2


def test_small_pure_media_flattens_and_removes_only_old_wrapper(tmp_path):
    root, manifest, frozen = prepared(
        tmp_path, {"P1/x.jpg": b"x", "P1/y.png": b"y", "z.jpg": b"z"},
    )
    result = publish(tmp_path, manifest, frozen)
    assert result["published_files"] == 3
    assert not (root / "P1").exists()
    assert (root / "001.jpg").is_file()
    assert (root / "002.png").is_file()
    assert (root / "003.jpg").is_file()
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])


def test_preexisting_source_bucket_can_be_replaced_only_after_staging(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "first.jpg").write_bytes(b"first")
    (root / "clip.mp4").write_bytes(b"clip")
    # The old wrapper and its files participate in the frozen source set.
    (root / "P").mkdir()
    (root / "P" / "second.jpg").write_bytes(b"second")
    preview = preview_semantic_unit(root, allowed_roots=[tmp_path])
    manifest = build_frozen_preview_manifest(root, preview_record=preview,
                                             allowed_roots=[tmp_path], job_id=920)
    frozen = tmp_path / "private" / "920.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    stage_frozen_sources(manifest, frozen_manifest_path=frozen,
                         allowed_roots=[tmp_path], lease_fence=lambda: None)
    publish(tmp_path, manifest, frozen)
    assert not (root / "P").exists()
    assert any(g["kind"] == "P" and (root / g["name"]).is_dir()
               for g in manifest["groups"])
    assert sorted(Path(m["final"]).read_bytes() for m in manifest["moves"] if m["group"] == "P") == [b"first", b"second"]


def test_publish_refuses_foreign_group_folder_without_touching_it(tmp_path):
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    group = root / manifest["groups"][0]["name"]
    group.mkdir()
    (group / "private.txt").write_bytes(b"foreign")
    with pytest.raises(PublishingConflict, match="foreign|untrusted|occupied"):
        publish(tmp_path, manifest, frozen)
    assert (group / "private.txt").read_bytes() == b"foreign"
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])


def test_flat_publication_refuses_foreign_file_collision(tmp_path):
    root, manifest, frozen = prepared(tmp_path, {"x.jpg": b"x", "y.jpg": b"y"})
    final = Path(manifest["moves"][0]["final"])
    final.write_bytes(b"foreign")
    with pytest.raises(PublishingConflict, match="foreign|occupied"):
        publish(tmp_path, manifest, frozen)
    assert final.read_bytes() == b"foreign"
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])


def test_partial_group_publish_resumes_from_exact_frozen_identity(tmp_path, monkeypatch):
    from app.batch import media_organizer_publish as publishing
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    actual = publishing._link_one
    called = 0

    def interrupted(*args, **kwargs):
        nonlocal called
        called += 1
        if called == 2:
            raise RuntimeError("synthetic interruption")
        return actual(*args, **kwargs)

    monkeypatch.setattr(publishing, "_link_one", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        publish(tmp_path, manifest, frozen)
    assert sum(Path(row["final"]).exists() for row in manifest["moves"]) == 1
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    monkeypatch.setattr(publishing, "_link_one", actual)
    result = publish(tmp_path, manifest, frozen, resume=True)
    assert result["published_files"] == 1
    assert result["reconciled_files"] == 1
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])


def test_resume_rejects_modified_existing_final_instead_of_adopting_it(tmp_path, monkeypatch):
    from app.batch import media_organizer_publish as publishing
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    actual = publishing._link_one
    def interrupt(*args, **kwargs):
        if Path(manifest["moves"][0]["final"]).exists():
            raise RuntimeError("interruption")
        return actual(*args, **kwargs)
    monkeypatch.setattr(publishing, "_link_one", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        publish(tmp_path, manifest, frozen)
    monkeypatch.setattr(publishing, "_link_one", actual)
    final = Path(manifest["moves"][0]["final"])
    final.unlink()
    final.write_bytes(b"changed-foreign")
    with pytest.raises(PublishingConflict, match="foreign|identity|changed"):
        publish(tmp_path, manifest, frozen, resume=True)
    assert final.read_bytes() == b"changed-foreign"


def test_resume_requires_owner_witness_on_existing_bucket(tmp_path):
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    first = root / manifest["groups"][0]["name"]
    first.mkdir()
    with pytest.raises(PublishingConflict, match="owner|foreign|witness"):
        publish(tmp_path, manifest, frozen, resume=True)
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])


def test_corrupt_stage_file_blocks_before_creating_public_targets(tmp_path):
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    Path(manifest["moves"][0]["target"]).write_bytes(b"modified")
    with pytest.raises(PublishingConflict, match="identity|stage|changed"):
        publish(tmp_path, manifest, frozen)
    assert not any(Path(row["final"]).exists() for row in manifest["moves"])


def test_published_work_is_noop_on_repeat_resume(tmp_path):
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    publish(tmp_path, manifest, frozen)
    result = publish(tmp_path, manifest, frozen, resume=True)
    assert result["published_files"] == 0
    assert result["reconciled_files"] == len(manifest["moves"])


def test_lease_loss_before_publication_preserves_all_staged_files(tmp_path):
    root, manifest, frozen = prepared(
        tmp_path, {"a.jpg": b"image", "b.mp4": b"video"},
    )
    def deny():
        raise RuntimeError("lease lost")
    with pytest.raises(RuntimeError, match="lease lost"):
        publish(tmp_path, manifest, frozen, lease_fence=deny)
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert not any(Path(row["final"]).exists() for row in manifest["moves"])
