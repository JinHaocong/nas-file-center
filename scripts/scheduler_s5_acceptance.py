#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import platform
from pathlib import Path
import subprocess
from uuid import uuid4

from sqlalchemy import func, select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import IndexRoot, ScheduleRun, User, WorkJob
from app.scheduler.dispatch import run_scheduler_tick
from app.scheduler.schema import ScheduleCreate
from app.scheduler.service import SchedulerService
from app.worker import process_work_job


EXPECTED_ROOT_NAME = "nfc-scheduler-s5-acceptance"
CONFIRMATION = "YES"
UTC = timezone.utc


def _dt(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 29, hour, minute, second, tzinfo=UTC)


def _filesystem_type(path: Path) -> str:
    try:
        proc = subprocess.run(
            ["stat", "-f", "-c", "%T", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _validate_project_test_root(path: Path, confirmation: str) -> Path:
    if confirmation != CONFIRMATION:
        raise RuntimeError("Refusing to run without --confirm-synthetic-only YES")
    if path.name != EXPECTED_ROOT_NAME:
        raise RuntimeError(
            f"Acceptance root basename must be exactly {EXPECTED_ROOT_NAME!r}"
        )
    if path.is_symlink():
        raise RuntimeError("Acceptance root must not be a symlink")
    if not path.exists() or not path.is_dir():
        raise RuntimeError("Acceptance root must already exist as a directory")
    entries = list(path.iterdir())
    if entries:
        raise RuntimeError(
            "Acceptance root must be empty before the run; found: "
            + ", ".join(sorted(entry.name for entry in entries))
        )
    return path.resolve(strict=True)


def _remove_owned_tree(run_root: Path, project_root: Path) -> None:
    resolved_project = project_root.resolve(strict=True)
    resolved_run = run_root.resolve(strict=False)
    if resolved_run.parent != resolved_project:
        raise RuntimeError("Refusing cleanup outside the exact Scheduler S5 test root")
    if not resolved_run.name.startswith(".nfc-scheduler-s5-"):
        raise RuntimeError("Refusing cleanup of a non-Scheduler-S5 directory")
    if run_root.is_symlink():
        raise RuntimeError("Refusing cleanup because run root became a symlink")
    if not run_root.exists():
        return

    for current, dirnames, filenames in os.walk(run_root, topdown=False, followlinks=False):
        current_path = Path(current)
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink() or candidate.is_file():
                candidate.unlink()
            else:
                raise RuntimeError(f"Unexpected non-file acceptance residue: {candidate}")
        for dirname in dirnames:
            candidate = current_path / dirname
            if candidate.is_symlink():
                raise RuntimeError(f"Unexpected symlink directory residue: {candidate}")
            candidate.rmdir()
    run_root.rmdir()


def _schedule_payload(name: str, target: dict) -> ScheduleCreate:
    return ScheduleCreate.model_validate(
        {
            "name": name,
            "target": target,
            "cron_expression": "* * * * *",
            "timezone": "UTC",
        }
    )


def run_acceptance(
    project_root: Path,
    *,
    execute_jobs: bool,
    candidate_sha: str,
) -> dict:
    run_root = project_root / f".nfc-scheduler-s5-{uuid4().hex}"
    run_root.mkdir(mode=0o700)
    config = run_root / "config"
    data = run_root / "data"
    index_root = data / "index"
    scan_a = data / "scan-a"
    scan_b = data / "scan-b"
    config.mkdir()
    index_root.mkdir(parents=True)
    scan_a.mkdir()
    scan_b.mkdir()

    (index_root / "indexed.txt").write_text("scheduler-index-fixture\n", encoding="utf-8")
    duplicate_payload = b"scheduler-s5-duplicate\n" * 128
    (scan_a / "duplicate.bin").write_bytes(duplicate_payload)
    (scan_b / "duplicate.bin").write_bytes(duplicate_payload)

    evidence: dict = {
        "result": "FAIL",
        "candidate_sha": candidate_sha,
        "synthetic_only": True,
        "real_nas_acceptance": False,
        "execute_jobs": execute_jobs,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "filesystem_type": _filesystem_type(project_root),
        "project_test_root": str(project_root),
        "run_root_name": run_root.name,
        "allow_mutation": False,
        "allow_delete": False,
        "dispatch": {},
        "runs": [],
        "work_jobs": [],
        "zero_residue": False,
    }

    engine = None
    try:
        settings = Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=data / ".nas-file-center-trash",
            allow_mutation=False,
            allow_delete=False,
        )
        engine, SessionLocal = create_engine_and_session(settings.database_path)
        init_db(
            engine,
            db_path=settings.database_path,
            backups_dir=settings.backups_dir,
        )

        with SessionLocal() as session:
            admin = User(
                username="scheduler-s5-admin",
                password_hash="synthetic-only",
                role="admin",
                is_active=True,
            )
            indexed_root = IndexRoot(root=str(index_root))
            session.add_all([admin, indexed_root])
            session.commit()
            admin_id = int(admin.id)
            index_root_id = int(indexed_root.id)

        scheduler = SchedulerService(SessionLocal)
        index_schedule = scheduler.create_schedule(
            admin_id,
            _schedule_payload(
                "S5 scheduled index",
                {"type": "index_root", "root_id": index_root_id},
            ),
            now_utc=_dt(12, 0, 5),
        )
        scan_schedule = scheduler.create_schedule(
            admin_id,
            _schedule_payload(
                "S5 scheduled scan",
                {
                    "type": "fclones_scan",
                    "roots": [str(scan_a), str(scan_b)],
                    "isolate": True,
                },
            ),
            now_utc=_dt(12, 0, 5),
        )

        tick = run_scheduler_tick(
            SessionLocal,
            settings,
            owner="scheduler-s5-acceptance",
            now_utc=_dt(12, 1, 5),
        )
        evidence["dispatch"] = tick.to_dict()
        if not tick.lease_acquired or tick.dispatched != 2:
            raise RuntimeError(f"Expected exactly two scheduled dispatches, got {tick.to_dict()}")

        with SessionLocal() as session:
            runs = list(session.scalars(select(ScheduleRun).order_by(ScheduleRun.id)))
            works = list(session.scalars(select(WorkJob).order_by(WorkJob.id)))
            if len(runs) != 2 or len(works) != 2:
                raise RuntimeError(
                    f"Expected two ScheduleRuns and two WorkJobs, got runs={len(runs)} jobs={len(works)}"
                )
            expected_schedule_ids = {int(index_schedule["id"]), int(scan_schedule["id"])}
            if {int(row.schedule_id) for row in runs} != expected_schedule_ids:
                raise RuntimeError("ScheduleRun rows do not match the two acceptance schedules")
            if {row.kind for row in works} != {"index-root", "fclones-scan"}:
                raise RuntimeError(f"Unexpected WorkJob kinds: {[row.kind for row in works]}")

            work_by_id = {int(row.id): row for row in works}
            for run in runs:
                if run.status != "dispatched" or run.work_job_id is None:
                    raise RuntimeError(f"ScheduleRun #{run.id} is not durably dispatched")
                work = work_by_id.get(int(run.work_job_id))
                if work is None:
                    raise RuntimeError(f"ScheduleRun #{run.id} points to a missing WorkJob")
                state = json.loads(work.state_json or "{}")
                scheduler_meta = state.get("scheduler")
                if not isinstance(scheduler_meta, dict):
                    raise RuntimeError(f"WorkJob #{work.id} is missing scheduler metadata")
                expected_slot = _dt(12, 1).isoformat()
                if (
                    scheduler_meta.get("schedule_id") != run.schedule_id
                    or scheduler_meta.get("schedule_revision") != run.schedule_revision
                    or scheduler_meta.get("schedule_run_id") != run.id
                    or scheduler_meta.get("scheduled_for_utc") != expected_slot
                ):
                    raise RuntimeError(
                        f"ScheduleRun / WorkJob linkage mismatch for run #{run.id}"
                    )

            evidence["runs"] = [
                {
                    "id": int(row.id),
                    "schedule_id": int(row.schedule_id),
                    "status": row.status,
                    "work_job_id": int(row.work_job_id) if row.work_job_id is not None else None,
                }
                for row in runs
            ]
            evidence["work_jobs"] = [
                {
                    "id": int(row.id),
                    "kind": row.kind,
                    "status": row.status,
                }
                for row in works
            ]
            work_ids = [int(row.id) for row in works]

        if execute_jobs:
            for work_id in work_ids:
                if not process_work_job(
                    settings,
                    work_id,
                    session_factory=SessionLocal,
                    engine=engine,
                ):
                    raise RuntimeError(f"WorkJob #{work_id} failed synthetic execution")

            with SessionLocal() as session:
                works = list(session.scalars(select(WorkJob).order_by(WorkJob.id)))
                if any(row.status != "completed" for row in works):
                    raise RuntimeError(
                        "Synthetic execution did not complete all WorkJobs: "
                        + ", ".join(f"#{row.id}={row.status}" for row in works)
                    )
                evidence["work_jobs"] = [
                    {
                        "id": int(row.id),
                        "kind": row.kind,
                        "status": row.status,
                    }
                    for row in works
                ]

        with SessionLocal() as session:
            destructive = int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkJob)
                    .where(
                        WorkJob.kind.in_(
                            [
                                "batch-plan-execute",
                                "quarantine-purge",
                                "quarantine-restore",
                                "organizer-execute",
                            ]
                        )
                    )
                )
                or 0
            )
            if destructive != 0:
                raise RuntimeError("Scheduler acceptance created destructive WorkJob authority")

        evidence["result"] = "PASS"
        return evidence
    finally:
        if engine is not None:
            engine.dispose()
        _remove_owned_tree(run_root, project_root)
        evidence["zero_residue"] = not any(project_root.iterdir())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scheduler S5 isolated synthetic acceptance harness"
    )
    parser.add_argument("--project-test-root", type=Path, required=True)
    parser.add_argument("--confirm-synthetic-only", required=True)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--candidate-sha", default="")
    parser.add_argument("--execute-jobs", action="store_true")
    args = parser.parse_args()

    evidence: dict = {
        "result": "FAIL",
        "synthetic_only": True,
        "real_nas_acceptance": False,
        "zero_residue": False,
    }
    try:
        root = _validate_project_test_root(
            args.project_test_root,
            args.confirm_synthetic_only,
        )
        evidence_path = args.evidence_json.resolve(strict=False)
        if evidence_path == root or evidence_path.is_relative_to(root):
            raise RuntimeError("Evidence JSON must live outside the disposable acceptance root")
        evidence = run_acceptance(
            root,
            execute_jobs=bool(args.execute_jobs),
            candidate_sha=str(args.candidate_sha or ""),
        )
        if evidence.get("result") != "PASS" or evidence.get("zero_residue") is not True:
            raise RuntimeError("Synthetic acceptance did not close with zero residue")
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    finally:
        args.evidence_json.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_json.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(main())
