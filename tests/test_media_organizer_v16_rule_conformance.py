"""V1.6 confirmed Notion rule conformance tests for generic semantic units.

All tests use disposable pytest tmp_path data. They assert the read-only target
manifest only; they do not authorize or perform any filesystem mutation.
"""
from pathlib import Path

from app.batch.media_organizer_planner import preview_semantic_unit


def put(path: Path, payload: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload if payload is not None else path.name.encode("utf-8"))


def preview(root: Path) -> dict:
    return preview_semantic_unit(root, allowed_roots=[root.parent])


def test_401_pictures_are_split_into_200_200_1_and_each_bucket_restarts_at_001(tmp_path):
    root = tmp_path / "A3594-53"
    for index in range(401):
        put(root / "photos" / f"source-{index:03d}.JpG", f"payload-{index}".encode())

    result = preview(root)

    assert result["status"] == "ready"
    assert result["totals"] == {"P": 401, "V": 0, "Other": 0}
    assert [group["count"] for group in result["groups"]] == [200, 200, 1]
    assert [group["kind"] for group in result["groups"]] == ["P", "P", "P"]
    assert [Path(group["destination"]).name.split(" [", 1)[0]
            for group in result["groups"]] == ["P", "P_1", "P_2"]
    for group in result["groups"]:
        names = [Path(item["target"]).name for item in result["items"]
                 if Path(item["target"]).parent == Path(group["destination"])]
        assert names[0] == "001.JpG"
        assert names[-1] == f"{len(names):03d}.JpG"
    assert sum(group["bytes"] for group in result["groups"]) == sum(
        path.stat().st_size for path in (root / "photos").iterdir()
    )


def test_200_pictures_plus_one_video_uses_independent_p_and_v_buckets(tmp_path):
    root = tmp_path / "mixed"
    for index in range(200):
        put(root / "photos" / f"image-{index:03d}.png")
    put(root / "videos" / "movie.MP4")

    result = preview(root)

    assert result["totals"] == {"P": 200, "V": 1, "Other": 0}
    assert {(g["kind"], g["count"]) for g in result["groups"]} == {
        ("P", 200), ("V", 1)
    }
    p_group = next(g for g in result["groups"] if g["kind"] == "P")
    v_group = next(g for g in result["groups"] if g["kind"] == "V")
    p_names = [Path(row["target"]).name for row in result["items"]
               if row["kind"] == "P"]
    v_names = [Path(row["target"]).name for row in result["items"]
               if row["kind"] == "V"]
    assert p_names[0] == "001.png" and p_names[-1] == "200.png"
    assert v_names == ["001.MP4"]
    assert p_group["name"].startswith("P [200 ")
    assert v_group["name"].startswith("V [1 ")


def test_root_p_p1_and_photos_wrappers_merge_into_one_numbered_p_bucket(tmp_path):
    root = tmp_path / "work"
    for index in range(10):
        put(root / f"root-{index:02d}.jpg")
    for index in range(80):
        put(root / "P" / (f"duplicate-{index:02d}.jpg" if index else "001.jpg"))
    for index in range(40):
        put(root / "P1" / (f"duplicate-{index:02d}.jpg" if index else "001.jpg"))
    for index in range(30):
        put(root / "photos" / (f"duplicate-{index:02d}.jpg" if index else "001.jpg"))
    for index in range(5):
        put(root / "V" / f"video-{index:02d}.mp4")

    result = preview(root)

    assert result["totals"] == {"P": 160, "V": 5, "Other": 0}
    assert {(g["kind"], g["count"]) for g in result["groups"]} == {
        ("P", 160), ("V", 5)
    }
    p_rows = [row for row in result["items"] if row["kind"] == "P"]
    v_rows = [row for row in result["items"] if row["kind"] == "V"]
    assert sorted(Path(row["target"]).name for row in p_rows) == [
        f"{index:03d}.jpg" for index in range(1, 161)
    ]
    assert sorted(Path(row["target"]).name for row in v_rows) == [
        f"{index:03d}.mp4" for index in range(1, 6)
    ]
    assert len({row["target"] for row in p_rows}) == 160


def test_last_extension_classification_and_original_extension_case_are_preserved(tmp_path):
    root = tmp_path / "double-extensions"
    for name in ("video.mp4.png", "photo.jpg.mp4", "cover.WEBP", "clip.MP4", "captions.srt"):
        put(root / name)

    result = preview(root)

    assert result["totals"] == {"P": 2, "V": 2, "Other": 1}
    assert {row["target_name"] for row in result["items"] if row["kind"] == "P"} == {
        "001.WEBP", "002.png"
    }
    assert {row["target_name"] for row in result["items"] if row["kind"] == "V"} == {
        "001.MP4", "002.mp4"
    }
    other = next(row for row in result["items"] if row["kind"] == "Other")
    assert other["target_name"] == "captions.srt"
    assert Path(other["target"]).parent.name.startswith("Other [1 ")


def test_same_media_basename_across_historical_wrappers_is_never_deduplicated(tmp_path):
    root = tmp_path / "duplicate-names"
    put(root / "P" / "001.jpg", b"root-P")
    put(root / "P1" / "001.jpg", b"old-P1")
    put(root / "photos" / "001.jpg", b"old-photos")

    result = preview(root)

    assert result["totals"] == {"P": 3, "V": 0, "Other": 0}
    assert len(result["items"]) == 3
    assert {Path(row["target"]).name for row in result["items"]} == {
        "001.jpg", "002.jpg", "003.jpg"
    }
    assert {row["bytes"] for row in result["items"]} == {
        len(b"root-P"), len(b"old-P1"), len(b"old-photos")
    }
    assert len({row["source"] for row in result["items"]}) == 3
