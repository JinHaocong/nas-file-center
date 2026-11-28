"""OpenList's native file and copy task interfaces."""
from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Literal
from urllib.parse import urlencode

from app.config import Settings
from app.download_verification.models import DownloadVerificationSource
from app.download_verification.sources import AListAPIClient, source_secret_path
from app.download_verification.webdav import WebDAVError, relative_parts, segment


_TASK_ID = re.compile(r"[A-Za-z0-9_.~-]{1,128}")
_COPY_TASK_STATES = {
    0: "queued", 1: "running", 2: "completed", 3: "cancel_requested",
    4: "cancelled", 5: "queued", 6: "running", 7: "failed", 8: "queued", 9: "queued",
}


class OpenListError(ValueError):
    """A safe provider error for callers, without OpenList response details."""


def _logical_parts(path: str) -> tuple[str, ...]:
    if not path.startswith("/"):
        raise WebDAVError("Expected an absolute OpenList path")
    return relative_parts(path[1:])


def _linkage(name: str) -> tuple[str | None, str | None]:
    # Native task names use FileTransferTask.GetName(). The second path is the destination
    # directory, including for child tasks, so the source leaf gives the target.
    if not name.startswith("copy [") or name.count(") to [") != 1 or not name.endswith(")"):
        return None, None
    src, dst = name[6:-1].split(") to [")
    if src.count("](") != 1 or dst.count("](") != 1:
        return None, None
    src_mount, src_actual = src.split("](")
    dst_mount, dst_actual = dst.split("](")
    try:
        source = _logical_parts(src_mount) + _logical_parts(src_actual)
        destination = _logical_parts(dst_mount) + _logical_parts(dst_actual)
    except WebDAVError:
        return None, None
    if not source:
        return None, None
    return "/" + "/".join(source), "/" + "/".join((*destination, source[-1]))


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _normalize_task(row: dict) -> dict:
    task_id = row.get("id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise OpenListError("OpenList 返回的任务编号无效。")
    raw_name = row.get("name")
    source, destination = _linkage(raw_name) if isinstance(raw_name, str) else (None, None)
    state = row.get("state")
    status = _COPY_TASK_STATES.get(state, "unknown") if type(state) is int else "unknown"
    progress = row.get("progress")
    if type(progress) not in (float, int) or not 0 <= progress <= 100 or not math.isfinite(progress):
        progress = None
    size = row.get("total_bytes")
    if type(size) is not int or not 0 <= size <= 2**63 - 1:
        size = None
    phase = row.get("status")
    directory = None
    if isinstance(phase, str):
        if phase.startswith("src object is dir,"):
            directory = True
        elif phase in ("uploading", "getting src object link"):
            directory = False
    if size:
        directory = False
    return {
        "id": task_id,
        "name": source.rsplit("/", 1)[-1] if source else "OpenList 复制任务",
        "status": status, "progress": float(progress) if progress is not None else None,
        "total_bytes": size, "error": "OpenList 报告复制失败。" if status == "failed" else None,
        "source_path": source, "destination_path": destination, "is_directory": directory,
        "started_at": _timestamp(row.get("start_time")), "ended_at": _timestamp(row.get("end_time")),
    }


class OpenListProvider:
    def __init__(self, source: DownloadVerificationSource, settings: Settings, *, opener=None):
        if source.provider != "openlist" or not source.active:
            raise OpenListError("OpenList 来源不可用。")
        self._username = source.username
        try:
            secret = source_secret_path(settings.config_dir, source.secret_file) if source.secret_file else None
            self._client = AListAPIClient(
                base_url=source.base_url, username=source.username,
                password_file=str(secret) if secret else None, opener=opener,
                session_config_dir=settings.config_dir, session_secret_name=source.secret_file,
            )
        except (ValueError, OSError):
            raise OpenListError("无法连接 OpenList 或登录已失效。") from None

    def entries(self, path: tuple[str, ...]) -> list[dict]:
        try:
            return [
                {"name": item_path[-1], "kind": item["kind"], "size": item["size"]}
                for item_path, item in self._client.list_directory(path).items()
            ]
        except WebDAVError:
            raise OpenListError("无法读取 OpenList 目录。") from None

    def require_destination(self, path: tuple[str, ...]) -> None:
        """Verify that OpenList resolves the configured NAS target to a Local directory."""
        self._require_account()
        if not path:
            raise OpenListError("OpenList 的 NAS 目标必须是本地目录。")
        try:
            qualified = "/" + "/".join(map(segment, path))
            reply = self._client._request_json("POST", "/api/fs/get", {"path": qualified, "password": ""})
        except WebDAVError:
            raise OpenListError("无法读取 OpenList 的 NAS 本地目录。") from None
        data = reply.get("data") if reply else None
        if not isinstance(data, dict) or data.get("is_dir") is not True or data.get("provider") != "Local":
            raise OpenListError("OpenList 的 NAS 目标必须是本地目录。")

    def start(
        self, path: tuple[str, ...], names: tuple[str, ...], destination: tuple[str, ...],
    ) -> list[dict]:
        """Submit a native batch copy without merge or overwrite."""
        self._require_account()
        if not names or not destination or len(set(names)) != len(names):
            raise OpenListError("请选择有效的 OpenList 文件和 NAS 目标目录。")
        try:
            src = "/" + "/".join(map(segment, path))
            dst = "/" + "/".join(map(segment, destination))
            validated_names = [segment(name) for name in names]
        except WebDAVError:
            raise OpenListError("OpenList 路径格式无效。") from None
        try:
            result = self._client._request_json("POST", "/api/fs/copy", {
                "src_dir": src, "dst_dir": dst, "names": validated_names,
                "overwrite": False, "skip_existing": False, "merge": False, "follow_seed": False,
            })
        except WebDAVError:
            raise OpenListError("无法确认 OpenList 复制任务，请在原服务查看任务后再重试。") from None
        data = result.get("data") if result else None
        if isinstance(data, dict) and isinstance(data.get("tasks"), list) and data["tasks"]:
            tasks = data["tasks"]
            if all(isinstance(task, dict) and task.get("creator") == self._username for task in tasks):
                normalized = [_normalize_task(task) for task in tasks]
                if len({task["id"] for task in normalized}) == len(normalized):
                    return normalized
        if isinstance(data, dict) and data.get("message") == "Copy operations completed immediately":
            return []
        raise OpenListError("OpenList 未返回可确认的复制任务，请查看原服务。")

    def _require_account(self) -> None:
        if not self._username:
            raise OpenListError("OpenList 的复制操作需要登录账号。")

    def _task_request(
        self, action: Literal["info", "cancel", "delete"], job_id: str, *, allow_missing: bool = False,
    ) -> dict | None:
        self._require_account()
        if not isinstance(job_id, str) or not _TASK_ID.fullmatch(job_id):
            raise OpenListError("OpenList 任务编号无效。")
        path = "/api/task/copy/" + action + "?" + urlencode({"tid": job_id})
        try:
            return self._client._request_json("POST", path, None, allow_missing=allow_missing)
        except WebDAVError:
            raise OpenListError("OpenList 任务接口不可用。") from None

    def get(self, job_id: str) -> dict | None:
        """Fetch a single native copy record when still retained by the service."""
        result = self._task_request("info", job_id, allow_missing=True)
        if result is None:
            return None
        row = result.get("data")
        if not isinstance(row, dict) or row.get("id") != job_id:
            raise OpenListError("OpenList 返回了无法确认的任务。")
        return _normalize_task(row) if row.get("creator") == self._username else None

    def list_tasks(self, *, active_only: bool = False) -> list[dict]:
        """Find this account's native copy tasks, including recursive child tasks."""
        self._require_account()
        records = {}
        try:
            for group in (("undone",) if active_only else ("undone", "done")):
                result = self._client._request_json("GET", "/api/task/copy/" + group, None)
                rows = result.get("data") if result else None
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                    raise OpenListError("OpenList 返回的任务列表无效。")
                for row in rows:
                    if row.get("creator") == self._username:
                        record = _normalize_task(row)
                        records[record["id"]] = record
        except WebDAVError:
            raise OpenListError("无法读取 OpenList 复制任务。") from None
        return list(records.values())

    def cancel(self, job_id: str) -> None:
        self._task_request("cancel", job_id)

    def delete(self, job_id: str) -> None:
        """Delete a native copy record; no filesystem operation is involved."""
        self._task_request("delete", job_id, allow_missing=True)
