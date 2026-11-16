#!/usr/bin/env python3
"""Local-only, repeatable media-sort benchmark; NEVER points at a real NAS.

Runs inside an isolated TemporaryDirectory. Reports observations without
asserting brittle CI timing thresholds. Compare output across commits on the
same machine/mount. Safety/functional assertions live in pytest.
Run: PYTHONPATH=. python benchmarks/media_sort_benchmark.py --media 200 --nonmedia 1500
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time

from app.batch.media_sort import preview_media_sort
from app.batch.media_sort_bulk_plan import create_media_sort_bulk_plan
from app.config import Settings
from app.models import BatchPlanItem
from app.service import FileCenterService


def _seconds() -> float:
    return time.perf_counter()


def run_benchmark(*, media: int, nonmedia: int, directories: int, execute: bool) -> dict:
    if not (1 <= media <= 3000 and 0 <= nonmedia <= 30_000 and 1 <= directories <= 64):
        raise ValueError("Benchmark input outside bounded local-test ranges")
    with tempfile.TemporaryDirectory(prefix="nfc-media-perf-") as work:
        base = Path(work)
        root = base / "data"
        config = base / "config"
        root.mkdir()
        config.mkdir()
        albums = [root / f"album_{n:02d}" for n in range(directories)]
        for folder in albums:
            folder.mkdir()
        for index in range(media):
            album = albums[index % directories]
            (album / f"img_{index:05d}.jpg").write_bytes(b"img")
            (album / f"vid_{index:05d}.mp4").write_bytes(b"video")
        for index in range(nonmedia):
            (albums[index % directories] / f"note_{index:05d}.txt").touch()

        settings = Settings(
            _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(root),
            ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
            ALLOW_MUTATION=True, ALLOW_DELETE=False,
            INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="benchmark-password-only",
        )
        service = FileCenterService(settings)
        start = _seconds()
        preview = preview_media_sort(
            root, recursive=True, smart_skip=True,
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root,
        )
        scan_s = _seconds() - start
        rows = preview["items"]
        count = len(rows)
        if count != media * 2 or preview["conflict_count"]:
            raise AssertionError("Preview unexpectedly skipped or conflicted with media files")

        file_path = base / "validated-preview.jsonl"
        with file_path.open("w", encoding="utf-8") as dest:
            for row in rows:
                dest.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary = {k: v for k, v in preview.items() if k not in {"items", "skipped_directories"}}

        start = _seconds()
        legacy = service.create_plan(
            name="reference old ORM Plan", kind="media-sort",
            items=[{"operation": "move", "source": row["source"],
                    "target": row["target"], "expected_size": row["expected_size"]}
                   for row in rows],
        )
        legacy_s = _seconds() - start

        start = _seconds()
        faster = create_media_sort_bulk_plan(
            service.SessionLocal, settings,
            items_file=file_path, summary=summary, preview_job_id=1,
        )
        bulk_s = _seconds() - start

        from sqlalchemy import func, select
        with service.SessionLocal() as session:
            n_legacy = session.scalar(select(func.count(BatchPlanItem.id)).where(
                BatchPlanItem.plan_id == legacy.id))
            n_bulk = session.scalar(select(func.count(BatchPlanItem.id)).where(
                BatchPlanItem.plan_id == faster.id))
        if n_legacy != count or n_bulk != count:
            raise AssertionError("Batch Plan row count differs from legacy Plan")

        start = _seconds()
        service.freeze_plan(faster.id)
        freeze_s = _seconds() - start

        start = _seconds()
        validated = service.validate_plan(faster.id)
        validate_s = _seconds() - start
        if validated["status"] != "ready":
            raise AssertionError(f"Optimized Plan not ready: {validated['status']}")

        execution_s = None
        if execute:
            from app.worker import process_work_job
            start = _seconds()
            enqueued = service.enqueue_plan_execution(faster.id)
            if not process_work_job(settings, enqueued["work_job_id"]):
                raise AssertionError("Benchmark move worker failed")
            execution_s = _seconds() - start
            if service.plan_detail(faster.id)["status"] != "completed":
                raise AssertionError("Benchmark execution did not complete")

        return {
            "scope": "isolated-temp-files-only",
            "media_files": media * 2,
            "nonmedia_files": nonmedia,
            "scanned_entries": preview["scanned_entries"],
            "scanned_directories": preview["scanned_directories"],
            "plan_items": count,
            "seconds": {
                "preview": round(scan_s, 6),
                "legacy_orm_plan": round(legacy_s, 6),
                "bulk_sql_plan": round(bulk_s, 6),
                "freeze": round(freeze_s, 6),
                "validate": round(validate_s, 6),
                "execute": round(execution_s, 6) if execution_s is not None else None,
            },
            "plan_speedup_observed": round(legacy_s / bulk_s, 3) if bulk_s else None,
            "scan_entries_per_second": round(preview["scanned_entries"] / scan_s, 1) if scan_s else None,
            "note": "Timing is observational; compare on the same disk and system. "
                    "No speedup guarantee is inferred from one run.",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=int, default=120, help="image+video pairs")
    parser.add_argument("--nonmedia", type=int, default=900)
    parser.add_argument("--directories", type=int, default=6)
    parser.add_argument("--execute", action="store_true",
                        help="also execute actual moves in the isolated temporary directory")
    parser.add_argument("--json", type=Path, help="optional output JSON path")
    args = parser.parse_args()
    result = run_benchmark(media=args.media, nonmedia=args.nonmedia,
                           directories=args.directories, execute=args.execute)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
