"""Pure naming rules: no disk I/O and no private collection identifiers."""
from app.batch.media_package_naming import allocate_names, numbered_name


def test_numbered_groups_start_again_at_one_and_preserve_extension():
    names, collisions = allocate_names(
        [{"name": "001.mp4"}, {"name": "001.MOV"}, {"name": "001.mp4"}],
        kind="V",
    )
    assert names == ["001.mp4", "002.MOV", "003.mp4"]
    assert collisions == 0
    assert numbered_name(1, "original.webp") == "001.webp"
    assert numbered_name(201, "original.avi") == "201.avi"


def test_other_duplicates_use_stable_suffix_without_clobbering_originals():
    items = [{"name": n} for n in (
        "notes.txt", "notes.TXT", "notes__dup002.txt", "notes.txt",
    )]
    result, resolved = allocate_names(items, kind="Other")
    assert result == [
        "notes.txt", "notes__dup003.TXT", "notes__dup002.txt",
        "notes__dup004.txt",
    ]
    assert resolved == 2
    assert len({v.casefold() for v in result}) == len(result)


def test_other_names_with_different_extensions_are_preserved():
    rows = [{"name": "notes.txt"}, {"name": "notes.json"}]
    assert allocate_names(rows, kind="Other") == (
        ["notes.txt", "notes.json"], 0,
    )
