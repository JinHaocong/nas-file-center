from pathlib import Path


def test_scan_root_collects_stable_metadata_and_relative_paths(tmp_path):
    root = tmp_path / "A"
    nested = root / "x"
    nested.mkdir(parents=True)
    (nested / "a.JPG").write_bytes(b"abc")

    from app.indexing.indexer import scan_root

    entries = scan_root(root, [tmp_path], root_key="A")
    by_rel = {e.relative_path: e for e in entries}
    assert "x" in by_rel
    assert "x/a.JPG" in by_rel
    file = by_rel["x/a.JPG"]
    assert file.root_key == "A"
    assert file.basename == "a.JPG"
    assert file.stem == "a"
    assert file.suffix == ".JPG"
    assert file.size == 3
    assert file.is_dir is False
    assert file.device > 0 and file.inode > 0


def test_scan_root_does_not_follow_symlinked_directories(tmp_path):
    root = tmp_path / "A"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (root / "link").symlink_to(outside, target_is_directory=True)

    from app.indexing.indexer import scan_root

    entries = scan_root(root, [root], root_key="A")
    assert all("secret.txt" not in e.relative_path for e in entries)


def E(root, rel):
    from app.indexing.indexer import IndexedEntry
    p = Path("/data") / root / rel
    return IndexedEntry(
        root_key=root,
        absolute_path=p,
        relative_path=rel,
        basename=p.name,
        stem=p.stem,
        suffix=p.suffix,
        size=1,
        mtime_ns=1,
        device=1,
        inode=hash((root, rel)) & 0xFFFF,
        is_dir=False,
    )


def test_match_same_relative_path_across_roots():
    from app.indexing.matcher import match_entries
    entries = [E("A", "foo/a.jpg"), E("B", "foo/a.jpg"), E("B", "other.jpg")]
    groups = match_entries(entries, mode="relative-path")
    assert list(groups) == ["foo/a.jpg"]
    assert {e.root_key for e in groups["foo/a.jpg"]} == {"A", "B"}


def test_match_basename_and_regex_normalized_path():
    from app.indexing.matcher import match_entries
    entries = [
        E("A", "001 PhotoAlbum A/a.jpg"),
        E("B", "999 PhotoAlbum A/a.jpg"),
        E("B", "x/a.jpg"),
    ]
    basename = match_entries(entries, mode="basename")
    assert len(basename["a.jpg"]) == 3

    normalized = match_entries(
        entries,
        mode="normalized-relative-path",
        normalize_pattern=r"^\d{3} ",
        normalize_replacement="",
    )
    assert "PhotoAlbum A/a.jpg" in normalized
    assert len(normalized["PhotoAlbum A/a.jpg"]) == 2
