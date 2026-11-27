from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest

from app.batch import zspace_recycle
from app.batch.zspace_recycle import PROBE_NAME, ZSpaceRecycleClient, ZSpaceRecycleError


@pytest.fixture
def recycler(tmp_path):
    return ZSpaceRecycleClient(Path("/opt/zspace/zspace-cli"), "media", tmp_path.resolve(), "/pool/my/data",
                              cli_home=tmp_path.resolve().parent / "zspace-private")


def file_identity(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def test_recycles_only_the_confirmed_native_path(tmp_path, monkeypatch):
    local_root = tmp_path.resolve()
    source = local_root / "摄影集" / "下载地址.url"
    source.parent.mkdir()
    source.write_text("[InternetShortcut]", encoding="utf-8")
    info = source.stat()
    calls = []
    sequence = []

    def native_cli(args, **kwargs):
        calls.append((args, kwargs))
        sequence.append("native")
        source.unlink()
        return subprocess.CompletedProcess(args, 0, stdout=b'{"ok":true,"data":{}}')

    monkeypatch.setattr(subprocess, "run", native_cli)
    recycler = ZSpaceRecycleClient(Path("/opt/zspace/zspace-cli"), "media", local_root, "/pool/my/data")
    recycler.recycle(source, identity=(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns),
                     fence=lambda: sequence.append("fence"))

    [(argv, kwargs)] = calls
    assert argv[:3] == ["/opt/zspace/zspace-cli", "--profile", "media"]
    assert argv[argv.index("file"):] == ["file", "delete", "--params", argv[-2], "--yes"]
    assert json.loads(argv[-2]) == {"paths": ["/pool/my/data/摄影集/下载地址.url"]}
    assert not kwargs.get("shell")
    assert sequence == ["fence", "native", "fence"]
    assert not source.exists()


def test_mapping_probe_is_local_until_verified_and_profile_changes_change_binding(recycler, monkeypatch):
    marker = b"b" * 64 + b"\n"
    (recycler.local_root / PROBE_NAME).write_bytes(marker)
    calls = []

    def native_cli(args, **kwargs):
        calls.append((args, kwargs))
        response = {"ok": True, "data": {
            "path": "/pool/my/data/" + PROBE_NAME, "offset": 0, "size": len(marker), "bytes": len(marker),
            "truncated": False, "next_offset": None, "encoding": "base64",
            "content": base64.b64encode(marker).decode("ascii"),
        }}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(response).encode())

    monkeypatch.setattr(subprocess, "run", native_cli)
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "test-password")
    binding = recycler.binding_id()
    assert not calls
    assert binding == recycler.verify_mapping()
    [(argv, kwargs)] = calls
    assert argv[argv.index("file"):-1] == ["file", "read", "--params"]
    assert json.loads(argv[-1]) == {"path": "/pool/my/data/" + PROBE_NAME, "max_bytes": 66, "encoding": "base64"}
    assert kwargs["env"]["ZSPACE_CLI_HOME"] == str(recycler.cli_home)
    assert "INITIAL_ADMIN_PASSWORD" not in kwargs["env"]

    alternative = ZSpaceRecycleClient(recycler.executable, "different", recycler.local_root, recycler.remote_root,
                                      recycler.cli_home)
    assert alternative.binding_id() != binding


@pytest.mark.parametrize("payload", [
    {"ok": True, "data": {"content": "A" * 88}},
    {"ok": True, "data": {"content_base64": "not base64"}},
    {"ok": True, "data": None},
    {"ok": True, "data": {
        "path": "/pool/my/data/" + PROBE_NAME, "offset": 0, "size": 100, "bytes": 64,
        "truncated": True, "next_offset": 64, "encoding": "base64", "content": base64.b64encode(b"a" * 64).decode(),
    }},
])
def test_mapping_probe_rejects_unconfirmed_remote_content(recycler, monkeypatch, payload):
    (recycler.local_root / PROBE_NAME).write_bytes(b"a" * 64)
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps(payload).encode(),
    ))
    with pytest.raises(ZSpaceRecycleError, match="验证标记与容器路径不匹配"):
        recycler.verify_mapping()


def test_mapping_refuses_symlinked_probe(recycler):
    other = recycler.local_root / "marker"
    other.write_bytes(b"a" * 64)
    (recycler.local_root / PROBE_NAME).symlink_to(other)
    with pytest.raises(ZSpaceRecycleError, match="验证标记缺失、无效或已变化"):
        recycler.binding_id()


@pytest.mark.parametrize("relative", ["../escaped.url", ".recycle/my/previous.url", "bad\\name.url", ""])
def test_rejects_unsafe_path_mappings(recycler, relative):
    with pytest.raises(ValueError):
        recycler.remote_path(recycler.local_root / relative)


def test_refuses_modified_file_before_native_command(recycler, monkeypatch):
    source = recycler.local_root / "下载地址.url"
    source.write_bytes(b"captured")
    identity = file_identity(source)
    source.write_bytes(b"different bytes")

    def never_called(*args, **kwargs):
        pytest.fail("the modified file must not be sent to the recycle command")

    monkeypatch.setattr(subprocess, "run", never_called)
    with pytest.raises(ZSpaceRecycleError, match="回收文件已变化"):
        recycler.recycle(source, identity=identity, fence=lambda: None)
    assert source.read_bytes() == b"different bytes"


@pytest.mark.parametrize("returncode,stdout,message", [
    (1, b'{"private":"secret"}', "极空间命令未返回成功"),
    (0, b'{"ok":false,"message":"secret"}', "极空间命令未确认成功"),
    (0, b'secret failed JSON', "无法验证的结果"),
    (0, b'{"ok":true,"data":{"task_id":"123"}}', "原文件仍在"),
])
def test_accepted_or_failed_request_does_not_mutate_or_retry(recycler, monkeypatch, returncode, stdout, message):
    source = recycler.local_root / "下载地址.url"
    source.write_bytes(b"confirmed")
    calls = []

    def native_cli(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", native_cli)
    monkeypatch.setattr(zspace_recycle, "_CONFIRM_TIMEOUT", 0)
    with pytest.raises(ZSpaceRecycleError, match=message) as error:
        recycler.recycle(source, identity=file_identity(source), fence=lambda: None)
    assert len(calls) == 1
    assert "secret" not in str(error.value)
    assert source.read_bytes() == b"confirmed"
