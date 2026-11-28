"""Exercise the fixed rclone RC requests without connecting to a NAS."""
import io
import json
from urllib.error import HTTPError

import pytest

STAGE_NAME = ".nfc-cloud-copy-" + "0" * 32
STAGE = "/nfc-import/" + STAGE_NAME


class Response:
    status = 200
    headers = {"Content-Encoding": "identity"}

    def __init__(self, body: bytes):
        self.body = io.BytesIO(body)

    def read(self, size):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.body.close()


def test_copy_submits_only_the_attributed_one_way_operation(tmp_path, monkeypatch):
    from app.cloud_copy import rclone

    password = tmp_path / "rc-password"
    password.write_text("fixture-only\n", encoding="utf-8")
    calls = []
    execute_id = "2dcb71e9-25d7-4ebe-9d68-f89babba3c8b"
    group = None

    class Remote:
        def open(self, request, timeout):
            nonlocal group
            op = request.full_url.split(":5572/")[1]
            parameters = json.loads(request.data)
            calls.append((op, parameters))
            assert request.get_method() == "POST"
            assert request.get_header("Authorization") == "Basic d29ya2VyOmZpeHR1cmUtb25seQ=="
            assert 0 < timeout <= 15
            if op == "sync/copy":
                group = parameters["_group"]
                reply = {"jobid": 42, "executeId": execute_id}
            elif op == "job/status":
                reply = {"id": 42, "executeId": execute_id, "group": group, "finished": False, "success": False}
            elif op == "core/stats":
                reply = {"bytes": 3, "speed": 1.5, "eta": None, "lastError": "private-output"}
            else:
                assert op == "job/stopgroup"
                reply = {}
            return Response(json.dumps(reply).encode())

    monkeypatch.setattr(rclone, "build_opener", lambda *handlers: Remote())
    client = rclone.RcloneClient("http://cloud-transfer:5572", "worker", password)
    assert client.start_copy("openlist:摄影/照片", STAGE) == (42, execute_id)
    assert client.status(42, execute_id)["finished"] is False
    assert client.stats(42) == {
        "bytes": 3, "totalBytes": 0, "speed": 1.5, "eta": None, "transfers": 0, "totalTransfers": 0, "errors": 0,
    }
    client.stop(42, execute_id)

    assert calls[0][1]["srcFs"] == "openlist:摄影/照片"
    assert calls[0][1]["dstFs"] == STAGE
    assert calls[0][1]["_async"] and calls[0][1]["createEmptySrcDirs"]
    assert calls[0][1]["_config"]["Immutable"] is True
    assert calls[0][1]["_config"]["MaxDuration"] > 0
    assert calls[1:] == [
        ("job/status", {"jobid": 42}),
        ("core/stats", {"group": group, "short": True}),
        ("job/status", {"jobid": 42}),
        ("job/stopgroup", {"group": group}),
    ]


@pytest.mark.parametrize("url", [
    "http://localhost:5572", "http://public.example:5572", "https://user:password@worker",
    "https://cloud-transfer/other", "file:///tmp",
])
def test_rejects_endpoints_outside_the_configured_origin(tmp_path, url):
    from app.cloud_copy.rclone import RcloneClient, RcloneError

    with pytest.raises(RcloneError):
        RcloneClient(url, "worker", tmp_path / "rc-password")


@pytest.mark.parametrize("source,destination", [
    ("/tmp/source", STAGE),
    (":s3:endpoint/path", STAGE),
    ("openlist,option=bad:path", STAGE),
    ("openlist:../path", STAGE),
    ("openlist:folder", "/nfc-import/final"),
    ("openlist:folder", "user:/nfc-import/.nfc-cloud-copy-stage"),
])
def test_copy_rejects_unscoped_requests_before_using_credentials(tmp_path, source, destination):
    from app.cloud_copy.rclone import RcloneClient, RcloneError

    client = RcloneClient("http://cloud-transfer:5572", "worker", tmp_path / "absent")
    with pytest.raises(RcloneError, match="复制来源或暂存路径无效"):
        client.start_copy(source, destination)


def test_stale_daemon_cannot_stop_a_reused_job_id(tmp_path, monkeypatch):
    from app.cloud_copy import rclone

    password = tmp_path / "rc-password"
    password.write_text("fixture-only", encoding="utf-8")
    calls = []

    class Remote:
        def open(self, request, timeout):
            calls.append(request.full_url)
            return Response(json.dumps({
                "id": 42, "executeId": "new-daemon", "group": "nfc-cloud-copy-" + "a" * 32,
                "finished": False, "success": False,
            }).encode())

    monkeypatch.setattr(rclone, "build_opener", lambda *handlers: Remote())
    client = rclone.RcloneClient("http://cloud-transfer:5572", "worker", password)
    with pytest.raises(rclone.RcloneError, match="实例或任务已变化"):
        client.stop(42, "old-daemon")
    assert calls == ["http://cloud-transfer:5572/job/status"]


@pytest.mark.parametrize("failure,expected", [
    ("no space left on device for private-file", "NAS 暂存空间不足"),
    ("HTTP 403 Forbidden: secret-url", "云端来源拒绝读取"),
    ("vendor text with access credentials", "rclone 报告复制失败"),
])
def test_failure_reasons_are_categorized_without_returning_remote_output(tmp_path, monkeypatch, failure, expected):
    from app.cloud_copy import rclone

    password = tmp_path / "rc-password"
    password.write_text("fixture-only", encoding="utf-8")

    class Remote:
        def open(self, request, timeout):
            return Response(json.dumps({
                "id": 42, "executeId": "my-daemon", "group": "nfc-cloud-copy-" + "a" * 32,
                "finished": True, "success": False, "error": failure, "output": {"token": "remote-secret"},
            }).encode())

    monkeypatch.setattr(rclone, "build_opener", lambda *handlers: Remote())
    client = rclone.RcloneClient("http://cloud-transfer:5572", "worker", password)
    result = client.status(42, "my-daemon")
    assert result["error"] == expected
    assert "output" not in result and failure not in str(result)


def test_http_authentication_error_does_not_return_vendor_data(tmp_path, monkeypatch):
    from app.cloud_copy import rclone

    password = tmp_path / "rc-password"
    password.write_text("fixture-only", encoding="utf-8")

    class Remote:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 401, "private-diagnostics", {}, io.BytesIO(b"secret response"))

    monkeypatch.setattr(rclone, "build_opener", lambda *handlers: Remote())
    client = rclone.RcloneClient("http://cloud-transfer:5572", "worker", password)
    with pytest.raises(rclone.RcloneError, match="拒绝授权") as denied:
        client.status(42, "daemon")
    assert "private-diagnostics" not in str(denied.value)


def test_symlinked_password_cannot_be_read(tmp_path):
    from app.cloud_copy.rclone import RcloneClient, RcloneError

    password = tmp_path / "rc-password"
    password.symlink_to(tmp_path / "existing-secret")
    password.resolve().write_text("fixture-only", encoding="utf-8")
    client = RcloneClient("http://cloud-transfer:5572", "worker", password)
    with pytest.raises(RcloneError, match="服务密码文件不可用"):
        client.status(42, "daemon")


@pytest.mark.parametrize("item,expected", [
    ({"Path": STAGE_NAME, "Name": STAGE_NAME, "IsDir": True}, True),
    ({"Path": STAGE_NAME, "Name": STAGE_NAME, "IsDir": False}, False),
    ({"Path": STAGE_NAME, "Name": "other", "IsDir": True}, False),
    (None, False),
])
def test_staging_directory_must_be_visible_to_rclone_before_copy(tmp_path, monkeypatch, item, expected):
    from app.cloud_copy import rclone

    password = tmp_path / "rc-password"
    password.write_text("fixture-only", encoding="utf-8")
    requests = []

    class Remote:
        def open(self, request, timeout):
            requests.append((request.full_url, json.loads(request.data)))
            return Response(json.dumps({"item": item}).encode())

    monkeypatch.setattr(rclone, "build_opener", lambda *handlers: Remote())
    client = rclone.RcloneClient("http://cloud-transfer:5572", "worker", password)
    if expected:
        client.require_staging_directory(STAGE)
    else:
        with pytest.raises(rclone.RcloneError, match="rclone 无法看到 NAS 暂存目录"):
            client.require_staging_directory(STAGE)
    assert requests == [("http://cloud-transfer:5572/operations/stat", {"fs": "/nfc-import", "remote": STAGE_NAME})]
