"""#403: semantic-preview evidence crosses distinct API/Worker UIDs safely.

Synthetic fixture proves modes and the read-only mapping contract; real
cross-UID Docker/NAS acceptance is separately required.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.batch.media_organizer_jobs import (
    MediaOrganizerPreviewHandler, report_files,
    mapping_report_root, get_media_organizer_mapping,
)


class _ReadOnlyContext:
    def checkpoint(self, **_kwargs):
        pass


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NFC_SHARED_CONFIG_GID", str(os.getegid()))
    data = tmp_path / "synthetic-data"
    work = data / "Collection" / "NO.001"
    work.mkdir(parents=True)
    for index in range(13):
        (work / f"photo-{index:03d}.JpG").write_bytes(f"synthetic-{index}".encode())
    config = tmp_path / "synthetic-config"
    config.mkdir()
    config.chmod(0o2770)
    reports = config / "reports"
    reports.mkdir()
    reports.chmod(0o2770)
    settings = SimpleNamespace(
        reports_dir=reports, allowed_roots=[data],
        quarantine_root=data / ".trash", media_package_root=None,
    )
    job = SimpleNamespace(id=431, state_json=json.dumps({"selection": str(data / "Collection")}))
    return work, settings, job


def _preview(work, settings, job):
    MediaOrganizerPreviewHandler().run(job, _ReadOnlyContext(), settings)
    data, summary = report_files(settings, job.id)
    root = mapping_report_root(settings, job.id)
    record = next(json.loads(line) for line in data.read_text(encoding="utf-8").splitlines()
                  if line and str(work) in line)
    return data, summary, root, record


def test_preview_reports_and_full_mapping_are_group_readable_not_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    work, settings, job = _fixture(tmp_path, monkeypatch)
    data, summary, mapping_root, row = _preview(work, settings, job)
    assert row["mapping_id"]
    root = data.parent
    assert (root.stat().st_mode & 0o7777) == 0o2770
    assert (mapping_root.stat().st_mode & 0o7777) == 0o2770
    for path in (data, summary, mapping_root / f"{row['mapping_id']}.jsonl"):
        assert (path.stat().st_mode & 0o777) == 0o640
        assert path.stat().st_gid == os.getegid()
    # This uses the *actual* authenticated backend reader, not a mocked parser.
    class _Session:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def get(self, _model, _job_id):
            return SimpleNamespace(kind="media-organizer-preview", status="completed")
    result = get_media_organizer_mapping(
        lambda: _Session(), settings, job.id, row["mapping_id"],
        page=2, page_size=5,
    )
    assert result["total_moves"] == 13
    assert len(result["moves"]) == 5
    assert all(item["target_name"].endswith(".JpG") for item in result["moves"])
    assert all("identity" not in item for item in result["moves"])
    assert all(f.read_bytes().startswith(b"synthetic") for f in work.iterdir())


def test_existing_private_preview_root_fails_without_permission_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    work, settings, job = _fixture(tmp_path, monkeypatch)
    old = settings.reports_dir / "media_package-previews"
    old.mkdir()
    old.chmod(0o700)
    before = old.stat().st_mode & 0o7777
    with pytest.raises((ValueError, PermissionError), match="SHARED_CONFIG|preview|trusted"):
        MediaOrganizerPreviewHandler().run(job, _ReadOnlyContext(), settings)
    assert (old.stat().st_mode & 0o7777) == before
    assert list(old.iterdir()) == []
    assert len(list(work.iterdir())) == 13


def test_group_mapping_reader_refuses_private_file_without_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    work, settings, job = _fixture(tmp_path, monkeypatch)
    _, _, root, row = _preview(work, settings, job)
    mapping = root / f"{row['mapping_id']}.jsonl"
    mapping.chmod(0o600)
    bytes_before = mapping.read_bytes()
    from app.batch.media_organizer_reports import read_preview_mapping
    with pytest.raises((ValueError, PermissionError), match="unsafe|SHARED_CONFIG|mode"):
        read_preview_mapping(root, row["mapping_id"], page=1, page_size=5)
    assert mapping.read_bytes() == bytes_before
    assert (mapping.stat().st_mode & 0o777) == 0o600


def test_existing_symlinked_preview_root_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    work, settings, job = _fixture(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign-folder"
    foreign.mkdir()
    (foreign / "foreign.txt").write_text("unchanged", encoding="utf-8")
    (settings.reports_dir / "media_package-previews").symlink_to(foreign, target_is_directory=True)
    with pytest.raises((ValueError, PermissionError)):
        MediaOrganizerPreviewHandler().run(job, _ReadOnlyContext(), settings)
    assert (foreign / "foreign.txt").read_text(encoding="utf-8") == "unchanged"
    assert len(list(foreign.iterdir())) == 1
