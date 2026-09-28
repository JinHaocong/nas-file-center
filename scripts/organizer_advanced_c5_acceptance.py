#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan
from app.worker import process_work_job

EXPECTED_ROOT_NAME = "nfc-organizer-c5-acceptance"
CONFIRMATION = "YES"


def _rules() -> dict:
    return {
        "version": 1,
        "directory_depth": {"enabled": False, "rename_from_depth": 2},
        "file_numbering": {
            "enabled": True,
            "start": 1,
            "padding": 3,
            "sort": "natural_name",
            "extension_mode": "preserve",
        },
        "latest_child_prefix": {
            "enabled": False,
            "prefix": "New ",
            "timestamp": "mtime_ns",
        },
        "single_child_wrapper_collapse": {
            "enabled": True,
            "wrapper_depth": 2,
            "child_type": "directory",
        },
    }


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
        raise RuntimeError(
            "Refusing to run without --confirm-synthetic-only YES"
        )
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
        raise RuntimeError("Refusing cleanup outside the exact project test root")
    if not resolved_run.name.startswith(".nfc-organizer-c5-"):
        raise RuntimeError("Refusing cleanup of a non-C5 acceptance directory")
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


def _data_tree(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
    )


def _plan_count(app) -> int:
    with app.state.service.SessionLocal() as session:
        return int(session.scalar(select(func.count()).select_from(BatchPlan)) or 0)


def _assert_status(response, expected: int, label: str) -> dict:
    if response.status_code != expected:
        raise RuntimeError(
            f"{label} failed: HTTP {response.status_code}: {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned non-object JSON")
    return payload


def run_acceptance(project_root: Path) -> dict:
    run_root = project_root / f".nfc-organizer-c5-{uuid4().hex}"
    run_root.mkdir(mode=0o700)
    data = run_root / "data"
    config = run_root / "config"
    data.mkdir()
    config.mkdir()
    organizer_root = data / "Organizer"
    wrapper = organizer_root / "A" / "Wrapper"
    child = wrapper / "Child"
    child.mkdir(parents=True)
    (child / "photo10.JPG").write_bytes(b"ten")
    (child / "photo2.JPG").write_bytes(b"two")

    evidence: dict = {
        "result": "FAIL",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "filesystem_type": _filesystem_type(project_root),
        "project_test_root": str(project_root),
        "run_root_name": run_root.name,
        "allow_delete": False,
        "stage_a": {},
        "stage_b": {},
        "zero_residue": False,
    }

    app = None
    try:
        settings = Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=data / ".trash",
            allow_mutation=True,
            allow_delete=False,
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
        )
        app = create_app(settings)

        with TestClient(app) as client:
            client.headers.update({"Origin": "http://testserver"})
            _assert_status(
                client.post(
                    "/api/auth/login",
                    json={
                        "username": "admin",
                        "password": "AdminPassword123!",
                    },
                ),
                200,
                "login",
            )

            profile = _assert_status(
                client.post(
                    "/api/organizer-profiles",
                    json={
                        "name": "C5 isolated NAS acceptance",
                        "root": str(organizer_root),
                        "recursive": True,
                        "rename_template": "{name}",
                        "statistics_template": "[{files}F]",
                        "advanced_rules": _rules(),
                    },
                ),
                200,
                "create organizer profile",
            )
            profile_id = int(profile["id"])

            before_preview = _data_tree(organizer_root)
            preview_a = _assert_status(
                client.post(f"/api/organizer-profiles/{profile_id}/preview"),
                200,
                "Stage A preview",
            )
            after_preview = _data_tree(organizer_root)
            if before_preview != after_preview:
                raise RuntimeError("Stage A Preview mutated the filesystem")
            if preview_a.get("advanced_enabled") is not True:
                raise RuntimeError("Stage A Preview did not report Advanced Rules enabled")
            if preview_a.get("structural_required") is not True:
                raise RuntimeError("Stage A Preview did not require structural staging")
            digest_a = str(preview_a.get("preview_digest") or "")
            if len(digest_a) != 64:
                raise RuntimeError("Stage A Preview digest is missing or malformed")
            wrapper_rows = [
                row
                for row in preview_a.get("proposals", [])
                if row.get("proposal_type") == "wrapper_collapse"
            ]
            if len(wrapper_rows) != 1:
                raise RuntimeError(
                    f"Expected exactly one wrapper candidate, got {len(wrapper_rows)}"
                )

            stage_a_plan = _assert_status(
                client.post(
                    f"/api/organizer-profiles/{profile_id}/plan",
                    json={"expected_preview_digest": digest_a},
                ),
                200,
                "Stage A plan generation",
            )
            stage_a_plan_id = int(stage_a_plan["id"])
            plan_a = _assert_status(
                client.get(f"/api/plans/{stage_a_plan_id}"),
                200,
                "read Stage A plan",
            )
            operations_a = [row["operation"] for row in plan_a.get("items", [])]
            if operations_a != ["move", "rmdir_empty"]:
                raise RuntimeError(
                    f"Stage A must be exact MOVE -> rmdir_empty, got {operations_a}"
                )

            _assert_status(
                client.post(f"/api/plans/{stage_a_plan_id}/freeze"),
                200,
                "Stage A freeze",
            )
            validation_a = _assert_status(
                client.post(f"/api/plans/{stage_a_plan_id}/validate"),
                200,
                "Stage A validate",
            )
            if validation_a.get("status") != "ready":
                raise RuntimeError(
                    f"Stage A validation was not ready: {validation_a.get('status')}"
                )
            execution_a = _assert_status(
                client.post(f"/api/plans/{stage_a_plan_id}/execute"),
                200,
                "Stage A execute",
            )
            process_work_job(settings, int(execution_a["work_job_id"]))

            completed_a = _assert_status(
                client.get(f"/api/plans/{stage_a_plan_id}"),
                200,
                "read completed Stage A plan",
            )
            if completed_a.get("status") != "completed":
                raise RuntimeError(
                    f"Stage A plan did not complete: {completed_a.get('status')}"
                )
            promoted = organizer_root / "A" / "Child"
            if wrapper.exists():
                raise RuntimeError("Wrapper still exists after completed Stage A")
            if not promoted.is_dir():
                raise RuntimeError("Promoted child is missing after Stage A")
            if (promoted / "photo10.JPG").read_bytes() != b"ten":
                raise RuntimeError("Stage A changed photo10.JPG bytes")
            if (promoted / "photo2.JPG").read_bytes() != b"two":
                raise RuntimeError("Stage A changed photo2.JPG bytes")

            count_before_stale = _plan_count(app)
            stale_generate = client.post(
                f"/api/organizer-profiles/{profile_id}/plan",
                json={"expected_preview_digest": digest_a},
            )
            if stale_generate.status_code == 200:
                raise RuntimeError("Old Stage A Preview digest generated a post-Stage-A plan")
            if _plan_count(app) != count_before_stale:
                raise RuntimeError("Stale Stage A digest persisted a draft plan")

            preview_b = _assert_status(
                client.post(f"/api/organizer-profiles/{profile_id}/preview"),
                200,
                "fresh Stage B preview",
            )
            digest_b = str(preview_b.get("preview_digest") or "")
            if len(digest_b) != 64 or digest_b == digest_a:
                raise RuntimeError("Fresh Stage B Preview digest did not change")
            if preview_b.get("structural_required") is not False:
                raise RuntimeError("Fresh Stage B Preview still requires structural staging")
            if int(preview_b.get("summary", {}).get("conflicts", 0)) != 0:
                raise RuntimeError("Fresh Stage B Preview contains blocking conflicts")

            file_rows = [
                row
                for row in preview_b.get("proposals", [])
                if row.get("proposal_type") == "file_rename" and row.get("changed")
            ]
            targets = sorted(Path(row["target"]).name for row in file_rows)
            if targets != ["001.JPG", "002.JPG"]:
                raise RuntimeError(
                    f"Unexpected Stage B file-numbering targets: {targets}"
                )

            stage_b_plan = _assert_status(
                client.post(
                    f"/api/organizer-profiles/{profile_id}/plan",
                    json={"expected_preview_digest": digest_b},
                ),
                200,
                "Stage B plan generation",
            )
            stage_b_plan_id = int(stage_b_plan["id"])
            plan_b = _assert_status(
                client.get(f"/api/plans/{stage_b_plan_id}"),
                200,
                "read Stage B plan",
            )
            operations_b = [row["operation"] for row in plan_b.get("items", [])]
            if operations_b != ["rename", "rename"]:
                raise RuntimeError(
                    f"Stage B must contain the two file renames only, got {operations_b}"
                )

            _assert_status(
                client.post(f"/api/plans/{stage_b_plan_id}/freeze"),
                200,
                "Stage B freeze",
            )
            validation_b = _assert_status(
                client.post(f"/api/plans/{stage_b_plan_id}/validate"),
                200,
                "Stage B validate",
            )
            if validation_b.get("status") != "ready":
                raise RuntimeError(
                    f"Stage B validation was not ready: {validation_b.get('status')}"
                )
            execution_b = _assert_status(
                client.post(f"/api/plans/{stage_b_plan_id}/execute"),
                200,
                "Stage B execute",
            )
            process_work_job(settings, int(execution_b["work_job_id"]))

            completed_b = _assert_status(
                client.get(f"/api/plans/{stage_b_plan_id}"),
                200,
                "read completed Stage B plan",
            )
            if completed_b.get("status") != "completed":
                raise RuntimeError(
                    f"Stage B plan did not complete: {completed_b.get('status')}"
                )
            final_names = sorted(path.name for path in promoted.iterdir())
            if final_names != ["001.JPG", "002.JPG"]:
                raise RuntimeError(f"Unexpected final Stage B tree: {final_names}")
            if (promoted / "001.JPG").read_bytes() != b"two":
                raise RuntimeError("001.JPG did not preserve photo2.JPG bytes")
            if (promoted / "002.JPG").read_bytes() != b"ten":
                raise RuntimeError("002.JPG did not preserve photo10.JPG bytes")

            evidence["stage_a"] = {
                "preview_digest": digest_a,
                "plan_id": stage_a_plan_id,
                "operations": operations_a,
                "status": completed_a.get("status"),
                "old_digest_rejected": True,
            }
            evidence["stage_b"] = {
                "preview_digest": digest_b,
                "plan_id": stage_b_plan_id,
                "operations": operations_b,
                "status": completed_b.get("status"),
                "final_names": final_names,
            }
            evidence["result"] = "PASS"
    finally:
        if app is not None:
            engine = getattr(app.state.service, "engine", None)
            if engine is not None:
                engine.dispose()
        _remove_owned_tree(run_root, project_root)
        evidence["zero_residue"] = len(list(project_root.iterdir())) == 0

    if not evidence["zero_residue"]:
        raise RuntimeError("Acceptance root is not empty after cleanup")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Organizer Advanced Rules C5 isolated filesystem acceptance. "
            "The root must be a dedicated empty directory named "
            f"{EXPECTED_ROOT_NAME!r}."
        )
    )
    parser.add_argument("--project-test-root", required=True, type=Path)
    parser.add_argument("--confirm-synthetic-only", required=True)
    parser.add_argument("--evidence-json", type=Path)
    args = parser.parse_args()

    evidence: dict
    try:
        project_root = _validate_project_test_root(
            args.project_test_root,
            args.confirm_synthetic_only,
        )
        evidence = run_acceptance(project_root)
    except Exception as exc:
        evidence = {
            "result": "FAIL",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        if args.evidence_json:
            args.evidence_json.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return 1

    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print("C5_ACCEPTANCE_RESULT=PASS")
    if args.evidence_json:
        args.evidence_json.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
