from pathlib import Path

from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_reports import compact_preview_record, read_preview_page


def test_large_unit_preview_is_bounded_to_sample_and_preserves_counts(tmp_path):
    root = tmp_path/'work'
    root.mkdir()
    for i in range(30):
        (root/f'file{i:02d}.jpg').write_bytes(b'x')
    row=preview_semantic_unit(root,allowed_roots=[tmp_path])
    result=compact_preview_record(row, max_items=3)
    assert result['unit']==str(root)
    assert result['status']=='ready'
    assert result['total_proposals']==30
    assert len(result['sample_moves'])==3
    assert result['truncated'] is True
    assert 'items' not in result
    assert all('identity' not in item for item in result['sample_moves'])
    assert all((root/f'file{i:02d}.jpg').exists() for i in range(30))


def test_already_organized_record_does_not_claim_moves(tmp_path):
    root=tmp_path/'work'
    root.mkdir()
    (root/'001.jpg').write_bytes(b'x')
    row=preview_semantic_unit(root,allowed_roots=[tmp_path])
    record=compact_preview_record(row,max_items=10)
    assert record['status']=='already_organized'
    assert record['needed_moves']==0
    assert record['sample_moves']==[]
    assert record['total_proposals']==0


def test_read_preview_page_filter_is_global_before_pagination(tmp_path):
    import json
    path=tmp_path/'data.jsonl'
    records=[{'unit':f'/work/{i}','status':'ready' if i%2==0 else 'blocked'} for i in range(10)]
    path.write_text(''.join(json.dumps(x)+'\n' for x in records))
    page,total=read_preview_page(path,page=2,page_size=2,status_filter='ready')
    assert total==5
    assert [x['unit'] for x in page]==['/work/4','/work/6']
    page,total=read_preview_page(path,page=3,page_size=4,status_filter='all')
    assert total==10
    assert [x['unit'] for x in page]==['/work/8','/work/9']


def test_invalid_pagination_and_filter_fail_closed(tmp_path):
    path=tmp_path/'data.jsonl'
    path.write_text('')
    import pytest
    with pytest.raises(ValueError):
        read_preview_page(path,page=0,page_size=1,status_filter='all')
    with pytest.raises(ValueError):
        read_preview_page(path,page=1,page_size=101,status_filter='all')
    with pytest.raises(ValueError):
        read_preview_page(path,page=1,page_size=1,status_filter='unsafe')
