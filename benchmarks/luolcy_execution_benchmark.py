"""Temporary-files-only benchmark for Luolcy execution engine.

No production NAS path is accessed. This measures unleased filesystem engine
cost; Worker lease/database and real NAS storage latency are excluded.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from app.batch.luolcy_organizer import preview_luolcy_package
from app.batch.luolcy_execution import (
    execute_frozen_manifest, prepare_luolcy_manifest,
)


def run(files: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="luolcy-execute-bench-") as temp:
        root = Path(temp) / "data" / "Else" / "Luolcy"
        package = root / "2611" / "261115" / "benchmark" / "New1GB"
        nested = package / "video-source"
        nested.mkdir(parents=True)
        for number in range(files):
            (nested / f"{number:06d}.mp4").touch()

        tracemalloc.start()
        started = time.perf_counter()
        preview = preview_luolcy_package(
            package, luolcy_root=root, allowed_roots=[root.parent.parent],
        )
        manifest = prepare_luolcy_manifest(
            package, luolcy_root=root, allowed_roots=[root.parent.parent],
            quarantine_root=None, preview_record=preview, job_id=201,
        )
        planned_at = time.perf_counter()
        result = execute_frozen_manifest(manifest, lease_fence=lambda: None)
        finished_at = time.perf_counter()
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if result["files_moved"] != files:
            raise AssertionError("Synthetic benchmark did not move all files")
        if package.name != "New1GB" or nested.exists():
            raise AssertionError("Package boundary or cleanup changed unexpectedly")
        return {
            "synthetic_only": True,
            "worker_lease_sqlite_included": False,
            "files": files,
            "groups": len(manifest["groups"]),
            "plan_seconds": round(planned_at - started, 4),
            "execute_seconds": round(finished_at - planned_at, 4),
            "files_per_second": round(files / max(finished_at - planned_at, 1e-9), 2),
            "peak_python_heap_mib": round(peak / (1024 ** 2), 3),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=220)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()
    if not 1 <= args.files <= 1200:
        parser.error("Synthetic file count must be within 1..1200")
    data = run(args.files)
    output = json.dumps(data, ensure_ascii=False, indent=2)
    print(output)
    if args.json:
        Path(args.json).write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
