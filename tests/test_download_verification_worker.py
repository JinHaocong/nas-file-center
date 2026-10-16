"""End-to-end Worker orchestration: a completed WorkJob is not itself verification success."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import WorkJob
from app.tasks.context import JobContext
from app.download_verification.handler import DownloadVerificationHandler
from app.download_verification.models import DownloadVerificationRun, DownloadVerificationItem


class FakeRemote:
    def __init__(self, payload=b'abcd', changed=False):
        self.payload = payload
        self.changed = changed
        self.list_calls = 0

    def manifest(self, parts):
        self.list_calls += 1
        if self.changed and self.list_calls == 2:
            return {"changed.txt": {"kind": "file", "size": 4, "etag": None, "mtime": None}}
        return {"file.txt": {"kind": "file", "size": 4, "etag": None, "mtime": None}}

    def sha256(self, path, size, checkpoint):
        assert path == ("file.txt",)
        assert size == 4
        checkpoint()
        return hashlib.sha256(self.payload).hexdigest()


@pytest.mark.parametrize("remote_bytes,remote_changes,expected", [
    (b'abcd', False, "VERIFIED_IDENTICAL"),
    (b'WXYZ', False, "DIFFERENT"),
    (b'abcd', True, "STALE"),
])
def test_worker_full_run_and_fail_closed_final_verdict(tmp_path, monkeypatch,
                                                       remote_bytes, remote_changes, expected):
    data = tmp_path / "data"
    data.mkdir()
    target = data / "Movies"
    target.mkdir()
    (target / "file.txt").write_bytes(b'abcd')
    secret = tmp_path / "secret"
    secret.write_text("secret")
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(tmp_path / "config"), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        DOWNLOAD_VERIFY_WEBDAV_BASE_URL="https://dav.example/dav/",
        DOWNLOAD_VERIFY_WEBDAV_USER="readonly",
        DOWNLOAD_VERIFY_WEBDAV_PASSWORD_FILE=str(secret),
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123"}).status_code == 200
        enqueue = client.post("/api/download-verifications",
            json={"remote_root": "", "local_root": str(target)})
        assert enqueue.status_code == 202, enqueue.text
        run_id = enqueue.json()["id"]
        job_id = enqueue.json()["work_job_id"]
        service = client.app.state.service
        with service.SessionLocal() as session:
            job = session.get(WorkJob, job_id)
            job.status = "running"
            # An interrupted old attempt may have more progress than the new tree.
            job.progress_current = 50
            job.progress_total = 50
            session.commit()
        remote = FakeRemote(remote_bytes, remote_changes)
        monkeypatch.setattr("app.download_verification.handler.build_client", lambda settings: remote)
        ctx = JobContext(service.engine, service.SessionLocal, job_id, worker_id=None)
        if remote_changes:
            with pytest.raises(ValueError, match="REMOTE_CHANGED"):
                DownloadVerificationHandler().run(job, ctx, settings)
        else:
            DownloadVerificationHandler().run(job, ctx, settings)
            # A green result is suppressed while the Worker is still running.
            pending = client.get("/api/download-verifications/" + str(run_id))
            assert pending.json()["result"] == "INCOMPLETE"
            with service.SessionLocal() as session:
                session.get(WorkJob, job_id).status = "completed"
                session.commit()
        detail = client.get("/api/download-verifications/" + str(run_id))
        if remote_changes:
            assert detail.json()["result"] == "INCOMPLETE"
            with service.SessionLocal() as session:
                assert session.get(DownloadVerificationRun, run_id).result == "STALE"
        else:
            assert detail.json()["result"] == expected
            items = client.get(f"/api/download-verifications/{run_id}/items").json()["items"]
            assert len(items) == 1
            assert items[0]["status"] == (
                "VERIFIED_MATCH" if expected == "VERIFIED_IDENTICAL" else "HASH_MISMATCH")
        assert (target / "file.txt").read_bytes() == b'abcd'
