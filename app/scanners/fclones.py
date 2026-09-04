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


def _terminate_process(proc: subprocess.Popen, timeout: float = 3.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        try:
            proc.kill()
            proc.wait(timeout=timeout)
        except OSError:
            pass


MAX_STDERR_BYTES: int = 16 * 1024  # 16 KB


def run_scan(
    command: list[str],
    *,
    report_path: Path | str,
    home_dir: Path | str,
    context: Any | None = None,
    poll_interval: float = 0.5,
) -> subprocess.CompletedProcess[str]:
    import time
    report_path = Path(report_path)
    partial = report_path.with_suffix(report_path.suffix + ".partial")
    stderr_partial = report_path.with_suffix(report_path.suffix + ".err.partial")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    home_dir = Path(home_dir)
    home_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    stderr_text = ""
    try:
        with partial.open("w", encoding="utf-8", newline="") as out, \
             stderr_partial.open("w+", encoding="utf-8") as err:
            proc = subprocess.Popen(
                command,
                stdout=out,
                stderr=err,
                text=True,
                env=env,
                shell=False,
            )
            try:
                while True:
                    ret = proc.poll()
                    if ret is not None:
                        break
                    if context is not None:
                        try:
                            context.checkpoint()
                        except BaseException:
                            _terminate_process(proc)
                            raise
                    time.sleep(poll_interval)
                proc.wait()
            except BaseException:
                _terminate_process(proc)
                raise

            err.flush()
            err.seek(0, os.SEEK_END)
            size = err.tell()
            read_start = max(0, size - MAX_STDERR_BYTES)
            err.seek(read_start)
            stderr_text = err.read()

        if proc.returncode == 0:
            partial.replace(report_path)
    finally:
        if stderr_partial.exists():
            try:
                stderr_partial.unlink()
            except OSError:
                pass

    return subprocess.CompletedProcess(command, proc.returncode or 0, "", stderr_text)
