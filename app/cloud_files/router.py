from pathlib import PurePosixPath
import os
from typing import Annotated, Literal
from unicodedata import normalize

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import require_admin_user
from app.cloud_copy.handler import CloudCopyError, _protected, _reserved_parts, open_destination_parent, require_new_folder
from app.cloud_copy.rclone import RcloneError
from app.download_verification.webdav import WebDAVError, relative_parts, segment

from .configuration import public_configuration, read_configuration
from .openlist import OpenListError, OpenListProvider
from .rclone import RcloneProvider
from .transfers import parse_task_id, transfer_view


router = APIRouter(prefix="/api/cloud-files", tags=["cloud-files"], dependencies=[Depends(require_admin_user)])
Provider = Literal["openlist", "rclone"]
Remote = Annotated[str | None, Query(max_length=128)]
Relative = Annotated[str, Query(max_length=4096)]
_UPSTREAM_ERRORS = (RcloneError, OpenListError, WebDAVError, OSError)


class NewTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider
    remote: str | None = Field(default=None, max_length=128)
    path: str = Field(default="", max_length=4096)
    names: list[Annotated[str, Field(min_length=1, max_length=255)]] = Field(min_length=1, max_length=30)
    destination: str = Field(min_length=1, max_length=4096)


def _context(request):
    settings = request.app.state.settings
    with request.app.state.service.SessionLocal() as session:
        return settings, read_configuration(session, settings)


def _upstream():
    return HTTPException(502, "云端服务响应异常。请检查连接、账号权限或原生任务。")


def _adapter(provider, config, settings):
    if provider == "openlist" and config.openlist_source:
        return OpenListProvider(config.openlist_source, settings)
    if provider == "rclone" and config.rclone_enabled:
        return RcloneProvider(base_url=config.rclone_origin, username=settings.cloud_copy_rclone_username,
                              password_file=settings.cloud_copy_rclone_password_file)
    raise HTTPException(503, "此云端来源尚未配置。")


def _remotes(adapter, settings):
    allow = {name.strip() for name in settings.cloud_files_rclone_remotes.split(",") if name.strip()}
    return [name for name in adapter.remotes() if not allow or name in allow]


def _source_parts(provider, config, value):
    try:
        parts = relative_parts(value)
        if _reserved_parts(parts):
            raise ValueError
    except ValueError:
        raise HTTPException(422, "无效的云端目录。") from None
    if provider == "openlist" and config.openlist_root and (
        PurePosixPath("/", *parts).is_relative_to(config.openlist_root)
    ):
        raise HTTPException(422, "请从 OpenList 的云端存储选择文件。")
    return parts


def _entries(adapter, provider, parts, remote, config, settings):
    if provider == "rclone":
        if not remote or remote not in _remotes(adapter, settings):
            raise HTTPException(422, "请选择现有的 rclone 远程存储。")
        values = adapter.entries(remote, parts)
    else:
        if remote is not None:
            raise HTTPException(422, "OpenList 不使用 rclone 远程存储。")
        mount = config.openlist_root
        values = [item for item in adapter.entries(parts)
                  if not PurePosixPath("/", *parts, item["name"]).is_relative_to(mount)]
    return [entry for entry in values if not _reserved_parts((entry["name"],))]


def _case_key(name):
    return normalize("NFC", name).casefold()


def _selection(values):
    try:
        names = tuple(segment(name) for name in values)
        if (_reserved_parts(names) or any(len(os.fsencode(name)) > 255 for name in names)
                or len(set(map(_case_key, names))) != len(names)):
            raise ValueError
    except (ValueError, UnicodeError):
        raise HTTPException(422, "请选择名称有效且没有重名的文件。") from None
    return names


def _validate_destination(config, settings, destination, names):
    try:
        with open_destination_parent(config, settings, destination, names[0]) as (path, fd):
            requested = set(map(_case_key, names))
            for name in names:
                if _protected(path / name, settings):
                    raise HTTPException(422, "目标文件位于系统保留目录。")
                require_new_folder(fd, name)
            with os.scandir(fd) as existing:
                if any(_case_key(item.name) in requested for item in existing):
                    raise HTTPException(409, "NAS 目标位置已有同名文件或目录。")
            return path
    except CloudCopyError as exc:
        raise HTTPException(409, str(exc)) from None
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(422, "请选择存放根目录下的实际 NAS 目录。") from None


def _lookup(adapter, provider, native_id, instance):
    return adapter.get(native_id, instance) if provider == "rclone" else adapter.get(native_id)


def _task(task_id, config, settings):
    try:
        provider, native_id, instance = parse_task_id(task_id)
    except ValueError:
        raise HTTPException(404, "找不到这笔原生传输。") from None
    try:
        adapter = _adapter(provider, config, settings)
        record = _lookup(adapter, provider, native_id, instance)
        view = transfer_view(provider, record, config, instance=instance) if record else None
    except _UPSTREAM_ERRORS:
        raise _upstream() from None
    if view is None:
        raise HTTPException(404, "这笔任务尚未在原服务的传输列表中出现，或已被清理。")
    return adapter, provider, native_id, instance, record, view


def _submit(adapter, provider, remote, parts, items, target):
    if provider == "openlist":
        if any(delimiter in str(value) for delimiter in ("](", ") to [")
               for value in (*parts, target, *(item["name"] for item in items))):
            raise HTTPException(422, "这批名称包含 OpenList 任务路径的分隔符，无法准确追踪原生任务。")
        adapter.require_destination(target.parts[1:])
        return adapter.start(parts, tuple(item["name"] for item in items), target.parts[1:]), None

    adapter.require_destination(target)
    submitted = []
    for item in items:
        try:
            ref = adapter.start(remote, parts, item["name"], item["kind"] == "directory", target / item["name"])
        except _UPSTREAM_ERRORS:
            return submitted, "部分提交结果未确认，请查看 rclone 的传输列表后再重试。"
        submitted.append({**ref, "name": item["name"], "status": "queued", "files": [],
                          "source": "/".join(parts), "remote": remote})
    return submitted, None


@router.get("/configuration")
def configuration(request: Request):
    settings, config = _context(request)
    return public_configuration(config, settings)


@router.get("/rclone/remotes")
def rclone_remotes(request: Request):
    settings, config = _context(request)
    try:
        adapter = _adapter("rclone", config, settings)
        return {"items": [{"name": name} for name in _remotes(adapter, settings)]}
    except _UPSTREAM_ERRORS:
        raise _upstream() from None


@router.get("/entries")
def entries(request: Request, provider: Provider, remote: Remote = None, path: Relative = ""):
    settings, config = _context(request)
    parts = _source_parts(provider, config, path)
    try:
        adapter = _adapter(provider, config, settings)
        return {"items": _entries(adapter, provider, parts, remote, config, settings)}
    except _UPSTREAM_ERRORS:
        raise _upstream() from None


@router.post("/transfers", status_code=202)
def start_transfer(request: Request, payload: NewTransfer):
    settings, config = _context(request)
    if not settings.allow_mutation:
        raise HTTPException(403, "当前部署为只读模式，无法复制到 NAS。")
    if config.local_root is None:
        raise HTTPException(503, "请先配置 NAS 存放根目录。")
    parts = _source_parts(payload.provider, config, payload.path)
    names = _selection(payload.names)
    destination = _validate_destination(config, settings, payload.destination, names)
    try:
        adapter = _adapter(payload.provider, config, settings)
        listed = {item["name"]: item for item in _entries(
            adapter, payload.provider, parts, payload.remote, config, settings,
        )}
        if any(name not in listed for name in names):
            raise HTTPException(409, "云端文件列表已变化，请刷新后重新选择。")
        provider_root = config.rclone_root if payload.provider == "rclone" else config.openlist_root
        target = provider_root / destination.relative_to(config.local_root)
        _validate_destination(config, settings, payload.destination, names)
        records, message = _submit(adapter, payload.provider, payload.remote, parts,
                                   [listed[name] for name in names], target)
    except _UPSTREAM_ERRORS:
        raise _upstream() from None
    if not records:
        raise HTTPException(502, message or "原生服务未返回任务编号，请查看对应服务的传输列表。")
    view = transfer_view(payload.provider, records[0], config, destination=str(destination))
    view.update(native_ids=[record["id"] for record in records],
                names=list(names), error=message, submitted_count=len(records))
    return view


@router.get("/transfers")
def list_transfers(request: Request):
    settings, config = _context(request)
    items, errors = [], {}
    for provider, enabled in (("openlist", config.openlist_source is not None), ("rclone", config.rclone_enabled)):
        if not enabled or not config.local_root:
            continue
        try:
            adapter = _adapter(provider, config, settings)
            records = adapter.list_tasks() if provider == "openlist" else adapter.list_transfers()
            items.extend(view for record in records if (view := transfer_view(provider, record, config)) is not None)
        except _UPSTREAM_ERRORS:
            errors[provider] = "暂时无法读取原生任务列表。"
    items.sort(key=lambda item: (not item["can_delete"], item["created_at"]), reverse=True)
    return {"items": items, "errors": errors}


@router.get("/transfers/{transfer_id}")
def transfer_status(request: Request, transfer_id: str):
    settings, config = _context(request)
    return _task(transfer_id, config, settings)[-1]


@router.post("/transfers/{transfer_id}/cancel")
def cancel_transfer(request: Request, transfer_id: str):
    settings, config = _context(request)
    adapter, provider, native_id, instance, _, view = _task(transfer_id, config, settings)
    if not view["can_cancel"]:
        raise HTTPException(409, "这笔原生任务已结束或正在取消。")
    try:
        if provider == "openlist":
            adapter.cancel(native_id)
        elif not adapter.cancel(native_id, instance):
            raise HTTPException(409, "rclone 任务已结束，请刷新。")
    except _UPSTREAM_ERRORS:
        raise _upstream() from None
    return {**view, "status": "cancel_requested", "speed": None, "can_cancel": False}


@router.delete("/transfers/{transfer_id}")
def delete_transfer(request: Request, transfer_id: str):
    settings, config = _context(request)
    adapter, provider, native_id, instance, _, view = _task(transfer_id, config, settings)
    if not view["can_delete"]:
        raise HTTPException(409, "请先等待原生传输结束。")
    try:
        if provider == "openlist":
            adapter.delete(native_id)
        elif not adapter.delete_history(native_id, instance):
            raise HTTPException(409, "rclone 的传输记录已变化，请刷新。")
    except _UPSTREAM_ERRORS:
        raise _upstream() from None
    return {"deleted": True}
