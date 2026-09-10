from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from app.db import create_engine_and_session, init_db
from app.tasks.handlers import FclonesScanHandler
from app.models import WorkJob, ResourcePolicy
from app.resource_control import ResourcePolicyConfigError

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_fclones_scan_handler_applies_effective_threads_and_logs(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    handler = FclonesScanHandler()
    job = WorkJob(id=1, kind="fclones-scan", state_json='{"roots": ["/allowed/root"], "scan_job_id": 1}')
    context = MagicMock()
    context.SessionLocal = SessionLocal
    context.worker_id = None  # Prevent mock lease check failure
    settings = MagicMock()
    settings.allowed_roots = ["/allowed/root"]
    settings.reports_dir = tmp_path
    settings.fclones_binary = "fclones"
    settings.fclones_threads = "4"  # legacy setting

    with SessionLocal() as session:
        p = session.get(ResourcePolicy, 1)
        p.scan_threads = 2
        p.hash_threads = 2
        p.io_limit = "normal"
        session.commit()

    with patch("app.tasks.handlers.build_group_command") as mock_build, \
         patch("app.tasks.handlers.run_scan") as mock_run, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(())):
        mock_run.return_value.returncode = 0
        handler.run(job, context, settings)

        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["threads"] == "2"

        # Exact dictionary-field assertion on logged context
        call_args_list = [c for c in context.log.call_args_list if c[0][0] == "resource_policy_applied"]
        assert len(call_args_list) >= 1
        logged_ctx = call_args_list[0][1]["context"]
        assert logged_ctx["resource_policy_revision"] == 1
        assert logged_ctx["profile"] == "full"
        assert logged_ctx["effective_thread_cap"] == 2

def test_fclones_scan_corrupt_policy_fails_closed_before_subprocess(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    handler = FclonesScanHandler()
    job = WorkJob(id=2, kind="fclones-scan", state_json='{"roots": ["/allowed/root"], "scan_job_id": 2}')
    context = MagicMock()
    context.SessionLocal = SessionLocal
    context.worker_id = None
    settings = MagicMock()
    settings.allowed_roots = ["/allowed/root"]
    settings.reports_dir = tmp_path
    settings.fclones_threads = "invalid_threads_format"

    with patch("app.tasks.handlers.run_scan") as mock_run:
        with pytest.raises(ResourcePolicyConfigError):
            handler.run(job, context, settings)
        mock_run.assert_not_called()

def test_fclones_scan_handler_effective_thread_ceiling_cases(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    handler = FclonesScanHandler()
    context = MagicMock()
    context.SessionLocal = SessionLocal
    context.worker_id = None
    settings = MagicMock()
    settings.allowed_roots = ["/allowed/root"]
    settings.reports_dir = tmp_path
    settings.fclones_binary = "fclones"
    settings.fclones_threads = None

    with SessionLocal() as session:
        p = session.get(ResourcePolicy, 1)
        p.scan_threads = 2
        p.hash_threads = 2
        p.io_limit = "normal"
        session.commit()

    # Case A: global effective cap = 2, job state threads = 32 -> build_group_command(... threads="2")
    job_a = WorkJob(id=10, kind="fclones-scan", state_json='{"roots": ["/allowed/root"], "scan_job_id": 10, "threads": 32}')
    with patch("app.tasks.handlers.build_group_command") as mock_build_a, \
         patch("app.tasks.handlers.run_scan") as mock_run_a, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(())):
        mock_run_a.return_value.returncode = 0
        handler.run(job_a, context, settings)
        mock_build_a.assert_called_once()
        assert mock_build_a.call_args.kwargs["threads"] == "2"

    # Case B: global effective cap = 2, job state threads = 1 -> build_group_command(... threads="1")
    job_b = WorkJob(id=11, kind="fclones-scan", state_json='{"roots": ["/allowed/root"], "scan_job_id": 11, "threads": 1}')
    with patch("app.tasks.handlers.build_group_command") as mock_build_b, \
         patch("app.tasks.handlers.run_scan") as mock_run_b, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(())):
        mock_run_b.return_value.returncode = 0
        handler.run(job_b, context, settings)
        mock_build_b.assert_called_once()
        assert mock_build_b.call_args.kwargs["threads"] == "1"
