from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from app.batch import zspace_recycle
from app.batch.zspace_recycle import ZSpaceRecycleClient, ZSpaceRecycleError


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
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "test-password")

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
    assert "INITIAL_ADMIN_PASSWORD" not in kwargs["env"]
    assert sequence == ["fence", "native", "fence"]
    assert not source.exists()


def test_recycle_binding_uses_only_deployment_configuration(recycler, monkeypatch):
    def never_called(*args, **kwargs):
        pytest.fail("binding the preview must not call the CLI")

    monkeypatch.setattr(subprocess, "run", never_called)
    binding = recycler.binding_id()
    assert binding == replace(recycler).binding_id()
    assert replace(recycler, remote_root="/another-pool/my/data").binding_id() != binding
    assert replace(recycler, profile="different").binding_id() != binding


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
