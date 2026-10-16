"""Deletion of completed verification reports does not alter the source files or task audit."""
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.download_verification.models import DownloadVerificationItem, DownloadVerificationRun
from app.models import WorkJob


def test_delete_only_terminal_reports_keeps_task_history_and_files(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    file = root / "preserve.mkv"
    file.write_bytes(b"original")
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(tmp_path / "config"), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        url = "/api/download-verifications/1"
        assert client.delete(url).status_code == 401
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        session_factory = client.app.state.service.SessionLocal
        with session_factory() as session:
            job = WorkJob(kind="download-verify-webdav", status="queued", state_json='{"run_id": 1}')
            session.add(job)
            session.flush()
            run = DownloadVerificationRun(
                work_job_id=job.id, remote_root="", local_root=str(root),
                mode="metadata", result="INCOMPLETE",
            )
            session.add(run)
            session.flush()
            run_id, job_id = run.id, job.id
            session.add(DownloadVerificationItem(
                run_id=run_id, relative_path="preserve.mkv", kind="file",
                status="METADATA_MATCH", remote_size=8, local_size=8,
            ))
            session.commit()
        url = f"/api/download-verifications/{run_id}"
        assert client.delete(url).status_code == 409
        assert client.get(url).status_code == 200
        with session_factory() as session:
            session.get(WorkJob, job_id).status = "paused"
            session.commit()
        assert client.delete(url).status_code == 409
        with session_factory() as session:
            session.get(WorkJob, job_id).status = "completed"
            session.commit()
        assert client.delete(url).status_code == 204
        assert client.get(url).status_code == 404
        assert client.get(url + "/items").status_code == 404
        assert client.delete(url).status_code == 404
        with session_factory() as session:
            assert session.get(WorkJob, job_id) is not None
            assert session.get(DownloadVerificationRun, run_id) is None
            assert session.query(DownloadVerificationItem).filter_by(run_id=run_id).count() == 0
        assert file.read_bytes() == b"original"
