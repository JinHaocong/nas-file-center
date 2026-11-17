from pathlib import Path

from app.batch.media_organizer_planner import preview_semantic_unit


def put(folder: Path, names: list[str]):
    folder.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        (folder / name).write_bytes((name + '_' + str(i)).encode())


def preview(root):
    return preview_semantic_unit(root, allowed_roots=[root.parent])


def targets(result, kind=None):
    return [Path(m['target']).relative_to(Path(result['unit'])).as_posix()
            for m in result['items'] if kind is None or m['kind'] == kind]


def test_flatten_pure_35_from_root_and_p1_without_modifying_input(tmp_path):
    root = tmp_path / 'Saber'
    put(root, [f'img_{i:02d}.jpg' for i in range(28)])
    put(root / 'P1', [f'pic_{i:02d}.jpg' for i in range(7)])
    original = [(p.relative_to(root).as_posix(), p.read_bytes())
                for p in root.rglob('*') if p.is_file()]
    result = preview(root)
    assert result['status'] == 'ready'
    assert result['operation'] == 'flatten_pure_media'
    assert result['totals'] == {'P': 35, 'V': 0, 'Other': 0}
    assert result['groups'] == []
    assert sorted(targets(result)) == [f'{i:03d}.jpg' for i in range(1, 36)]
    assert original == [(p.relative_to(root).as_posix(), p.read_bytes())
                        for p in root.rglob('*') if p.is_file()]
    assert (root/'P1').exists()


def test_already_canonical_flat_does_no_work(tmp_path):
    root = tmp_path / 'work'
    put(root, ['001.jpg', '002.jpg', '003.png'])
    result = preview(root)
    assert result['status'] == 'already_organized'
    assert result['needed_moves'] == 0
    assert result['renamed_count'] == 0


def test_exactly_200_flat_but_201_buckets(tmp_path):
    for count in (200, 201):
        root = tmp_path / f'w{count}'
        put(root / 'photos', [f'image{i:03d}.jpg' for i in range(count)])
        result = preview(root)
        assert result['totals']['P'] == count
        if count == 200:
            assert result['groups'] == []
            assert '200.jpg' in targets(result)
        else:
            assert [g['count'] for g in result['groups']] == [200, 1]
            assert result['groups'][0]['name'].startswith('P [200 ')
            assert result['groups'][1]['name'].startswith('P_1 [1 ')
            assert Path(targets(result)[200]).name == '001.jpg'


def test_mixed_media_and_last_extension(tmp_path):
    root = tmp_path / 'mixed'
    put(root, ['video.mp4', 'video.mp4.png', 'poster.webp', 'captions.srt'])
    result = preview(root)
    assert result['totals'] == {'P': 2, 'V': 1, 'Other': 1}
    assert {(g['kind'], g['count']) for g in result['groups']} == {('P', 2), ('V', 1), ('Other', 1)}
    assert sorted(m['target_name'] for m in result['items'] if m['kind'] == 'P') == ['001.webp', '002.png'] or sorted(m['target_name'] for m in result['items'] if m['kind'] == 'P') == ['001.png', '002.webp']
    assert any(m['kind']=='Other' and m['target_name']=='captions.srt' for m in result['items'])


def test_wrong_way_classification_corrected(tmp_path):
    root = tmp_path / 'swapped'
    put(root / 'P', ['a.mp4', 'b.mp4'])
    put(root / 'V', ['a.jpg', 'b.jpg', 'c.jpg'])
    result = preview(root)
    assert result['totals'] == {'P': 3, 'V': 2, 'Other': 0}
    assert sorted(g['kind'] for g in result['groups']) == ['P','V']
    assert all('P [' in m['target'] for m in result['items'] if m['kind']=='P')
    assert all('V [' in m['target'] for m in result['items'] if m['kind']=='V')


def test_semantic_child_inside_p_wrapper_is_blocker_not_flattened(tmp_path):
    root = tmp_path / 'parent'
    put(root / 'P' / 'NO.001', ['one.jpg'])
    result = preview(root)
    assert result['status'] == 'blocked'
    assert result['needed_moves'] == 0


def test_symlink_is_blocker_even_if_named_as_image(tmp_path):
    root = tmp_path / 'w'
    put(root, ['1.jpg'])
    (root/'bad.jpg').symlink_to(tmp_path/'elsewhere')
    result = preview(root)
    assert result['status'] == 'blocked'
    assert result['needed_moves'] == 0


def test_correct_existing_bucket_name_and_numbers_is_idempotent(tmp_path):
    root=tmp_path/'work'
    put(root/'P [2 10B]', ['001.jpg','002.jpg'])
    # Do not hardcode size labels that could mismatch actual byte sizes.
    from app.batch.media_package_organizer import _size_label
    size=sum(p.stat().st_size for p in (root/'P [2 10B]').iterdir())
    (root/'P [2 10B]').rename(root/f'P [2 {_size_label(size)}]')
    put(root/'V [1 1B]',['001.mp4'])
    size=(root/'V [1 1B]'/'001.mp4').stat().st_size
    (root/'V [1 1B]').rename(root/f'V [1 {_size_label(size)}]')
    result=preview(root)
    assert result['status']=='already_organized'
    assert result['needed_moves']==0


def test_existing_empty_final_bucket_is_not_claimed_as_owned_input(tmp_path):
    root = tmp_path / 'work'
    put(root, ['photo.jpg','movie.mp4'])
    size = (root/'photo.jpg').stat().st_size
    (root/f'P [1 {size}B]').mkdir()
    result = preview(root)
    assert result['status'] == 'blocked'
    assert result['needed_moves'] == 0


def test_symlink_swapped_during_wrapper_scan_fails_closed(tmp_path, monkeypatch):
    import os
    root=tmp_path/'work'
    outside=tmp_path/'outside'
    put(root/'P1',['a.jpg'])
    put(outside,['private.jpg'])
    actual=os.scandir
    original_inode=os.stat(root).st_ino
    swapped=[False]

    class Swapper:
        def __init__(self,inner):
            self.inner=inner
        def __enter__(self):
            self.inner.__enter__()
            return self.inner
        def __exit__(self,*args):
            out=self.inner.__exit__(*args)
            if not swapped[0]:
                swapped[0]=True
                (root/'P1').rename(root/'moved-P1')
                (root/'P1').symlink_to(outside, target_is_directory=True)
            return out

    def wrapped(path):
        fd_inode=os.fstat(path).st_ino if isinstance(path,int) else os.stat(path).st_ino
        ctx=actual(path)
        return Swapper(ctx) if fd_inode==original_inode and not swapped[0] else ctx

    monkeypatch.setattr(os,'scandir',wrapped)
    result=preview(root)
    assert result['status'] == 'blocked'
    assert all('private' not in m['source'] for m in result['items'])


def test_nested_wrapper_cleanup_runs_from_child_to_parent(tmp_path):
    root = tmp_path / 'work'
    put(root/'P'/'P1', ['a.jpg','b.jpg'])
    result = preview(root)
    assert result['status'] == 'ready'
    assert [Path(x).relative_to(root).as_posix() for x in result['wrapper_cleanup']] == ['P/P1', 'P']
