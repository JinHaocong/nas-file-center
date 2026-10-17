"""Atomic, authorization-guarded bulk deletion of verification reports only."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.download_verification.models import DownloadVerificationItem, DownloadVerificationRun
from app.models import WorkJob, utcnow


def test_bulk_delete_validates_all_targets_before_any_removal(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    protected_file = root / "keep.mkv"
    protected_file.write_bytes(b"keep")
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(tmp_path / "config"), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        endpoint = "/api/download-verifications/bulk-delete"
        assert client.post(endpoint, json={"run_ids": [1]}).status_code == 401
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        session_factory = client.app.state.service.SessionLocal
        with session_factory() as session:
            completed_job = WorkJob(kind="download-verify-webdav", status="completed", state_json="{}")
            active_job = WorkJob(kind="download-verify-webdav", status="paused", state_json="{}")
            session.add_all([completed_job, active_job])
            session.flush()
            jobs = [completed_job.id, active_job.id]
            runs = [
                DownloadVerificationRun(
                    work_job_id=completed_job.id, remote_root="", local_root=str(root),
                    mode="metadata", result="METADATA_IDENTICAL", finished_at=utcnow(),
                ),
                DownloadVerificationRun(
                    work_job_id=None, remote_root="", local_root=str(root),
                    mode="metadata", result="DIFFERENT", finished_at=utcnow(),
                ),
                DownloadVerificationRun(
                    work_job_id=active_job.id, remote_root="", local_root=str(root),
                    mode="metadata", result="INCOMPLETE",
                ),
            ]
            session.add_all(runs)
            session.flush()
            ids = [run.id for run in runs]
            for run in runs:
                session.add(DownloadVerificationItem(
                    run_id=run.id, relative_path="keep.mkv", kind="file",
                    status="METADATA_MATCH", remote_size=4, local_size=4,
                ))
            session.commit()

        # Validation rejects empty, duplicate, invalid and oversized requests.
        invalid = [
            [], [ids[0], ids[0]], [-1], [True], ["1"], list(range(1, 52)),
        ]
        for run_ids in invalid:
            assert client.post(endpoint, json={"run_ids": run_ids}).status_code == 422
        assert client.post(endpoint, json={"run_ids": [ids[0]], "other": True}).status_code == 422

        # A paused job blocks the *entire* batch without losing any item rows.
        response = client.post(endpoint, json={"run_ids": ids})
        assert response.status_code == 409
        assert response.json()["detail"] == "VERIFICATION_JOB_NOT_TERMINAL"
        with session_factory() as session:
            assert session.query(DownloadVerificationRun).count() == 3
            assert session.query(DownloadVerificationItem).count() == 3

        # A stale / nonexistent ID also aborts without deleting valid rows.
        assert client.post(endpoint, json={"run_ids": [ids[0], 999999]}).status_code == 404
        with session_factory() as session:
            assert session.query(DownloadVerificationRun).count() == 3

        with session_factory() as session:
            session.get(WorkJob, jobs[1]).status = "cancelled"
            session.commit()
        assert all(item["can_delete"] for item in
                   client.get("/api/download-verifications").json()["items"])

        response = client.post(endpoint, json={"run_ids": ids})
        assert response.status_code == 200
        assert response.json() == {"deleted": 3}
        assert client.get("/api/download-verifications").json()["total"] == 0
        with session_factory() as session:
            assert session.query(DownloadVerificationRun).count() == 0
            assert session.query(DownloadVerificationItem).count() == 0
            assert all(session.get(WorkJob, job_id) is not None for job_id in jobs)
        assert protected_file.read_bytes() == b"keep"
        assert client.post(endpoint, json={"run_ids": ids}).status_code == 404
