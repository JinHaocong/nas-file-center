"""Read-only operator inventory for MediaPackage preview/execution reports.

No pruning is implemented: failed execution manifests are recovery authority,
and even apparently orphaned previews require a separate operator review.
Usage:
    python -m app.batch.media_package_report_inspector inventory
    python -m app.batch.media_package_report_inspector inspect 14
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from pathlib import Path

from app.config import Settings


_PREVIEW_NAME = re.compile(r"^([1-9][0-9]*)[.]")
_EXECUTION_KIND = "media_package-package-execute"
_PREVIEW_KIND = "media_package-package-preview"


def _jobs(settings: Settings) -> dict[int, dict]:
    """Read the task ledger without opening it for writes."""
    db_uri = settings.database_path.resolve(strict=False).as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        rows = conn.execute(
            "SELECT id, kind, status, progress_current, progress_total, "
            "state_json, error_text FROM work_jobs"
        )
        result = {}
        for ident, kind, status, current, total, raw_state, error in rows:
            try:
                state = json.loads(raw_state or "{}")
            except (TypeError, ValueError):
                state = None
            result[int(ident)] = {
                "kind": kind,
                "status": status,
                "progress_current": current,
                "progress_total": total,
                "state": state,
                "error": error,
            }
        return result


def _entries(directory: Path) -> list[str]:
    if directory.is_symlink():
        raise ValueError(f"Unsafe symbolic-link report directory: {directory}")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError(f"Not a report directory: {directory}")
    with os.scandir(directory) as listing:
        return sorted(item.name for item in listing)


def inventory(settings: Settings) -> dict:
    """Classify report namespaces; never infer that an orphan is deletable."""
    jobs = _jobs(settings)
    execution_ids = {
        job_id for job_id, row in jobs.items()
        if row["kind"] == _EXECUTION_KIND
    }
    linked_preview_ids = set()
    unknown_links = False
    for ident in execution_ids:
        state = jobs[ident]["state"]
        if not isinstance(state, dict):
            unknown_links = True
            continue
        preview_id = state.get("preview_job_id")
        if isinstance(preview_id, int) and preview_id > 0:
            linked_preview_ids.add(preview_id)
        else:
            unknown_links = True

    preview_root = settings.reports_dir / "media_package-previews"
    execution_root = settings.reports_dir / "media_package-executions"
    previews: dict[int, list[str]] = {}
    for name in _entries(preview_root):
        m = _PREVIEW_NAME.match(name)
        if m:
            previews.setdefault(int(m.group(1)), []).append(name)

    preview_report_rows = []
    for ident, names in sorted(previews.items()):
        job = jobs.get(ident)
        if unknown_links:
            disposition = "retain_unknown_execution_links"
        elif ident in linked_preview_ids:
            disposition = "retain_execution_dependency"
        elif job and job["kind"] == _PREVIEW_KIND:
            disposition = "retain_preview_task"
        else:
            disposition = "review_orphan_never_auto_delete"
        preview_report_rows.append({
            "job_id": ident, "artifacts": names,
            "task_status": job["status"] if job else None,
            "disposition": disposition,
        })

    execution_report_rows = []
    for name in _entries(execution_root):
        if not name.isdecimal() or int(name) < 1:
            continue
        ident = int(name)
        job = jobs.get(ident)
        execution_report_rows.append({
            "job_id": ident,
            "task_status": job["status"] if job else None,
            "disposition": (
                "retain_execution_recovery_or_audit"
                if job and job["kind"] == _EXECUTION_KIND
                else "retain_unknown_execution_artifact"
            ),
        })

    return {
        "read_only": True,
        "auto_prune": False,
        "preview_reports": preview_report_rows,
        "execution_reports": execution_report_rows,
        "unrecognized_preview_entries": [
            n for n in _entries(preview_root) if not _PREVIEW_NAME.match(n)
        ],
        "unrecognized_execution_entries": [
            n for n in _entries(execution_root) if not n.isdecimal()
        ],
    }


def inspect_execution(settings: Settings, job_id: int, *,
                      ordinal: int | None = None) -> dict:
    """Inspect a failed/current package without altering reports or NAS data."""
    from app.batch.media_package_execution import (
        MediaPackageExecutionConflict, load_frozen_manifest,
    )

    if job_id < 1 or ordinal is not None and ordinal < 0:
        raise ValueError("Task ID and ordinal must be nonnegative integers")
    job = _jobs(settings).get(job_id)
    result = {
        "read_only": True, "job_id": job_id, "task_status": None,
        "disposition": "retain_execution_recovery_or_audit",
    }
    if not job or job["kind"] != _EXECUTION_KIND:
        result["diagnosis"] = "Execution task not found; preserve orphaned reports"
        result["report_entries"] = _entries(
            settings.reports_dir / "media_package-executions" / str(job_id)
        )
        return result

    result["task_status"] = job["status"]
    result["task_error"] = job["error"]
    state = job["state"]
    if not isinstance(state, dict) or not isinstance(state.get("preview_job_id"), int):
        result["diagnosis"] = "Missing or unreadable execution task state"
        return result
    preview_id = state["preview_job_id"]
    frozen_job_id = state.get("recovery_of_job_id")
    if not isinstance(frozen_job_id, int) or frozen_job_id < 1:
        frozen_job_id = job_id
    folder = (settings.reports_dir / "media_package-executions"
              / str(frozen_job_id))
    result["frozen_execution_job_id"] = frozen_job_id
    result["preview_job_id"] = preview_id
    if ordinal is None:
        current = int(job["progress_current"] or 0)
        ordinal = max(0, current - 1) if job["status"] == "completed" else current
    result["package_ordinal"] = ordinal

    report = (settings.reports_dir / "media_package-previews"
              / f"{preview_id}.packages.jsonl")
    result["preview_report_present"] = report.is_file() and not report.is_symlink()
    if not result["preview_report_present"]:
        result["diagnosis"] = "Original preview evidence missing; preserve all artifacts"
        return result

    record = None
    try:
        with report.open("r", encoding="utf-8") as stream:
            for position, line in enumerate(stream):
                if position == ordinal:
                    record = json.loads(line)
                    break
    except (OSError, UnicodeError, json.JSONDecodeError):
        result["diagnosis"] = "Original preview evidence is unreadable or invalid"
        return result
    if not isinstance(record, dict) or not isinstance(record.get("package"), str):
        result["diagnosis"] = "Package ordinal absent or invalid in original preview"
        return result

    package = Path(record["package"])
    manifest_file = folder / f"{ordinal:07d}.manifest.json"
    result["manifest_path"] = str(manifest_file)
    result["manifest_present"] = manifest_file.is_file() and not manifest_file.is_symlink()
    if result["manifest_present"]:
        try:
            manifest = load_frozen_manifest(
                manifest_file, job_id=frozen_job_id, package=package,
            )
            result["manifest_integrity"] = "valid"
            result["frozen_move_count"] = len(manifest.get("moves", []))
        except (MediaPackageExecutionConflict, OSError, ValueError) as exc:
            result["manifest_integrity"] = "invalid"
            result["diagnosis"] = str(exc)
    else:
        result["manifest_integrity"] = "missing_or_unsafe"

    # Only inspect the package's immediate children, never descend or mutate.
    stages = []
    try:
        with os.scandir(package) as listing:
            for entry in listing:
                if entry.name.startswith(f".nfc-media_package-stage-{frozen_job_id}-"):
                    stages.append(entry.name)
    except OSError:
        result["stage_inspection"] = "package unavailable"
    result["stage_entries"] = sorted(stages)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only MediaPackage report and recovery evidence inspector"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory", help="Classify preserved report artifacts")
    inspect = commands.add_parser("inspect", help="Check one execution's frozen manifest")
    inspect.add_argument("job_id", type=int)
    inspect.add_argument("--ordinal", type=int, default=None)
    args = parser.parse_args()
    settings = Settings()
    data = (inventory(settings) if args.command == "inventory"
            else inspect_execution(settings, args.job_id, ordinal=args.ordinal))
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
