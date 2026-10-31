"""OTP source sessions: protected cache and API/Worker reuse."""
import json
import stat
from pathlib import Path

from app.download_verification.sources import (
    AListAPIClient, clear_source_session, read_source_session,
    save_source_session, source_secret_path, write_secret,
)


class Reply:
    status = 200
    headers = {"Content-Encoding": "identity"}
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, length=-1):
        return json.dumps(self.payload).encode()


class Opener:
    def __init__(self):
        self.calls = []
    def open(self, request, timeout=None):
        body = json.loads(request.data)
        self.calls.append((request.full_url, body, request.headers))
        if request.full_url.endswith("/api/auth/login"):
            assert body["otp_code"] == "123456"
            return Reply({"code": 200, "data": {"token": "test-token"}})
        return Reply({"code": 200, "data": {"total": 0, "content": []}})


def test_otp_session_reused_by_separate_worker_client(tmp_path):
    name = "source-" + "a" * 32 + ".secret"
    write_secret(tmp_path, name, "example-password")
    opener = Opener()
    a = AListAPIClient(base_url="http://openlist:5244", username="read",
                       password_file=str(source_secret_path(tmp_path, name)),
                       session_config_dir=tmp_path, session_secret_name=name,
                       otp_code="123456", opener=opener)
    assert a.list_directory(()) == {}
    assert len([x for x in opener.calls if x[0].endswith("/api/auth/login")]) == 1
    cache = source_secret_path(tmp_path, name).with_suffix(".session")
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert "123456" not in cache.read_text()
    assert "example-password" not in cache.read_text()
    second = Opener()
    b = AListAPIClient(base_url="http://openlist:5244", username="read",
                       password_file=str(source_secret_path(tmp_path, name)),
                       session_config_dir=tmp_path, session_secret_name=name,
                       opener=second)
    b.list_directory(())
    assert len(second.calls) == 1
    assert second.calls[0][2].get("Authorization") == "test-token"
    assert read_source_session(tmp_path, name, "http://other:5244", "read") == ""
    clear_source_session(tmp_path, name)
    assert not cache.exists()


def test_expired_session_requires_fresh_otp(tmp_path):
    name = "source-" + "b" * 32 + ".secret"
    write_secret(tmp_path, name, "example-password")
    save_source_session(tmp_path, name, "http://openlist:5244", "read", "expired-soon")
    cache = source_secret_path(tmp_path, name).with_suffix(".session")
    obj = json.loads(cache.read_text())
    obj["expires_at"] = 1
    cache.write_text(json.dumps(obj))
    assert read_source_session(tmp_path, name, "http://openlist:5244", "read") == ""
