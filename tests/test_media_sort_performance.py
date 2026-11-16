"""Deterministic performance-regression and safety tests for P/V media sorting.

Assertions target eliminated work (stat counts, SQL batches, mkdir counts),
not wall-clock thresholds that fluctuate across CI runners.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from collections import Counter

import pytest
from sqlalchemy import event, func, select

from app.batch import media_sort
from app.batch.media_sort import preview_media_sort
from app.batch.media_sort_bulk_plan import (
    INSERT_BATCH_SIZE, create_media_sort_bulk_plan,
)
from app.batch.plans import OperationItem
from app.config import Settings
from app.execution.executor import execute_item
from app.models import BatchPlan, BatchPlanItem
from app.service import FileCenterService


def _settings(tmp_path: Path) -> Settings:
    root = tmp_path / "data"
    root.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    return Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=True, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )


def _preview_file(settings: Settings, tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "proposals.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for item in rows:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


def _summary(root: Path, count: int) -> dict:
    return {
        "count": count, "conflict_count": 0,
        "parent": str(root), "recursive": True, "smart_skip": True,
    }


def test_scandir_avoids_explicit_stat_for_unrelated_files(tmp_path, monkeypatch):
    root = tmp_path / "mixed"
    root.mkdir()
    for index in range(90):
        (root / f"irrelevant-{index}.txt").write_bytes(b"x")
    (root / "image.jpg").write_bytes(b"picture")
    (root / "movie.mp4").write_bytes(b"video")
    (root / "link.jpg").symlink_to(root / "image.jpg")

    original_scandir = os.scandir
    explicit_stats: Counter[str] = Counter()

    class Entry:
        def __init__(self, inner):
            self.inner = inner
            self.name = inner.name

        def is_dir(self, *, follow_symlinks=True):
            return self.inner.is_dir(follow_symlinks=follow_symlinks)

        def is_file(self, *, follow_symlinks=True):
            return self.inner.is_file(follow_symlinks=follow_symlinks)

        def stat(self, *, follow_symlinks=True):
            explicit_stats[self.name] += 1
            return self.inner.stat(follow_symlinks=follow_symlinks)

    class Directory:
        def __init__(self, fd):
            self.inner = original_scandir(fd)

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __iter__(self):
            return (Entry(entry) for entry in self.inner)

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

    monkeypatch.setattr(media_sort.os, "scandir", Directory)
    result = preview_media_sort(root, allowed_roots=[root], smart_skip=False)
    assert result["count"] == 2
    assert not any(name.startswith("irrelevant") for name in explicit_stats)
    assert explicit_stats["image.jpg"] == 1
    assert explicit_stats["movie.mp4"] == 1
    assert explicit_stats["link.jpg"] == 0
    assert not (root / "P").exists()


def test_bulk_plan_uses_bounded_executemany_and_matches_standard_plan(tmp_path):
    settings = _settings(tmp_path)
    root = settings.data_mount
    album = root / "album"
    album.mkdir()
    for i in range(150):
        (root / f"photo-{i:04}.jpg").write_bytes(b"image")
        (root / f"movie-{i:04}.mp4").write_bytes(b"movie")
    (album / "nested.jpg").write_bytes(b"pic")
    (album / "nested.mp4").write_bytes(b"movie")
    service = FileCenterService(settings)
    preview = preview_media_sort(
        root, recursive=True, smart_skip=False,
        allowed_roots=settings.allowed_roots, quarantine_root=settings.quarantine_root,
    )
    rows = preview["items"]
    assert len(rows) == 302
    payload = _preview_file(settings, tmp_path, rows)
    statements: list[bool] = []

    def observe(_conn, _cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into batch_plan_items"):
            statements.append(bool(executemany))

    event.listen(service.engine, "before_cursor_execute", observe)
    try:
        optimized = create_media_sort_bulk_plan(
            service.SessionLocal, settings, items_file=payload,
            summary=_summary(root, len(rows)), preview_job_id=1001,
        )
    finally:
        event.remove(service.engine, "before_cursor_execute", observe)
    assert optimized.status == "draft"
    assert optimized.expected_changes == len(rows)
    assert len(statements) <= (len(rows) + INSERT_BATCH_SIZE - 1) // INSERT_BATCH_SIZE + 1
    assert statements and all(statements)

    standard = service.create_plan(
        name="Reference Move Plan", kind="media-sort",
        items=[{
            "operation": "move", "source": row["source"],
            "target": row["target"], "expected_size": row["expected_size"],
        } for row in rows],
    )
    with service.SessionLocal() as session:
        optimized_rows = list(session.scalars(select(BatchPlanItem).where(
            BatchPlanItem.plan_id == optimized.id).order_by(BatchPlanItem.sequence)))
        standard_rows = list(session.scalars(select(BatchPlanItem).where(
            BatchPlanItem.plan_id == standard.id).order_by(BatchPlanItem.sequence)))
    assert len(optimized_rows) == len(standard_rows) == 302
    assert [(r.sequence, r.source_path, r.target_path, r.expected_size)
            for r in optimized_rows] == [
            (r.sequence, r.source_path, r.target_path, r.expected_size)
            for r in standard_rows]
    assert (root / "photo-0000.jpg").exists()
    assert not (root / "P").exists()


@pytest.mark.parametrize("fault", ["missing_source", "symlink_source", "wrong_kind",
                                     "outside_root", "duplicate_target", "count_mismatch"])
def test_bulk_plan_rolls_back_all_rows_on_validation_failure(tmp_path, fault):
    settings = _settings(tmp_path)
    root = settings.data_mount
    (root / "one.jpg").write_bytes(b"one")
    (root / "two.jpg").write_bytes(b"two")
    service = FileCenterService(settings)
    rows = preview_media_sort(
        root, allowed_roots=settings.allowed_roots, smart_skip=False,
    )["items"]
    assert len(rows) == 2
    if fault == "missing_source":
        (root / "one.jpg").unlink()
    elif fault == "symlink_source":
        (root / "one.jpg").unlink()
        (root / "one.jpg").symlink_to(root / "two.jpg")
    elif fault == "wrong_kind":
        rows[0]["media_kind"] = "video"
    elif fault == "outside_root":
        rows[0]["target"] = str(tmp_path / "outside" / "P" / "one.jpg")
    elif fault == "duplicate_target":
        rows[1]["target"] = rows[0]["target"]
        rows[1]["media_kind"] = rows[0]["media_kind"]
    summary = _summary(root, len(rows) + int(fault == "count_mismatch"))
    payload = _preview_file(settings, tmp_path, rows)
    with pytest.raises(ValueError):
        create_media_sort_bulk_plan(
            service.SessionLocal, settings, items_file=payload,
            summary=summary, preview_job_id=1002,
        )
    with service.SessionLocal() as session:
        assert (session.scalar(select(func.count(BatchPlan.id))) or 0) == 0
        assert (session.scalar(select(func.count(BatchPlanItem.id))) or 0) == 0
    assert not (root / "P").exists()
    assert not (root / "V").exists()


def _move(settings: Settings, source: Path, target: Path, cache=None):
    return execute_item(
        OperationItem(sequence=1, operation="move", source=source, target=target,
                      expected_size=len(source.read_bytes())),
        allowed_roots=settings.allowed_roots,
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=settings.quarantine_root,
        plan_id="perf-test",
        move_parent_cache=cache,
    )


def test_media_parent_cache_skips_redundant_mkdir_but_preserves_noreplace(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    root = settings.data_mount
    original_mkdir = Path.mkdir
    mkdir_calls: list[str] = []

    def counting_mkdir(self, *args, **kwargs):
        if str(self) == str(root / "P"):
            mkdir_calls.append(str(self))
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting_mkdir)
    cache: dict[str, tuple[int, int]] = {}
    for i in range(7):
        source = root / f"{i}.jpg"
        source.write_bytes(b"image")
        result = _move(settings, source, root / "P" / source.name, cache)
        assert result.state == "completed", result.reason
    assert len(mkdir_calls) == 1
    assert len(list((root / "P").glob("*.jpg"))) == 7

    conflict_source = root / "same.jpg"
    conflict_source.write_bytes(b"original")
    (root / "P" / "same.jpg").write_bytes(b"destination")
    result = _move(settings, conflict_source, root / "P" / "same.jpg", cache)
    assert result.state != "completed"
    assert conflict_source.read_bytes() == b"original"
    assert (root / "P" / "same.jpg").read_bytes() == b"destination"


def test_media_parent_cache_detects_directory_replacement(tmp_path):
    settings = _settings(tmp_path)
    root = settings.data_mount
    cache: dict[str, tuple[int, int]] = {}
    first = root / "a.jpg"
    first.write_bytes(b"first")
    assert _move(settings, first, root / "P" / "a.jpg", cache).state == "completed"

    (root / "P").rename(root / "old_p")
    (root / "P").mkdir()
    second = root / "b.jpg"
    second.write_bytes(b"second")
    result = _move(settings, second, root / "P" / "b.jpg", cache)
    assert result.state != "completed"
    assert second.read_bytes() == b"second"
    assert not (root / "P" / "b.jpg").exists()
    assert (root / "old_p" / "a.jpg").read_bytes() == b"first"


def test_sparse_jsonl_pagination_jumps_to_nearby_offset_and_supports_legacy(tmp_path, monkeypatch):
    import app.batch.media_sort_jobs as jobs

    rows_file = tmp_path / "preview.items.jsonl"
    index_file = jobs._index_path(rows_file)
    with rows_file.open("w", encoding="utf-8") as rows, index_file.open("w", encoding="utf-8") as index:
        for number in range(1300):
            if number % jobs.PAGE_INDEX_STRIDE == 0:
                index.write(f"{number}\t{rows.tell()}\n")
            rows.write(json.dumps({"number": number, "name": "风景图片"}, ensure_ascii=False) + "\n")

    original_islice = jobs.itertools.islice
    requested_offsets: list[int] = []

    def observed_islice(iterator, start, stop):
        requested_offsets.append(start)
        return original_islice(iterator, start, stop)

    monkeypatch.setattr(jobs.itertools, "islice", observed_islice)
    page = jobs._read_page(rows_file, offset=1125, page_size=25)
    assert [item["number"] for item in page] == list(range(1125, 1150))
    assert requested_offsets[-1] < jobs.PAGE_INDEX_STRIDE

    # Older previews without sparse indexes must retain exact pagination.
    index_file.unlink()
    legacy = jobs._read_page(rows_file, offset=1125, page_size=25)
    assert legacy == page
    assert requested_offsets[-1] == 1125

    index_file.write_text("malformed-index\n", encoding="utf-8")
    corrupt = jobs._read_page(rows_file, offset=1125, page_size=25)
    assert corrupt == page  # Fail-safe fallback, never wrong rows.
