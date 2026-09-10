from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.tasks.handlers import IndexRootHandler
from app.models import WorkJob

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_index_root_maintains_serial_execution(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    handler = IndexRootHandler()
    job = WorkJob(id=2, kind="index-root", state_json='{"root": "/allowed/root"}')
    context = MagicMock()
    context.SessionLocal = SessionLocal
    context.worker_id = None

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
    )

    with patch("app.service.FileCenterService.reindex_root") as mock_reindex:
        mock_reindex.return_value = {"files": 10, "folders": 2}
        handler.run(job, context, settings)

        mock_reindex.assert_called_once()
        call_args_list = [c for c in context.log.call_args_list if c[0][0] == "resource_policy_applied"]
        assert len(call_args_list) >= 1
        logged_ctx = call_args_list[0][1]["context"]
        assert logged_ctx["profile"] == "full"
        assert logged_ctx["execution_concurrency"] == 1
