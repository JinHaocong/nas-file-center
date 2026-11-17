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
