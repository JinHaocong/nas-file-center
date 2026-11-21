import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.batch.media_organizer_jobs import MediaOrganizerPreviewHandler, report_files


def item(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'synthetic')


class FakeContext:
    def __init__(self): self.calls=[]
    def checkpoint(self, **kwargs): self.calls.append(kwargs)


def setup(tmp_path):
    root=tmp_path/'data'
    item(root/'author'/'NO.001'/'1.jpg')
    item(root/'author'/'NO.002'/'1.mp4')
    config=tmp_path/'config'
    config.mkdir()
    settings=SimpleNamespace(reports_dir=config,allowed_roots=[root],quarantine_root=root/'.trash',media_package_root=None)
    job=SimpleNamespace(id=42,state_json=json.dumps({'selection':str(root/'author')}))
    return root,settings,job


def test_worker_run_writes_private_no_replace_report_and_does_not_modify_sources(tmp_path):
    root,settings,job=setup(tmp_path)
    ctx=FakeContext()
    MediaOrganizerPreviewHandler().run(job,ctx,settings)
    data,summary=report_files(settings,42)
    assert data.is_file() and summary.is_file()
    assert (data.stat().st_mode&0o777)==0o600
    assert (summary.stat().st_mode&0o777)==0o600
    stats=json.loads(summary.read_text())
    assert stats['unit_count']==2
    assert stats['ready_count']==2
    assert (root/'author'/'NO.001'/'1.jpg').exists()
    assert (root/'author'/'NO.002'/'1.mp4').exists()
    assert ctx.calls


def test_worker_does_not_overwrite_prior_report_artifacts(tmp_path):
    _,settings,job=setup(tmp_path)
    data,summary=report_files(settings,42)
    summary.write_text('keep me')
    with pytest.raises(ValueError, match='already exists'):
        MediaOrganizerPreviewHandler().run(job,FakeContext(),settings)
    assert summary.read_text()=='keep me'


def test_worker_refuses_selection_inside_excluded_directory_name(tmp_path):
    from app.batch.media_organizer_jobs import _validate_selection
    root, settings, job = setup(tmp_path)
    blocked = root / "author" / "PRIVATE_SOURCE" / "NO.003"
    item(blocked / "private.jpg")
    settings.media_organizer_excluded_dir_names_raw = "private_source"
    with pytest.raises(ValueError, match="excluded|protected"):
        _validate_selection(str(blocked), settings)
    assert (blocked / "private.jpg").is_file()


def test_worker_persists_and_pages_the_complete_mapping_for_a_ready_unit(tmp_path):
    from app.batch.media_organizer_jobs import (
        MediaOrganizerPreviewHandler, get_media_organizer_mapping,
        mapping_report_root, report_files,
    )
    from app.batch.media_organizer_jobs import PREVIEW_KIND

    root, settings, job = setup(tmp_path)
    work = root / "author" / "NO.003"
    for index in range(37):
        item(work / f"photo-{index:03d}.jpg")

    ctx = FakeContext()
    MediaOrganizerPreviewHandler().run(job, ctx, settings)
    data, summary = report_files(settings, int(job.id))
    records = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines()]
    record = next(row for row in records if row["unit"] == str(work))
    assert record["total_proposals"] == 37
    assert len(record["sample_moves"]) == 10
    assert record["truncated"] is True
    assert len(record["mapping_id"]) == 64

    mapping_root = mapping_report_root(settings, int(job.id))
    assert mapping_root.is_dir()
    assert mapping_root.stat().st_mode & 0o777 == 0o700
    assert (mapping_root / f"{record['mapping_id']}.jsonl").is_file()

    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def get(self, _model, _job_id):
            return SimpleNamespace(kind=PREVIEW_KIND, status="completed")

    def factory():
        return Session()

    first = get_media_organizer_mapping(
        factory, settings, int(job.id), record["mapping_id"],
        page=1, page_size=10,
    )
    second = get_media_organizer_mapping(
        factory, settings, int(job.id), record["mapping_id"],
        page=2, page_size=10,
    )
    last = get_media_organizer_mapping(
        factory, settings, int(job.id), record["mapping_id"],
        page=4, page_size=10,
    )
    assert first["total_moves"] == second["total_moves"] == last["total_moves"] == 37
    assert len(first["moves"]) == len(second["moves"]) == 10
    assert len(last["moves"]) == 7
    assert first["moves"][0]["target_name"] == "001.jpg"
    assert last["moves"][-1]["target_name"] == "037.jpg"
    assert all("identity" not in row for row in first["moves"] + last["moves"])



def test_worker_preview_does_not_require_atomic_directory_renameat2(tmp_path, monkeypatch):
    import errno
    import app.batch.media_organizer_jobs as jobs

    calls = []

    def unsupported_directory_rename(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError(errno.EOPNOTSUPP, "renameat2 unsupported by filesystem")

    # The preview publisher must not call this primitive. It creates its
    # job-scoped mapping directory exclusively and publishes the summary last.
    monkeypatch.setattr(
        jobs, "rename_noreplace_at", unsupported_directory_rename, raising=False,
    )
    root, settings, job = setup(tmp_path)
    work = root / "author" / "NO.003"
    for index in range(37):
        item(work / f"photo-{index:03d}.jpg")

    jobs.MediaOrganizerPreviewHandler().run(job, FakeContext(), settings)

    data, summary = jobs.report_files(settings, int(job.id))
    mapping_root = jobs.mapping_report_root(settings, int(job.id))
    records = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines()]
    record = next(row for row in records if row["unit"] == str(work))
    assert calls == []
    assert summary.is_file()
    assert mapping_root.is_dir()
    assert (mapping_root / f"{record['mapping_id']}.jsonl").is_file()
    assert not mapping_root.with_name(mapping_root.name + ".staging").exists()



def test_worker_refuses_preexisting_mapping_directory_without_adopting_it(tmp_path):
    from app.batch.media_organizer_jobs import mapping_report_root

    _, settings, job = setup(tmp_path)
    mapping_root = mapping_report_root(settings, int(job.id))
    mapping_root.mkdir(mode=0o700)
    sentinel = mapping_root / "foreign.jsonl"
    sentinel.write_text("preserve")

    with pytest.raises(ValueError, match="already exists"):
        MediaOrganizerPreviewHandler().run(job, FakeContext(), settings)

    assert sentinel.read_text() == "preserve"
    assert not report_files(settings, int(job.id))[1].exists()
