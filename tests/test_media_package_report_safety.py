"""MediaPackage report safety regressions: no manifest repair or implicit cleanup."""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.batch import media_package_execution as execution
from app.batch.media_package_report_inspector import inventory, inspect_execution
from app.batch.media_package_report_lifecycle import (
    _highest_report_id, next_media_package_job_id,
)
from app.config import Settings


def settings_for(tmp_path):
    return Settings(_env_file=None, CONFIG_DIR=str(tmp_path))


def test_report_artifacts_reserve_deleted_work_job_ids(tmp_path):
    settings = settings_for(tmp_path)
    previews = settings.reports_dir / "media_package-previews"
    executions = settings.reports_dir / "media_package-executions"
    previews.mkdir(parents=True)
    executions.mkdir(parents=True)
    (previews / "31.packages.jsonl").write_text("old preview")
    (previews / "34.packages.jsonl.staging").write_text("unfinished preview")
    (executions / "39").mkdir()
    (executions / "43").mkdir()
    (executions / "43" / "0000000.manifest.json").write_text("old manifest")

    class ReadOnlySession:
        def scalar(self, _stmt):
            return 36

    assert _highest_report_id(previews) == 34
    assert _highest_report_id(executions) == 43
    assert next_media_package_job_id(ReadOnlySession(), settings) == 44
    assert (executions / "43" / "0000000.manifest.json").read_text() == "old manifest"


@pytest.mark.parametrize("namespace", ["organizer-v1-previews", "organizer-v1-executions"])
def test_recursive_organizer_report_artifact_reserves_job_id(tmp_path, namespace):
    settings = settings_for(tmp_path)
    report = settings.reports_dir / namespace / "43"
    report.mkdir(parents=True)
    session = type("Session", (), {"scalar": lambda *args: 0})()

    assert next_media_package_job_id(session, settings) == 44
    assert report.is_dir()


def test_report_namespace_symlink_is_rejected(tmp_path):
    settings = settings_for(tmp_path)
    reports = settings.reports_dir
    reports.mkdir()
    (tmp_path / "foreign").mkdir()
    (reports / "media_package-executions").symlink_to(tmp_path / "foreign")
    with pytest.raises(ValueError, match="Unsafe MediaPackage report directory"):
        next_media_package_job_id(type("Session", (), {"scalar": lambda *a: 0})(), settings)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("checksum", "SHA-256 checksum differs"),
        ("schema", "schema version differs"),
        ("job_id", "execution job ID differs"),
        ("package", "package path differs from preview"),
    ],
)
def test_manifest_integrity_errors_identify_specific_field(tmp_path, kind, expected):
    path = tmp_path / "manifest.json"
    package = tmp_path / "media"
    frozen = {"schema_version": execution.MANIFEST_VERSION,
              "job_id": 14, "package": str(package), "moves": []}
    execution.save_frozen_manifest(path, frozen)
    body = json.loads(path.read_text())
    if kind == "checksum":
        body["manifest"]["moves"].append({"tampered": True})
    elif kind == "schema":
        body["manifest"]["schema_version"] = -1
    elif kind == "job_id":
        body["manifest"]["job_id"] = 999
    elif kind == "package":
        body["manifest"]["package"] = str(tmp_path / "another")
    if kind != "checksum":
        body["checksum"] = execution._manifest_checksum(body["manifest"])
    path.write_text(json.dumps(body))
    before = path.read_bytes()

    with pytest.raises(execution.MediaPackageExecutionConflict, match=expected):
        execution.load_frozen_manifest(path, job_id=14, package=package)
    assert path.read_bytes() == before


@pytest.mark.parametrize("content", ["not-json", "[]", '{"manifest":1}'])
def test_malformed_manifest_fails_closed_without_repair(tmp_path, content):
    path = tmp_path / "manifest.json"
    path.write_text(content)
    with pytest.raises(execution.MediaPackageExecutionConflict, match="integrity mismatch"):
        execution.load_frozen_manifest(path, job_id=14, package=tmp_path / "media")
    assert path.read_text() == content


def _task_db(settings, entries):
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "CREATE TABLE work_jobs "
            "(id INTEGER PRIMARY KEY, kind TEXT, status TEXT, "
            "progress_current INTEGER, progress_total INTEGER, "
            "state_json TEXT, error_text TEXT)"
        )
        db.executemany(
            "INSERT INTO work_jobs VALUES (?,?,?,?,?,?,?)", entries
        )


def test_inspector_reports_integrity_and_keeps_referenced_previews(tmp_path):
    settings = settings_for(tmp_path)
    package = tmp_path / "data" / "package"
    package.mkdir(parents=True)
    (package / ".nfc-media_package-stage-14-0").mkdir()
    previews = settings.reports_dir / "media_package-previews"
    executions = settings.reports_dir / "media_package-executions"
    previews.mkdir(parents=True)
    (executions / "14").mkdir(parents=True)
    report = previews / "13.packages.jsonl"
    report.write_text(json.dumps({"package": str(package), "status": "ready"}) + "\n")
    (previews / "99.packages.jsonl").write_text("unreferenced")
    frozen = {"schema_version": execution.MANIFEST_VERSION,
              "job_id": 14, "package": str(package), "moves": [{"id": 1}]}
    manifest_file = executions / "14" / "0000000.manifest.json"
    execution.save_frozen_manifest(manifest_file, frozen)
    _task_db(settings, [
        (13, "media_package-package-preview", "completed", 1, 1, "{}", None),
        (14, "media_package-package-execute", "failed", 0, 1,
         json.dumps({"preview_job_id": 13}), "failed earlier"),
    ])

    original = manifest_file.read_bytes()
    details = inspect_execution(settings, 14)
    assert details["read_only"] is True
    assert details["manifest_integrity"] == "valid"
    assert details["stage_entries"] == [".nfc-media_package-stage-14-0"]
    assert details["frozen_move_count"] == 1
    classified = inventory(settings)
    previews_by_id = {x["job_id"]: x for x in classified["preview_reports"]}
    assert previews_by_id[13]["disposition"] == "retain_execution_dependency"
    assert previews_by_id[99]["disposition"] == "review_orphan_never_auto_delete"
    assert classified["auto_prune"] is False
    assert classified["execution_reports"][0]["disposition"] == (
        "retain_execution_recovery_or_audit"
    )
    assert manifest_file.read_bytes() == original
    assert report.exists()


def test_inspector_detects_missing_manifest_without_writing(tmp_path):
    settings = settings_for(tmp_path)
    previews = settings.reports_dir / "media_package-previews"
    previews.mkdir(parents=True)
    (previews / "7.packages.jsonl").write_text(
        json.dumps({"package": str(tmp_path / "data")}) + "\n"
    )
    _task_db(settings, [
        (8, "media_package-package-execute", "failed", 0, 1,
         json.dumps({"preview_job_id": 7}), "error"),
    ])
    result = inspect_execution(settings, 8)
    assert result["manifest_integrity"] == "missing_or_unsafe"
    assert not (settings.reports_dir / "media_package-executions" / "8").exists()
