"""Deletion of completed verification reports does not alter the source files or task audit."""
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.download_verification.models import DownloadVerificationItem, DownloadVerificationRun
from app.models import WorkJob, utcnow


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
        assert client.get(url).json()["can_delete"] is False
        with session_factory() as session:
            session.get(WorkJob, job_id).status = "paused"
            session.commit()
        assert client.get(url).json()["can_delete"] is False
        assert client.delete(url).status_code == 409
        with session_factory() as session:
            session.get(WorkJob, job_id).status = "completed"
            session.commit()
        assert client.get(url).json()["can_delete"] is True
        assert client.delete(url).status_code == 204
        assert client.get(url).status_code == 404
        assert client.get(url + "/items").status_code == 404
        assert client.delete(url).status_code == 404
        with session_factory() as session:
            assert session.get(WorkJob, job_id) is not None
            assert session.get(DownloadVerificationRun, run_id) is None
            assert session.query(DownloadVerificationItem).filter_by(run_id=run_id).count() == 0
        assert file.read_bytes() == b"original"


def test_orphaned_verification_reports_can_be_deleted_regardless_of_verdict(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(tmp_path / "config"), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        session_factory = client.app.state.service.SessionLocal
        with session_factory() as session:
            for verdict in ("DIFFERENT", "INCOMPLETE"):
                session.add(DownloadVerificationRun(
                    work_job_id=None, remote_root="", local_root=str(root),
                    mode="metadata", result=verdict,
                    finished_at=utcnow() if verdict == "DIFFERENT" else None,
                ))
            session.commit()
            run_ids = [run.id for run in session.query(DownloadVerificationRun).order_by(
                DownloadVerificationRun.id).all()]
        summaries = client.get("/api/download-verifications").json()["items"]
        assert len(summaries) == 2
        assert {s["result"] for s in summaries} == {"DIFFERENT", "INCOMPLETE"}
        for run_id in run_ids:
            response = client.get(f"/api/download-verifications/{run_id}")
            assert response.status_code == 200
            assert response.json()["job_status"] == "unknown"
            assert response.json()["can_delete"] is True
            assert client.delete(f"/api/download-verifications/{run_id}").status_code == 204
        assert client.get("/api/download-verifications").json()["total"] == 0


def test_abnormal_item_filter_counts_and_paginates_entire_run(tmp_path):
    """The abnormal toggle filters SQL before LIMIT/OFFSET, not the UI's 50 rows."""
    root = tmp_path / "data"
    root.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(tmp_path / "config"), DATA_MOUNT=str(root),
        ALLOWED_ROOTS=str(root), QUARANTINE_ROOT=str(root / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        endpoint = "/api/download-verifications/1/items"
        assert client.get(endpoint + "?abnormal_only=true").status_code == 401
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        with client.app.state.service.SessionLocal() as session:
            run = DownloadVerificationRun(
                work_job_id=None, remote_root="", local_root=str(root),
                mode="strict_sha256", result="DIFFERENT", finished_at=utcnow(),
            )
            session.add(run)
            session.flush()
            run_id = run.id
            for n in range(65):
                session.add(DownloadVerificationItem(
                    run_id=run_id, relative_path=f"a-matched-{n:03d}.mkv",
                    kind="file", status="METADATA_MATCH", remote_size=4, local_size=4,
                ))
            for label, state in (
                ("z-only-local", "ONLY_LOCAL"),
                ("z-only-remote", "ONLY_REMOTE"),
                ("z-size", "SIZE_MISMATCH"),
                ("z-type", "TYPE_MISMATCH"),
                ("z-hash", "HASH_MISMATCH"),
            ):
                session.add(DownloadVerificationItem(
                    run_id=run_id, relative_path=label, kind="file",
                    status=state, remote_size=7, local_size=4,
                ))
            for label, state in (
                ("b-dir", "DIRECTORY_MATCH"),
                ("b-verified", "VERIFIED_MATCH"),
                ("b-pending", "PENDING_SHA256"),
            ):
                session.add(DownloadVerificationItem(
                    run_id=run_id, relative_path=label, kind="file",
                    status=state, remote_size=4, local_size=4,
                ))
            other = DownloadVerificationRun(
                work_job_id=None, remote_root="", local_root=str(root),
                mode="metadata", result="DIFFERENT",
            )
            session.add(other)
            session.flush()
            session.add(DownloadVerificationItem(
                run_id=other.id, relative_path="other-run-only-local", kind="file",
                status="ONLY_LOCAL", remote_size=None, local_size=2,
            ))
            session.commit()

        url = f"/api/download-verifications/{run_id}/items"
        ordinary = client.get(url + "?page=1&page_size=50").json()
        assert ordinary["total"] == 73
        assert len(ordinary["items"]) == 50
        assert all(item["status"] == "METADATA_MATCH" for item in ordinary["items"])

        abnormal = client.get(url + "?abnormal_only=true&page=1&page_size=2").json()
        assert abnormal["total"] == 5
        assert len(abnormal["items"]) == 2
        assert {item["status"] for item in abnormal["items"]} <= {
            "ONLY_LOCAL", "ONLY_REMOTE", "SIZE_MISMATCH", "TYPE_MISMATCH", "HASH_MISMATCH",
        }
        page2 = client.get(url + "?abnormal_only=true&page=2&page_size=2").json()
        page3 = client.get(url + "?abnormal_only=true&page=3&page_size=2").json()
        assert [len(part["items"]) for part in (abnormal, page2, page3)] == [2, 2, 1]
        assert {item["status"] for part in (abnormal, page2, page3)
                for item in part["items"]} == {
            "ONLY_LOCAL", "ONLY_REMOTE", "SIZE_MISMATCH", "TYPE_MISMATCH", "HASH_MISMATCH",
        }
        assert client.get(url + "?status=METADATA_MATCH&abnormal_only=true").json() == {
            "total": 0, "page": 1, "page_size": 50, "items": [],
        }
        assert client.get(url + "?status=SIZE_MISMATCH&abnormal_only=true").json()["total"] == 1
        assert client.get(url + "?abnormal_only=not-a-boolean").status_code == 422
        assert client.get("/api/download-verifications/999999/items?abnormal_only=true").status_code == 404
        assert (root / "sentinel").exists() is False
