"""Test the native rclone contract at its authenticated HTTP boundary."""
import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest

from app.cloud_copy import rclone as transport


class _Response:
    headers = {"Content-Encoding": "identity"}
    will_close = False

    def __init__(self, value, status=200):
        self.status = status
        self._body = io.BytesIO(json.dumps(value).encode())

    def read(self, size):
        return self._body.read(size)

    def close(self):
        self._body.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def rc(tmp_path, monkeypatch):
    """Intercept configured-origin requests and assert authentication is never forwarded."""
    password_file = tmp_path / "password"
    password_file.write_text("fixture-password\n")
    calls = []
    replies = {}
    connections = []

    def respond(endpoint, payload, headers):
        assert headers.get("Authorization") == "Basic dGVzdDpmaXh0dXJlLXBhc3N3b3Jk"
        calls.append((endpoint, json.loads(payload)))
        reply = replies[endpoint]
        return _Response(*reply) if isinstance(reply, tuple) else _Response(reply)

    class Opener:
        def open(self, request, timeout):
            url = urlsplit(request.full_url)
            assert url.netloc == "rclone:5533" and request.get_method() == "POST"
            response = respond(url.path[1:], request.data, request.headers)
            if response.status != 200:
                raise HTTPError(request.full_url, response.status, "fixture", response.headers, response._body)
            return response

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "rclone" and port == 5533
            self.sock = None
            self.auto_open = 1
            connections.append(self)

        def connect(self):
            self.sock = object()

        def request(self, method, path, body, headers):
            assert method == "POST" and self.sock is not None and self.auto_open == 0
            self.response = respond(path[1:], body, headers)

        def getresponse(self):
            return self.response

        def close(self):
            self.sock = None

    monkeypatch.setattr(transport, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(transport, "HTTPConnection", Connection, raising=False)
    return password_file, calls, replies, connections


def _provider(rc):
    from app.cloud_files.rclone import RcloneProvider

    return RcloneProvider("http://rclone:5533", "test", rc[0])


def test_lists_literal_configured_remotes_and_immediate_children(rc):
    _, calls, replies, _ = rc
    replies["config/listremotes"] = {"remotes": ["PikPak WebDAV", "backup", ":s3", "inline,token=bad"]}
    replies["operations/list"] = {"list": [
        {"Name": "照片", "Path": "摄影/照片", "IsDir": True, "Size": -1},
        {"Name": "封面.jpg", "Path": "摄影/封面.jpg", "IsDir": False, "Size": 30},
    ]}
    provider = _provider(rc)

    assert provider.remotes() == ["backup", "PikPak WebDAV"]
    assert provider.entries("PikPak WebDAV", ("摄影",)) == [
        {"name": "照片", "kind": "directory", "size": None},
        {"name": "封面.jpg", "kind": "file", "size": 30},
    ]
    assert calls == [
        ("config/listremotes", {}),
        ("operations/list", {"fs": "PikPak WebDAV:", "remote": "摄影",
                             "opt": {"noModTime": True, "noMimeType": True}}),
    ]


@pytest.mark.parametrize(("directory", "endpoint", "parameters"), [
    (True, "sync/copy", {"srcFs": "PikPak WebDAV:摄影/素材", "dstFs": "/landing/素材",
                        "createEmptySrcDirs": True}),
    (False, "operations/copyfile", {"srcFs": "PikPak WebDAV:摄影", "srcRemote": "素材",
                                    "dstFs": "/landing", "dstRemote": "素材"}),
])
def test_submits_a_native_copy_job_in_the_default_web_visible_group(rc, directory, endpoint, parameters):
    _, calls, replies, _ = rc
    replies[endpoint] = {"jobid": 9007199254740993, "executeId": "daemon-before-restart"}
    result = _provider(rc).start("PikPak WebDAV", ("摄影",), "素材", directory, Path("/landing/素材"))

    assert result == {"id": "9007199254740993", "instance": "daemon-before-restart"}
    assert len(calls) == 1
    command, payload = calls[0]
    assert command == endpoint
    assert "_group" not in payload and payload["_async"] is True
    assert {key: payload[key] for key in parameters} == parameters
    assert payload["_config"]["Immutable"] is True
    assert payload["_config"]["Links"] is False


@pytest.mark.parametrize("item", [
    {"Name": "导入", "Path": "导入", "IsDir": True},
    {"Name": "导入", "Path": "导入", "IsDir": False},
    {"Name": "另一个位置", "Path": "另一个位置", "IsDir": True},
    None,
])
def test_requires_the_mapped_local_destination_parent_to_exist_in_rclone(rc, item):
    _, calls, replies, _ = rc
    replies["operations/stat"] = {"item": item}
    provider = _provider(rc)
    if item == {"Name": "导入", "Path": "导入", "IsDir": True}:
        provider.require_destination(Path("/landing/导入"))
    else:
        with pytest.raises(transport.RcloneError, match="NAS 目标目录"):
            provider.require_destination(Path("/landing/导入"))
    assert calls == [("operations/stat", {"fs": "/landing", "remote": "导入"})]


@pytest.mark.parametrize(("remote", "parts", "name", "target"), [
    (":s3", (), "one", "/landing/one"),
    ("backup,option=x", (), "one", "/landing/one"),
    ("backup", ("..",), "one", "/landing/one"),
    ("backup", (), "one", "elsewhere/one"),
    ("backup", (), "one", "/landing/../one"),
])
def test_native_copy_rejects_nonliteral_remotes_and_destinations(rc, remote, parts, name, target):
    with pytest.raises(transport.RcloneError):
        _provider(rc).start(remote, parts, name, False, Path(target))
    assert not rc[1]


def _status(instance="daemon-before-restart", **extra):
    return {"id": 42, "executeId": instance, "group": "job/42", "finished": False, "success": False, **extra}


def test_uses_native_per_file_speeds_and_reports_completed_files(rc):
    _, calls, replies, connections = rc
    replies["job/status"] = _status()
    replies["core/stats"] = {
        "bytes": 50, "totalBytes": 100, "speed": 12, "eta": 5,
        "transferring": [
            {"name": "album/photo.jpg", "size": 50, "bytes": 10, "percentage": 20, "speed": 2, "speedAvg": 3},
            {"name": "album/video.mp4", "size": 25, "bytes": 5, "percentage": 20, "speed": 7, "speedAvg": 6},
        ],
    }
    replies["core/transferred"] = {"transferred": [
        {"name": "album/done.jpg", "size": 35, "bytes": 35, "error": "", "checked": False},
        {"name": "excluded.jpg", "size": 1, "bytes": 0, "error": "", "checked": True},
    ]}
    result = _provider(rc).get("42", "daemon-before-restart")

    assert result["status"] == "running" and result["progress"] == 50
    assert result["bytes"] == 50 and result["total_bytes"] == 100 and result["speed"] == 12
    assert [(item["name"], item["status"], item["speed"]) for item in result["files"]] == [
        ("album/photo.jpg", "running", 3),
        ("album/video.mp4", "running", 6),
        ("album/done.jpg", "completed", None),
    ]
    assert calls == [
        ("job/status", {"jobid": "42"}),
        ("core/stats", {"group": "job/42"}),
        ("core/transferred", {"group": "job/42"}),
    ]
    assert len(connections) == 1


def test_stale_daemon_cannot_stop_a_reused_native_job_id(rc):
    _, calls, replies, _ = rc
    replies["job/status"] = _status("new-daemon")

    assert _provider(rc).get("42", "daemon-before-restart") is None
    assert _provider(rc).cancel("42", "daemon-before-restart") is False
    assert calls == [("job/status", {"jobid": "42"})] * 2


def test_stops_the_attributed_native_job_on_the_same_connection(rc):
    _, calls, replies, connections = rc
    replies["job/status"] = _status()
    replies["job/stop"] = {}

    assert _provider(rc).cancel("42", "daemon-before-restart") is True
    assert len(connections) == 1
    assert calls == [("job/status", {"jobid": "42"}), ("job/stop", {"jobid": "42"})]


def test_never_reconnects_to_send_a_stop_after_a_daemon_disconnect(rc, monkeypatch):
    _, calls, replies, connections = rc
    replies["job/status"] = _status()
    read = transport.HTTPConnection.getresponse

    def disconnected(self):
        response = read(self)
        self.close()
        return response

    monkeypatch.setattr(transport.HTTPConnection, "getresponse", disconnected)
    with pytest.raises(transport.RcloneError, match="连接已中断"):
        _provider(rc).cancel("42", "daemon-before-restart")

    assert len(connections) == 1
    assert calls == [("job/status", {"jobid": "42"})]


def test_only_a_definite_missing_job_is_treated_as_expired(rc):
    _, _, replies, _ = rc
    replies["job/status"] = ({"error": "job not found", "path": "job/status", "status": 500}, 500)
    replies["job/list"] = _job_list()
    replies["core/transferred"] = {"transferred": []}
    provider = _provider(rc)
    assert provider.get("42", "daemon-before-restart") is None
    replies["job/status"] = ({"error": "private server fault"}, 500)
    with pytest.raises(transport.RcloneError) as exc:
        provider.get("42", "daemon-before-restart")
    assert "private server fault" not in str(exc.value)


def _file(group, name="片段.mp4", destination="/landing/素材", **fields):
    return {"group": group, "name": name, "size": 100, "bytes": 20,
            "srcFs": "PikPak WebDAV:摄影/素材", "dstFs": destination, **fields}


def _job_list(*running, finished=(), instance="daemon-before-restart"):
    return {"executeId": instance, "jobids": [*running, *finished],
            "runningIds": list(running), "finishedIds": list(finished)}


def test_discovers_default_native_copies_without_a_local_receipt(rc):
    _, calls, replies, _ = rc
    replies["job/list"] = _job_list(42)
    replies["core/stats"] = {"transferring": [
        _file("job/42", speedAvg=8), _file("nfc-cloud-copy-private", name="legacy.mp4"),
    ], "bytes": 20, "totalBytes": 100, "speed": 8}
    replies["core/transferred"] = {"transferred": [_file("job/35", name="封面.jpg", size=20, bytes=20)]}

    active, history = _provider(rc).list_transfers()
    assert (active["id"], active["instance"], active["status"], active["destination"]) == (
        "42", "daemon-before-restart", "running", "/landing/素材",
    )
    assert active["source_path"] == "PikPak WebDAV:摄影/素材/片段.mp4"
    assert active["files"][0]["speed"] == 8
    assert (history["id"], history["status"], history["history_only"], history["files"][0]["status"]) == (
        "35", "unknown", True, "completed",
    )
    assert all(endpoint != "job/stop" for endpoint, _ in calls)


def test_expired_native_job_retains_its_own_history_and_can_clear_just_that_group(rc):
    _, calls, replies, _ = rc
    replies["job/status"] = ({"error": "job not found", "path": "job/status", "status": 500}, 500)
    replies["job/list"] = _job_list()
    replies["core/transferred"] = {"transferred": [
        _file("job/42", name="封面.jpg", size=20, bytes=20),
        _file("job/41", name="other.jpg", destination="/elsewhere"),
    ]}
    replies["core/stats-delete"] = {}
    provider = _provider(rc)

    record = provider.get("42", "daemon-before-restart")
    assert record["destination"] == "/landing/素材"
    assert [item["name"] for item in record["files"]] == ["封面.jpg"]
    assert provider.delete_history("42", "daemon-before-restart")
    assert calls[-1] == ("core/stats-delete", {"group": "job/42"})
    assert provider.delete_history("42", "different-instance") is False
    assert len([call for call in calls if call[0] == "core/stats-delete"]) == 1


def test_native_history_cannot_be_cleared_for_running_or_unobserved_jobs(rc):
    _, calls, replies, _ = rc
    replies["job/status"] = _status()
    replies["job/list"] = _job_list(42)
    provider = _provider(rc)

    assert provider.delete_history("42", "daemon-before-restart") is False
    replies["job/status"] = _status(finished=True, success=True)
    replies["job/list"] = _job_list(finished=(42,))
    replies["core/transferred"] = {"transferred": [_file("job/41")]}
    assert provider.delete_history("42", "daemon-before-restart") is False
    assert all(endpoint != "core/stats-delete" for endpoint, _ in calls)


def test_mixed_remote_and_local_file_targets_provide_no_writable_mapping(rc):
    _, _, replies, _ = rc
    replies["job/status"] = _status()
    replies["core/stats"] = {"transferring": [
        _file("job/42"),
        _file("job/42", name="other.jpg", destination="other-remote:directory"),
    ]}
    replies["core/transferred"] = {"transferred": []}
    assert _provider(rc).get("42", "daemon-before-restart")["destination"] is None
