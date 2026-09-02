from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Iterable

from app.path_safety import require_allowed_path


def build_group_command(
    *,
    binary: str,
    roots: Iterable[Path | str],
    allowed_roots: Iterable[Path | str],
    isolate: bool = False,
    min_size: str | None = None,
    threads: str | None = None,
    name_patterns: Iterable[str] | None = None,
    exclude_patterns: Iterable[str] | None = None,
) -> list[str]:
    safe_roots = [require_allowed_path(root, allowed_roots) for root in roots]
    if not safe_roots:
        raise ValueError("At least one scan root is required")
    if isolate and len(safe_roots) < 2:
        raise ValueError("Isolate mode requires at least two roots")

    cmd = [binary, "group", "--cache", "--format", "json", "--no-ignore", "--hidden"]
    if isolate:
        cmd.append("--isolate")
    if min_size:
        cmd.extend(["--min-size", min_size])
    if threads:
        cmd.extend(["--threads", threads])
    for pattern in name_patterns or ():
        cmd.extend(["--name", pattern])
    for pattern in exclude_patterns or ():
        cmd.extend(["--exclude", pattern])
    cmd.extend(str(root) for root in safe_roots)
    return cmd


def run_scan(
    command: list[str],
    *,
    report_path: Path | str,
    home_dir: Path | str,
) -> subprocess.CompletedProcess[str]:
    report_path = Path(report_path)
    partial = report_path.with_suffix(report_path.suffix + ".partial")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    home_dir = Path(home_dir)
    home_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    with partial.open("w", encoding="utf-8", newline="") as out:
        completed = subprocess.run(
            command,
            stdout=out,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            check=False,
            shell=False,
        )
    if completed.returncode == 0:
        partial.replace(report_path)
    return completed
