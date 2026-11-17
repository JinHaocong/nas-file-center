from pathlib import Path

from app.batch.media_organizer_units import discover_semantic_units


def file(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'x')


def discover(root: Path):
    return list(discover_semantic_units(root, allowed_roots=[root.parent]))


def test_numbered_siblings_are_separate_units(tmp_path):
    root=tmp_path/'author'
    file(root/'collection'/'A100-01'/'one.jpg')
    file(root/'collection'/'A100-02'/'two.mp4')
    rows=discover(root)
    assert [Path(x['unit']).relative_to(root).as_posix() for x in rows if x['status']=='ready'] == ['collection/A100-01','collection/A100-02']
    assert all('/collection/' in x['unit'] for x in rows if x['status']=='ready')


def test_quality_versions_do_not_merge(tmp_path):
    root=tmp_path/'work'
    file(root/'4K'/'movieA.mp4')
    file(root/'PT'/'movieB.mp4')
    rows=discover(root)
    assert {Path(x['unit']).relative_to(root).as_posix() for x in rows if x['status']=='ready'} == {'4K','PT'}
    assert all(x['totals']['V']==1 for x in rows if x['status']=='ready')


def test_nested_classification_wrappers_are_one_unit(tmp_path):
    root=tmp_path/'work'
    file(root/'P'/'P1'/'a.jpg')
    rows=discover(root)
    assert len(rows)==1
    assert rows[0]['unit']==str(root)
    assert rows[0]['status']=='ready'
    assert rows[0]['totals']['P']==1


def test_p_folder_containing_real_numbered_works_is_not_flattened(tmp_path):
    root=tmp_path/'work'
    file(root/'P'/'NO.001'/'a.jpg')
    file(root/'P'/'NO.002'/'b.jpg')
    rows=discover(root)
    assert rows[0]['status']=='blocked'
    assert rows[0]['needed_moves']==0
    assert not any(x['status']=='ready' and x['unit']==str(root) for x in rows)


def test_ambiguous_numerical_wrapper_is_flagged_not_guessed(tmp_path):
    root=tmp_path/'work'
    file(root/'1'/'2'/'a.jpg')
    rows=discover(root)
    assert any(x['status']=='blocked' and 'ambiguous' in x['reason'] for x in rows)
    assert not any(x['status']=='ready' for x in rows)


def test_symlink_child_blocked_no_traversal(tmp_path):
    root=tmp_path/'work'
    file(root/'safe'/'a.jpg')
    file(tmp_path/'secret'/'private.jpg')
    (root/'shortcut').symlink_to(tmp_path/'secret',target_is_directory=True)
    rows=discover(root)
    assert any(x['status']=='blocked' for x in rows)
    assert not any('secret' in x['unit'] for x in rows)
    assert any(x['status']=='ready' and Path(x['unit']).name=='safe' for x in rows)


def test_unrelated_topic_root_is_supported(tmp_path):
    root=tmp_path/'Special Archive'
    file(root/'Collection B'/'Set 01'/'one.jpg')
    rows=discover(root)
    assert [Path(x['unit']).name for x in rows if x['status']=='ready']==['Set 01']


def test_work_subfolders_inside_legacy_media_wrapper_are_scanned_independently(tmp_path):
    root = tmp_path / 'work'
    file(root/'P'/'NO.001 Set One'/'a.jpg')
    file(root/'P'/'NO.002 Set Two'/'b.mp4')
    rows = discover(root)
    assert any(r['unit'] == str(root) and r['status'] == 'blocked' for r in rows)
    candidates = [r for r in rows if r['status'] == 'ready']
    assert {Path(r['unit']).name for r in candidates} == {'NO.001 Set One', 'NO.002 Set Two'}
    assert all(Path(r['items'][0]['target']).parent == Path(r['unit']) for r in candidates)


def test_exact_excluded_subtree_is_never_scanned(tmp_path):
    root = tmp_path/'Else'
    file(root/'ordinary'/'a.jpg')
    excluded = root/'fixed-source-archive'
    file(excluded/'secret-work'/'private.jpg')
    rows = list(discover_semantic_units(root, allowed_roots=[root.parent], exclude_roots=[excluded]))
    assert any(r['unit']==str(root/'ordinary') and r['status']=='ready' for r in rows)
    assert all(not r['unit'].startswith(str(excluded)) for r in rows)


def test_case_insensitive_excluded_directory_names_never_scan_descendants(tmp_path):
    root = tmp_path / "Else"
    file(root / "Author" / "PRIVATE_SOURCE" / "NO.001" / "hidden.jpg")
    file(root / "Author" / "Collection" / "NO.002" / "private_source_cover.jpg")
    rows = list(discover_semantic_units(
        root, allowed_roots=[tmp_path],
        exclude_dir_names=["private_source"],
    ))
    assert any(row["unit"].endswith("NO.002") and row["status"] == "ready"
               for row in rows)
    assert all("PRIVATE_SOURCE" not in row["unit"] for row in rows)
    assert all("hidden.jpg" not in str(row) for row in rows)
    assert any("private_source_cover.jpg" in str(row) for row in rows)


def test_excluded_name_matches_directory_not_an_unrelated_filename(tmp_path):
    root = tmp_path / "unit"
    file(root / "source_bundle.jpg")
    file(root / "a.mp4")
    file(root / "Source_Bundle" / "private.jpg")
    rows = list(discover_semantic_units(
        root, allowed_roots=[tmp_path],
        exclude_dir_names=["source_bundle"],
    ))
    assert all("Source_Bundle" not in row["unit"] for row in rows)
    assert any(row["unit"] == str(root) and row["status"] == "ready"
               and row["totals"] == {"P": 1, "V": 1, "Other": 0}
               for row in rows)
    assert not any("private.jpg" in str(row) for row in rows)


def test_excluded_name_invalid_path_component_is_rejected(tmp_path):
    root = tmp_path / "work"
    file(root / "a.jpg")
    rows = list(discover_semantic_units(
        root, allowed_roots=[tmp_path],
        exclude_dir_names=["../work"],
    ))
    assert rows and rows[0]["status"] == "blocked"
    assert not any(row["status"] == "ready" for row in rows)
