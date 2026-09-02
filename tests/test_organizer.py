from pathlib import Path


def test_shaonv_stat_name_preserves_semantic_bracket_and_omits_zero_video():
    from app.batch.stats import TreeStats
    from app.organizers.shaonv import shaonv_stat_name

    no_video = TreeStats(images=32, videos=0, files=32, folders=0, total_bytes=3 * 1024 * 1024)
    assert shaonv_stat_name("112 少女映画 未分类[存疑] [99P 1V 2GB]", no_video) == "112 少女映画 未分类[存疑] [32P 3.0MB]"

    with_video = TreeStats(images=40, videos=2, files=42, folders=0, total_bytes=1024**3)
    assert shaonv_stat_name("112 少女映画 银狼 [80P 2V 807.9MB]", with_video) == "112 少女映画 银狼 [40P 2V 1.00GB]"


def test_build_stat_rename_proposals_recomputes_actual_contents(tmp_path):
    root = tmp_path / "少女映画"; root.mkdir()
    folder = root / "001 少女映画 A [100P 1GB] [100P 1GB]"; folder.mkdir()
    (folder / "a.jpg").write_bytes(b"a")
    (folder / "b.mp4").write_bytes(b"bb")
    from app.organizers.shaonv import build_stat_rename_proposals

    proposals = build_stat_rename_proposals(root, allowed_roots=[root])
    assert len(proposals) == 1
    assert proposals[0].target.name == "001 少女映画 A [1P 1V 0.0MB]"


def test_ordered_touch_plan_keeps_requested_root_order_and_root_last(tmp_path):
    r2 = tmp_path / "百度网盘2"; r1 = tmp_path / "百度网盘1（更新）"
    (r2 / "a").mkdir(parents=True); (r1 / "b").mkdir(parents=True)
    (r2 / "a" / "x").write_text("x"); (r1 / "b" / "y").write_text("y")
    from app.organizers.shaonv import build_ordered_touch_plan

    items = build_ordered_touch_plan([r2, r1], allowed_roots=[tmp_path])
    paths = [item.source for item in items]
    split = paths.index(r2)
    assert all(p == r2 or p.is_relative_to(r2) for p in paths[: split + 1])
    assert all(p == r1 or p.is_relative_to(r1) for p in paths[split + 1 :])
    assert paths[split] == r2
    assert paths[-1] == r1
