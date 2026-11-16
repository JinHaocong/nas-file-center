"""Isolated, read-only MediaPackage planner benchmark.

All inputs are created under a temporary directory; no production NAS paths
are accessed. Timing is informational, never a nondeterministic CI gate.
Run: PYTHONPATH=. python benchmarks/media_package_preview_benchmark.py --packages 16
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from app.batch.media_package_organizer import iter_media_package_previews


def run(packages: int, images: int, videos: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="media_package-preview-bench-") as temp:
        root = Path(temp) / "data" / "Else" / "Collection"
        for index in range(packages):
            package = root / "2611" / "261115" / f"Author{index:04d}" / "New1GB"
            pic = package / "图包"
            vid = package / "视频"
            pic.mkdir(parents=True)
            vid.mkdir()
            for count in range(images):
                (pic / f"{count:04d}.jpg").touch()
            for count in range(videos):
                (vid / f"{count:04d}.mp4").touch()
        tracemalloc.start()
        start = time.perf_counter()
        summaries = 0
        scanned = 0
        expected = packages * (images + videos)
        for result in iter_media_package_previews(
            root, media_package_root=root, allowed_roots=[root.parent.parent],
            max_rows=10,
        ):
            summaries += 1
            scanned += result["total_files"]
        elapsed = time.perf_counter() - start
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if scanned != expected or summaries != packages:
            raise AssertionError(
                f"Scan lost files/packages: {scanned}/{expected}, {summaries}/{packages}"
            )
        return {
            "synthetic_only": True,
            "packages": packages,
            "files": scanned,
            "seconds": round(elapsed, 4),
            "files_per_second": round(scanned / max(elapsed, 1e-9), 2),
            "peak_python_heap_mib": round(peak / 1024**2, 3),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packages", type=int, default=16)
    parser.add_argument("--images", type=int, default=80)
    parser.add_argument("--videos", type=int, default=40)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()
    if not 1 <= args.packages <= 100 or not 0 <= args.images <= 500 or not 0 <= args.videos <= 500:
        parser.error("Invalid bounded synthetic benchmark size")
    results = run(args.packages, args.images, args.videos)
    output = json.dumps(results, indent=2, ensure_ascii=False)
    print(output)
    if args.json:
        Path(args.json).write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
