import json
from pathlib import Path

from app.batch.media_organizer_scan import write_semantic_preview


def put(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'data')


def test_stream_preview_writes_only_bounded_records_and_summary(tmp_path):
    root=tmp_path/'collection'
    put(root/'NO.001'/'image.jpg')
    put(root/'NO.002'/'video.mp4')
    output=tmp_path/'preview.jsonl'
    with output.open('w') as out:
        summary=write_semantic_preview(root,allowed_roots=[tmp_path],out=out,max_items=1)
    records=[json.loads(s) for s in output.read_text().splitlines()]
    assert len(records)==2
    assert summary['unit_count']==2
    assert summary['ready_count']==2
    assert summary['file_count']==2
    assert all(len(r['sample_moves'])==1 for r in records)
    assert all('items' not in r for r in records)
    assert (root/'NO.001'/'image.jpg').exists()
    assert (root/'NO.002'/'video.mp4').exists()


def test_stream_preview_never_enters_explicit_excluded_root(tmp_path):
    root=tmp_path/'root'
    put(root/'ordinary'/'a.jpg')
    excluded=root/'archive'
    put(excluded/'private'/'b.jpg')
    output=tmp_path/'result.jsonl'
    with output.open('w') as out:
        summary=write_semantic_preview(root,allowed_roots=[tmp_path],out=out,exclude_roots=[excluded])
    assert summary['unit_count']==1
    assert str(excluded) not in output.read_text()


def test_stream_preview_cancel_callback_is_honored(tmp_path):
    import pytest
    root=tmp_path/'root'
    put(root/'work'/'a.jpg')
    output=tmp_path/'result.jsonl'
    def cancel():
        raise RuntimeError('cancelled by test')
    with output.open('w') as out:
        with pytest.raises(RuntimeError,match='cancelled by test'):
            write_semantic_preview(root,allowed_roots=[tmp_path],out=out,check_cancelled=cancel)
    assert (root/'work'/'a.jpg').read_bytes()==b'data'
