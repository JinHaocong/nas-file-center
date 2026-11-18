"""Full source→target mapping pagination required by the confirmed V1.6 rules."""
import json
import os
from pathlib import Path

from app.batch.media_organizer_scan import write_semantic_preview
from app.batch.media_organizer_reports import read_preview_mapping


def test_full_mapping_is_persisted_privately_and_paged_without_truncation(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    for index in range(37):
        (root / f"photo-{index:03d}.jpg").write_bytes(f"payload-{index}".encode())
    output = tmp_path / "preview.jsonl"
    mapping_root = tmp_path / "maps"
    mapping_root.mkdir(mode=0o700)

    with output.open("w", encoding="utf-8") as stream:
        summary = write_semantic_preview(
            root, allowed_roots=[tmp_path], out=stream,
            mapping_root=mapping_root, max_items=3,
        )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert summary["needed_moves"] == 37
    assert record["total_proposals"] == 37
    assert record["truncated"] is True
    assert len(record["sample_moves"]) == 3
    assert len(record["mapping_id"]) == 64
    mapping_file = mapping_root / f"{record['mapping_id']}.jsonl"
    assert mapping_file.is_file()
    assert mapping_file.stat().st_mode & 0o777 == 0o600

    page1, total = read_preview_mapping(
        mapping_root, record["mapping_id"], page=1, page_size=10,
    )
    page2, total2 = read_preview_mapping(
        mapping_root, record["mapping_id"], page=2, page_size=10,
    )
    page4, total4 = read_preview_mapping(
        mapping_root, record["mapping_id"], page=4, page_size=10,
    )
    assert total == total2 == total4 == 37
    assert len(page1) == len(page2) == 10
    assert len(page4) == 7
    all_rows = page1 + page2
    assert all(row["source"] and row["target"] for row in all_rows)
    assert all("identity" not in row for row in all_rows)
    assert len({row["source"] for row in page1 + page2 + page4}) == 27


def test_mapping_pagination_rejects_path_traversal_or_unknown_id(tmp_path):
    from app.batch.media_organizer_reports import read_preview_mapping
    import pytest

    root = tmp_path / "maps"
    root.mkdir(mode=0o700)
    with pytest.raises(ValueError):
        read_preview_mapping(root, "../outside", page=1, page_size=10)
    with pytest.raises(ValueError):
        read_preview_mapping(root, "a" * 64, page=0, page_size=10)
    with pytest.raises(ValueError):
        read_preview_mapping(root, "a" * 64, page=1, page_size=101)
