"""Synthetic planner acceptance for canonical bucket ordinals above nine.

The expected layouts below are hand-derived. Fixture-only renames construct
the expected second-scan input; they do not exercise or authorize a Worker.
"""
from collections import Counter
import hashlib
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import preview_semantic_unit


def _put(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _preview(unit: Path) -> dict:
    return preview_semantic_unit(unit, allowed_roots=[unit.parent])


def _mapping(unit: Path, result: dict) -> dict[str, str]:
    return {
        Path(row["source"]).relative_to(unit).as_posix():
        Path(row["target"]).relative_to(unit).as_posix()
        for row in result["items"]
    }


def _contents(unit: Path) -> dict[str, bytes]:
    return {
        path.relative_to(unit).as_posix(): path.read_bytes()
        for path in unit.rglob("*") if path.is_file()
    }


def _hashes(files: dict[str, bytes]) -> Counter:
    return Counter((len(raw), hashlib.sha256(raw).hexdigest()) for raw in files.values())


@pytest.mark.parametrize("kind,extension,other", [
    ("P", ".JpG", False),
    ("V", ".Mp4", False),
    ("P", ".JpG", True),
])
def test_2201_numbered_media_keep_twelve_canonical_buckets_on_second_scan(
    tmp_path, kind, extension, other,
):
    unit = tmp_path / "synthetic-unit"
    expected = {}
    names = [f"{kind} [200 200B]"] + [
        f"{kind}_{index} [200 200B]" for index in range(1, 11)
    ] + [f"{kind}_11 [1 1B]"]
    for group_index, name in enumerate(names):
        count = 1 if group_index == 11 else 200
        for ordinal in range(1, count + 1):
            source_index = group_index * 200 + ordinal
            source = f"photos/source-{source_index:04d}{extension}"
            expected[source] = f"{name}/{ordinal:03d}{extension}"
            _put(unit / source, bytes([source_index % 256]))
    if other:
        _put(unit / "notes.txt", b"note")
        expected["notes.txt"] = "Other [1 4B]/notes.txt"
    before = _contents(unit)

    first = _preview(unit)

    assert first["status"] == "ready"
    assert _mapping(unit, first) == expected
    assert [group["name"] for group in first["groups"]] == (
        names + (["Other [1 4B]"] if other else [])
    )
    assert _contents(unit) == before

    # Build only the independently specified canonical layout for the rescan.
    for source, target in expected.items():
        (unit / target).parent.mkdir(parents=True, exist_ok=True)
        (unit / source).rename(unit / target)
    (unit / "photos").rmdir()
    canonical = _contents(unit)
    assert _hashes(canonical) == _hashes(before)

    second = _preview(unit)

    assert second["status"] == "already_organized", second["needed_moves"]
    assert second["needed_moves"] == 0
    assert second["renamed_count"] == 0
    assert second["wrapper_cleanup"] == []
    assert _mapping(unit, second) == {target: target for target in expected.values()}
    assert _contents(unit) == canonical


def test_numeric_bucket_ordinal_survives_stale_labels_and_preserves_extension_case(tmp_path):
    unit = tmp_path / "synthetic-unit"
    inputs = {
        "P_10 [999 999B]/a.JpG": b"a",
        "p_2 [888 888B]/z.JpG": b"b",
        "V_10 [999 999B]/a.Mp4": b"c",
        "v_2 [888 888B]/z.Mp4": b"d",
        "Other [999 999B]/notes.txt": b"e",
    }
    for path, payload in inputs.items():
        _put(unit / path, payload)

    result = _preview(unit)

    assert result["status"] == "ready"
    assert result["totals"] == {"P": 2, "V": 2, "Other": 1}
    assert _mapping(unit, result) == {
        "p_2 [888 888B]/z.JpG": "P [2 2B]/001.JpG",
        "P_10 [999 999B]/a.JpG": "P [2 2B]/002.JpG",
        "v_2 [888 888B]/z.Mp4": "V [2 2B]/001.Mp4",
        "V_10 [999 999B]/a.Mp4": "V [2 2B]/002.Mp4",
        "Other [999 999B]/notes.txt": "Other [1 1B]/notes.txt",
    }
    assert _contents(unit) == inputs


@pytest.mark.parametrize("wrapper,extension,kind", [
    ("P", ".Mp4", "V"),
    ("V", ".JpG", "P"),
])
def test_numeric_wrapper_order_never_overrides_actual_media_kind(
    tmp_path, wrapper, extension, kind,
):
    unit = tmp_path / "synthetic-unit"
    first = f"{wrapper}_2 [99 99B]/late{extension}"
    second = f"{wrapper}_10 [88 88B]/early{extension}"
    _put(unit / first, b"a")
    _put(unit / second, b"b")

    result = _preview(unit)

    assert result["status"] == "ready"
    assert result["totals"][kind] == 2
    assert result["totals"][wrapper] == 0
    assert result["groups"] == []
    assert _mapping(unit, result) == {
        first: f"001{extension}", second: f"002{extension}",
    }


def test_numeric_bucket_sorting_applies_inside_other_legacy_wrappers(tmp_path):
    unit = tmp_path / "synthetic-unit"
    _put(unit / "Other [9 9B]/P_10 [9 9B]/a.JPG", b"a")
    _put(unit / "Other [9 9B]/P_2 [9 9B]/z.JPG", b"b")

    result = _preview(unit)

    assert _mapping(unit, result) == {
        "Other [9 9B]/P_2 [9 9B]/z.JPG": "001.JPG",
        "Other [9 9B]/P_10 [9 9B]/a.JPG": "002.JPG",
    }


def test_ordinary_paths_keep_lexical_filename_order_and_global_case_tiebreak(tmp_path):
    unit = tmp_path / "synthetic-unit"
    inputs = {
        "image10.JpG": b"a", "image2.JpG": b"b", "P.jpg": b"c",
        "P/z.jpg": b"d", "p/a.jpg": b"e",
    }
    for path, payload in inputs.items():
        _put(unit / path, payload)

    result = _preview(unit)

    assert result["status"] == "ready"
    assert _mapping(unit, result) == {
        "image10.JpG": "001.JpG", "image2.JpG": "002.JpG",
        "P.jpg": "003.jpg", "p/a.jpg": "004.jpg", "P/z.jpg": "005.jpg",
    }
    assert _contents(unit) == inputs
