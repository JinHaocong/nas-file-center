import json
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_manifest import (
    FrozenPreviewError, build_frozen_preview_manifest,
    save_frozen_preview_manifest, load_frozen_preview_manifest,
)


def create(root: Path):
    root.mkdir()
    (root / 'original.jpg').write_bytes(b'image-data')
    (root / 'clip.mp4').write_bytes(b'video-data')
    return preview_semantic_unit(root, allowed_roots=[root.parent])


def test_freeze_matching_read_only_preview_carries_all_source_identifiers(tmp_path):
    root = tmp_path / 'work'
    preview = create(root)
    record = {k: v for k, v in preview.items() if k != 'items'}
    manifest = build_frozen_preview_manifest(root, preview_record=record, allowed_roots=[tmp_path], job_id=17)
    assert manifest['job_id'] == 17
    assert manifest['unit'] == str(root)
    assert manifest['input_fingerprint'] == record['input_fingerprint']
    assert len(manifest['moves']) == 2
    assert all(len(m['identity']) == 4 for m in manifest['moves'])
    assert all(Path(m['source']).exists() for m in manifest['moves'])
    assert all(not Path(m['target']).exists() for m in manifest['moves'])


def test_freeze_rejects_source_changed_after_preview(tmp_path):
    root = tmp_path / 'work'
    record = create(root)
    (root / 'original.jpg').write_bytes(b'changed')
    with pytest.raises(FrozenPreviewError, match='changed since preview'):
        build_frozen_preview_manifest(root, preview_record=record, allowed_roots=[tmp_path], job_id=18)


def test_freeze_rejects_tampered_expected_group_or_count(tmp_path):
    root = tmp_path / 'work'
    record = create(root)
    record['needed_moves'] = record['needed_moves'] + 1
    with pytest.raises(FrozenPreviewError, match='changed since preview'):
        build_frozen_preview_manifest(root, preview_record=record, allowed_roots=[tmp_path], job_id=19)


def test_freeze_rejects_new_foreign_target_occupant(tmp_path):
    root = tmp_path / 'work'
    record = create(root)
    first_group = record['groups'][0]['name']
    (root / first_group).mkdir()
    with pytest.raises(FrozenPreviewError, match='changed since preview'):
        build_frozen_preview_manifest(root, preview_record=record, allowed_roots=[tmp_path], job_id=20)


def test_freeze_never_accepts_already_organized_as_mutation(tmp_path):
    root = tmp_path / 'work'
    root.mkdir()
    (root / '001.jpg').write_bytes(b'valid')
    record = preview_semantic_unit(root, allowed_roots=[tmp_path])
    assert record['status'] == 'already_organized'
    with pytest.raises(FrozenPreviewError, match='not ready'):
        build_frozen_preview_manifest(root, preview_record=record, allowed_roots=[tmp_path], job_id=21)


def test_freeze_publication_is_exclusive_checksum_verified_and_private(tmp_path):
    root = tmp_path / 'work'
    record = create(root)
    manifest = build_frozen_preview_manifest(root, preview_record=record, allowed_roots=[tmp_path], job_id=22)
    path = tmp_path / 'private-reports' / '22.manifest.json'
    save_frozen_preview_manifest(path, manifest)
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_frozen_preview_manifest(path, job_id=22, unit=root) == manifest
    with pytest.raises(FrozenPreviewError, match='already exists'):
        save_frozen_preview_manifest(path, manifest)
    payload = json.loads(path.read_text())
    payload['manifest']['moves'][0]['target'] = str(tmp_path / 'foreign')
    path.write_text(json.dumps(payload))
    with pytest.raises(FrozenPreviewError, match='checksum'):
        load_frozen_preview_manifest(path, job_id=22, unit=root)


def test_freeze_reuses_preview_exclusion_policy_and_preflight_preserves_it(tmp_path):
    from app.batch.media_organizer_execution import validate_execution_preflight
    root = tmp_path / "synthetic-work"
    root.mkdir()
    (root / "photo.jpg").write_bytes(b"img")
    (root / "movie.mp4").write_bytes(b"vid")
    private = root / "PHOTOS"
    private.mkdir()
    (private / "hidden.jpg").write_bytes(b"private")
    preview = preview_semantic_unit(
        root, allowed_roots=[tmp_path], exclude_dir_names=["photos"],
    )
    manifest = build_frozen_preview_manifest(
        root, preview_record=preview, allowed_roots=[tmp_path],
        job_id=44, exclude_dir_names=["photos"],
    )
    assert manifest["excluded_dir_names"] == ["photos"]
    result = validate_execution_preflight(manifest, allowed_roots=[tmp_path])
    assert result["ready"] is True
    assert result["file_count"] == 2
    assert (private / "hidden.jpg").exists()
