"""Contract tests against the public OpenList HTTP API boundary."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from app.cloud_files.openlist import OpenListError, OpenListProvider
from app.download_verification.sources import write_secret


class SourceReply(io.BytesIO):
    status = 200
    headers = {}

    def __init__(self, data, *, code=200):
        super().__init__(json.dumps({"code": code, "data": data}, ensure_ascii=False).encode())


class SourceServer:
    def __init__(self, replies):
        self.replies = iter(replies)

    def open(self, request, *, timeout):
        path, method, data, reply = next(self.replies)
        url = urlsplit(request.full_url)
        assert url.netloc == "openlist:5244"
        assert url.path + ("?" + url.query if url.query else "") == path
        assert request.get_method() == method
        assert (json.loads(request.data) if request.data else None) == data
        if path != "/api/auth/login":
            assert request.get_header("Authorization") == "source-token"
        if isinstance(reply, BaseException):
            raise reply
        return reply


@pytest.fixture
def openlist(tmp_path):
    def connect(*replies):
        secret_name = "source-" + "a" * 32 + ".secret"
        write_secret(tmp_path, secret_name, "source-password")
        source = SimpleNamespace(provider="openlist", active=True, base_url="http://openlist:5244",
                                 username="copy-user", secret_file=secret_name)
        server = SourceServer([
            ("/api/auth/login", "POST", {"username": "copy-user", "password": "source-password"},
             SourceReply({"token": "source-token"})),
            *replies,
        ])
        return OpenListProvider(source, SimpleNamespace(config_dir=tmp_path), opener=server)
    return connect


def test_native_listing_includes_files_and_directories(openlist):
    client = openlist(("/api/fs/list", "POST",
                       {"path": "/项目资料", "password": "", "page": 1, "per_page": 200, "refresh": False},
                       SourceReply({"total": 2, "content": [
                           {"name": "照片", "is_dir": True, "size": 0},
                           {"name": "项目清单.xlsx", "is_dir": False, "size": 317440},
                       ]})))
    assert client.entries(("项目资料",)) == [
        {"name": "照片", "kind": "directory", "size": None},
        {"name": "项目清单.xlsx", "kind": "file", "size": 317440},
    ]


def native_task(task_id, name, *, state=1, status="uploading", progress=25, total_bytes=4096, creator="copy-user", **extra):
    return {"id": task_id, "name": name, "state": state, "status": status, "progress": progress,
            "total_bytes": total_bytes, "creator": creator, **extra}


def test_copy_submits_the_native_request_without_overwriting_and_keeps_opaque_ids(openlist):
    task = native_task("9007199254740993009", "copy [/云盘](/资料/图.jpg) to [/NAS](/导入)")
    client = openlist(("/api/fs/copy", "POST",
                       {"src_dir": "/云盘/资料", "dst_dir": "/NAS/导入", "names": ["图.jpg"],
                        "overwrite": False, "skip_existing": False, "merge": False, "follow_seed": False},
                       SourceReply({"tasks": [task]})))
    assert client.start(("云盘", "资料"), ("图.jpg",), ("NAS", "导入")) == [{
        "id": "9007199254740993009", "name": "图.jpg", "status": "running",
        "progress": 25.0, "total_bytes": 4096, "error": None,
        "source_path": "/云盘/资料/图.jpg", "destination_path": "/NAS/导入/图.jpg",
        "is_directory": False, "started_at": None, "ended_at": None,
    }]


def test_task_list_links_recursive_children_without_leaking_other_users_or_raw_errors(openlist):
    child = native_task("child-1", "copy [/云盘](/旅行/2025/拍摄.mov) to [/NAS](/导入/旅行/2025)",
                        start_time="2026-11-28T02:00:00.123Z")
    directory = native_task("parent", "copy [/云盘](/旅行) to [/NAS](/导入)",
                            state=2, status="src object is dir, added all copy tasks of objs",
                            progress=100, total_bytes=0, end_time="2026-11-28T10:00:00+08:00")
    failed = native_task("child-2", "copy [/云盘](/旅行/坏图.jpg) to [/NAS](/导入/旅行)",
                         state=7, error="could not fetch http://user:secret@example.invalid/file")
    other = native_task("other", "copy [/云盘](/旅行/另一张.jpg) to [/NAS](/导入/旅行)", creator="other-user")
    client = openlist(
        ("/api/task/copy/undone", "GET", None, SourceReply([child, other])),
        ("/api/task/copy/done", "GET", None, SourceReply([directory, failed])),
    )
    records = {item["id"]: item for item in client.list_tasks()}
    assert set(records) == {"parent", "child-1", "child-2"}
    assert records["child-1"]["source_path"] == "/云盘/旅行/2025/拍摄.mov"
    assert records["child-1"]["destination_path"] == "/NAS/导入/旅行/2025/拍摄.mov"
    assert records["child-1"]["started_at"] == "2026-11-28T02:00:00.123Z"
    assert records["parent"]["is_directory"] is True
    assert records["parent"]["status"] == "completed"
    assert records["parent"]["ended_at"] == "2026-11-28T10:00:00+08:00"
    assert records["child-2"]["status"] == "failed"
    assert records["child-2"]["error"] == "OpenList 报告复制失败。"


def test_status_cancel_and_delete_call_native_task_endpoints(openlist):
    task_id = "f-h_8"
    client = openlist(
        (f"/api/task/copy/info?tid={task_id}", "POST", None,
         SourceReply(native_task(task_id, "copy [/云盘](/图.jpg) to [/NAS](/)", state=3))),
        (f"/api/task/copy/cancel?tid={task_id}", "POST", None, SourceReply(None)),
        (f"/api/task/copy/delete?tid={task_id}", "POST", None, SourceReply(None)),
        (f"/api/task/copy/info?tid={task_id}", "POST", None, SourceReply(None, code=404)),
    )
    assert client.get(task_id)["status"] == "cancel_requested"
    client.cancel(task_id)
    client.delete(task_id)
    assert client.get(task_id) is None


def test_bad_relative_names_and_task_ids_never_make_provider_requests(openlist):
    client = openlist()
    with pytest.raises(OpenListError, match="路径格式"):
        client.start(("云盘",), ("子目录/照片.jpg",), ("NAS",))
    with pytest.raises(OpenListError, match="任务编号"):
        client.cancel("task&tid=other")


def test_copy_transport_failure_is_reported_without_retry_or_upstream_details(openlist):
    client = openlist(("/api/fs/copy", "POST",
                       {"src_dir": "/云盘", "dst_dir": "/NAS", "names": ["图.jpg"],
                        "overwrite": False, "skip_existing": False, "merge": False, "follow_seed": False},
                       TimeoutError("https://example.invalid/file?token=secret")))
    with pytest.raises(OpenListError) as raised:
        client.start(("云盘",), ("图.jpg",), ("NAS",))
    assert str(raised.value) == "无法确认 OpenList 复制任务，请在原服务查看任务后再重试。"


@pytest.mark.parametrize(("is_dir", "provider", "accepted"), [
    (True, "Local", True),
    (False, "Local", False),
    (True, "WebDav", False),
    (True, None, False),
])
def test_target_preflight_requires_an_openlist_local_directory(openlist, is_dir, provider, accepted):
    client = openlist(("/api/fs/get", "POST", {"path": "/NAS/导入", "password": ""},
                       SourceReply({"is_dir": is_dir, "provider": provider})))
    if accepted:
        client.require_destination(("NAS", "导入"))
    else:
        with pytest.raises(OpenListError, match="本地目录"):
            client.require_destination(("NAS", "导入"))


def test_active_task_list_can_read_pending_tasks_without_loading_completed_history(openlist):
    pending = native_task("copy-1", "copy [/云盘](/图.jpg) to [/NAS](/导入)", state=0)
    client = openlist(("/api/task/copy/undone", "GET", None, SourceReply([pending])))
    assert [record["id"] for record in client.list_tasks(active_only=True)] == ["copy-1"]
