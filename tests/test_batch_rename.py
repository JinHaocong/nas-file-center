from pathlib import Path

import pytest


def test_collect_tree_stats_counts_media_and_bytes(tmp_path):
    root = tmp_path / "set"
    (root / "sub").mkdir(parents=True)
    (root / "a.jpg").write_bytes(b"a" * 10)
    (root / "b.PNG").write_bytes(b"b" * 20)
    (root / "movie.mp4").write_bytes(b"v" * 30)
    (root / "sub" / "note.txt").write_bytes(b"n" * 40)

    from app.batch.stats import collect_tree_stats
    stats = collect_tree_stats(root)
    assert (stats.images, stats.videos, stats.files, stats.folders, stats.total_bytes) == (2, 1, 4, 1, 100)


def test_strip_repeated_stat_suffix_preserves_semantic_brackets():
    from app.batch.stats import strip_trailing_stat_suffixes
    name = "112 Album Special [5V 461.07MB] [0P 5V 461.1MB]"
    assert strip_trailing_stat_suffixes(name) == "112 Album Special"


def test_render_stat_name_supports_template_variables():
    from app.batch.stats import TreeStats, render_stat_name
    stats = TreeStats(images=40, videos=2, files=42, folders=0, total_bytes=1024**3)
    result = render_stat_name(
        "112 Album Silver [80P 2V 807.9MB]",
        stats,
        template="{name} [{images}P {videos}V {size}]",
    )
    assert result == "112 Album Silver [40P 2V 1.00 GB]"


def test_build_rename_plan_regex_prefix_numbering_and_parent(tmp_path):
    root = tmp_path / "data"
    parent = root / "Album"
    parent.mkdir(parents=True)
    a = parent / "foo 01.jpg"; b = parent / "foo 02.jpg"
    a.write_text("a"); b.write_text("b")

    from app.batch.rename import RenameRule, build_rename_plan
    proposals = build_rename_plan(
        [a, b],
        rule=RenameRule(
            regex_pattern=r"^foo ",
            regex_replacement="",
            prefix="PIC-",
            number_start=1,
            number_width=2,
            include_parent=True,
        ),
        allowed_roots=[root],
    )
    assert [p.target.name for p in proposals] == [
        "01-Album-PIC-01.jpg",
        "02-Album-PIC-02.jpg",
    ]


def test_build_rename_plan_rejects_collisions(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    a = root / "a.txt"; b = root / "b.txt"
    a.write_text("a"); b.write_text("b")
    from app.batch.rename import RenameRule, RenameCollisionError, build_rename_plan

    with pytest.raises(RenameCollisionError):
        build_rename_plan(
            [a, b],
            rule=RenameRule(regex_pattern=r"^[ab]", regex_replacement="same"),
            allowed_roots=[root],
        )
