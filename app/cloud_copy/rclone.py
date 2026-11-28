"""Fixed rclone RC operations for one-way cloud imports."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException, HTTPSConnection
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from app.download_verification.sources import validate_source_url
from app.download_verification.webdav import relative_parts

_MAX_RESPONSE = 256 * 1024
_MAX_PASSWORD = 4096
_COPY_MAX_DURATION = 24 * 60 * 60 * 1_000_000_000
_REMOTE_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}")
_EXECUTION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_GROUP_PREFIX = "nfc-cloud-copy-"
_GROUP_NAME = re.compile(r"nfc-cloud-copy-[0-9a-f]{32}")
_STAGE_NAME = re.compile(r"\.nfc-cloud-copy-[0-9a-f]{32}")
_COUNTERS = ("bytes", "totalBytes", "transfers", "totalTransfers", "errors")
_FAILURE_LABELS = (
    (("no space left on device", "disk quota exceeded"), "NAS 暂存空间不足"),
    (("403 forbidden", "401 unauthorized"), "云端来源拒绝读取"),
    (("directory not found", "object not found"), "未找到云端来源目录或文件"),
    (("i/o timeout", "context deadline exceeded", "max duration"), "复制请求超时"),
)


class RcloneError(ValueError):
    """An import problem safe to show in the task center."""


class RcloneJobNotFound(RcloneError):
    """An authoritative rclone response that the requested native job expired."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_password(path: Path) -> str:
    """Read a short, ordinary secret file without following its final component."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_PASSWORD:
                raise ValueError
            content = stream.read(_MAX_PASSWORD + 1)
            if len(content) > _MAX_PASSWORD:
                raise ValueError
            password = content.decode("utf-8").rstrip("\r\n")
            if not password or any(ord(char) < 32 or ord(char) == 127 for char in password):
                raise ValueError
    except (OSError, ValueError):
        raise RcloneError("rclone 服务密码文件不可用") from None
    return password


def _valid_job_id(value: object) -> bool:
    return type(value) is int and 0 < value < 2**63


def _valid_execution_id(value: object) -> bool:
    return isinstance(value, str) and _EXECUTION_ID.fullmatch(value) is not None


def _speed_or_eta(value: object, default: int | None) -> int | float | None:
    if type(value) is int and 0 <= value < 2**63:
        return value
    if type(value) is float and math.isfinite(value) and 0 <= value < 2**63:
        return value
    return default


def _copy_failure(reason: object) -> str:
    if isinstance(reason, str):
        folded = reason.lower()
        for markers, label in _FAILURE_LABELS:
            if any(marker in folded for marker in markers):
                return label
    return "rclone 报告复制失败"


def _staging_path(destination: str) -> PurePosixPath:
    path = PurePosixPath(destination)
    if not destination.startswith("/") or not relative_parts(destination[1:]) or not _STAGE_NAME.fullmatch(path.name):
        raise ValueError
    return path


class RcloneClient:
    """Talk to one private, authenticated rclone service using fixed requests."""

    def __init__(self, base_url: str, username: str, password_file: Path):
        try:
            self._origin = validate_source_url(base_url)
        except (ValueError, OverflowError):
            raise RcloneError("rclone 服务地址配置无效") from None
        if (not username or len(username) > 255 or ":" in username
                or any(ord(char) < 32 or ord(char) == 127 for char in username)):
            raise RcloneError("请为 rclone 服务配置有效的用户名")
        self._username = username
        self._password_file = Path(password_file)
        if not self._password_file.is_absolute():
            raise RcloneError("rclone 服务密码文件需要使用绝对路径")
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._groups: dict[int, tuple[str, str]] = {}

    def _message(self, payload: dict) -> tuple[bytes, dict[str, str]]:
        password = _read_password(self._password_file)
        basic_auth = base64.b64encode(f"{self._username}:{password}".encode("utf-8")).decode("ascii")
        return json.dumps(payload).encode(), {
            "Authorization": "Basic " + basic_auth, "Content-Type": "application/json",
            "Accept": "application/json", "Accept-Encoding": "identity",
        }

    @staticmethod
    def _http_error(endpoint: str, status: int, response) -> RcloneError:
        if status in (401, 403):
            return RcloneError("rclone 服务拒绝授权，请核对服务凭证")
        if endpoint in ("job/status", "job/stop") and status in (404, 500):
            try:
                item = json.loads(response.read(4097))
            except (ValueError, RecursionError):
                item = None
            if (isinstance(item, dict) and item.get("error") == "job not found"
                    and item.get("path") in (endpoint, "/" + endpoint)):
                return RcloneJobNotFound("rclone 任务记录已不可用")
        if endpoint.startswith("job/") and status == 404:
            return RcloneError("rclone 任务记录已不可用")
        return RcloneError("rclone 服务未接受本次请求")

    def _read_reply(self, endpoint: str, response, response_limit: int) -> dict:
        if response.headers.get("Content-Encoding", "identity") != "identity":
            raise RcloneError("rclone 服务响应格式无效")
        if response.status != 200:
            raise self._http_error(endpoint, response.status, response)
        body = response.read(response_limit + 1)
        if len(body) > response_limit:
            raise RcloneError("rclone 服务响应超过大小限制")
        try:
            result = json.loads(body)
        except (ValueError, RecursionError):
            raise RcloneError("rclone 服务响应格式无效") from None
        if not isinstance(result, dict):
            raise RcloneError("rclone 服务响应格式无效")
        return result

    def _request(self, endpoint: str, payload: dict, *, response_limit: int = _MAX_RESPONSE) -> dict:
        body, headers = self._message(payload)
        request = Request(self._origin + "/" + endpoint, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=10) as response:
                return self._read_reply(endpoint, response, response_limit)
        except HTTPError as exc:
            try:
                raise self._http_error(endpoint, exc.code, exc) from None
            finally:
                exc.close()
        except (OSError, HTTPException):
            raise RcloneError("无法连接 rclone 服务") from None

    @contextmanager
    def _pinned_request(self):
        """Keep identity checks and job actions on one direct daemon connection."""
        origin = urlsplit(self._origin)
        connection_class = HTTPSConnection if origin.scheme == "https" else HTTPConnection
        connection = connection_class(origin.hostname, origin.port, timeout=10)
        try:
            connection.connect()
            socket = connection.sock
            connection.auto_open = False

            def send(endpoint: str, payload: dict, *, response_limit: int = _MAX_RESPONSE) -> dict:
                # A reused numeric native job ID may belong to a restarted daemon.
                if socket is None or connection.sock is not socket:
                    raise RcloneError("rclone 连接已中断，无法确认任务实例")
                body, headers = self._message(payload)
                connection.request("POST", "/" + endpoint, body=body, headers=headers)
                with connection.getresponse() as response:
                    return self._read_reply(endpoint, response, response_limit)

            yield send
        except (OSError, HTTPException):
            raise RcloneError("rclone 任务连接已中断") from None
        finally:
            connection.close()

    def start_copy(self, source: str, destination: str) -> tuple[int, str]:
        """Start only a remote-to-local copy into a fresh staging directory."""
        remote, separator, relative = source.partition(":")
        try:
            if not separator or not _REMOTE_NAME.fullmatch(remote) or not relative_parts(relative):
                raise ValueError
            _staging_path(destination)
        except ValueError:
            raise RcloneError("rclone 复制来源或暂存路径无效") from None
        group = _GROUP_PREFIX + uuid4().hex
        result = self._request("sync/copy", {
            "srcFs": source, "dstFs": destination, "createEmptySrcDirs": True,
            "_async": True, "_group": group,
            "_config": {"Immutable": True, "DryRun": False, "Links": False, "MaxDuration": _COPY_MAX_DURATION},
        })
        job_id, execute_id = result.get("jobid"), result.get("executeId")
        if not _valid_job_id(job_id) or not _valid_execution_id(execute_id):
            raise RcloneError("rclone 未返回可确认的复制任务编号")
        self._groups[job_id] = (execute_id, group)
        return job_id, execute_id

    def require_staging_directory(self, destination: str) -> None:
        """Confirm the daemon can see the underlying folder created by the Worker."""
        try:
            stage = _staging_path(destination)
        except ValueError:
            raise RcloneError("rclone 暂存路径无效") from None
        result = self._request("operations/stat", {"fs": str(stage.parent), "remote": stage.name})
        item = result.get("item")
        if (not isinstance(item, dict) or item.get("IsDir") is not True
                or item.get("Name") != stage.name or item.get("Path") != stage.name):
            raise RcloneError("rclone 无法看到 NAS 暂存目录，请核对挂载映射")

    def status(self, job_id: int, execute_id: str) -> dict:
        """Check the daemon instance before trusting a numeric rclone job ID."""
        if not _valid_job_id(job_id) or not _valid_execution_id(execute_id):
            raise RcloneError("rclone 复制任务编号无效")
        result = self._request("job/status", {"jobid": job_id})
        result_id = result.get("id")
        if not _valid_job_id(result_id) or result_id != job_id or result.get("executeId") != execute_id:
            raise RcloneError("rclone 实例或任务已变化，无法确认复制结果")
        group = result.get("group")
        known = self._groups.get(job_id)
        if (not isinstance(group, str) or not _GROUP_NAME.fullmatch(group)
                or (known is not None and known != (execute_id, group))):
            raise RcloneError("rclone 返回的任务分组不匹配")
        finished, success = result.get("finished"), result.get("success")
        if type(finished) is not bool or type(success) is not bool or (success and not finished):
            raise RcloneError("rclone 返回的任务状态无效")
        self._groups[job_id] = (execute_id, group)
        return {"id": job_id, "executeId": execute_id, "group": group, "finished": finished, "success": success,
                "error": _copy_failure(result.get("error")) if finished and not success else ""}

    def stats(self, job_id: int) -> dict:
        """Return numeric progress only, avoiding raw paths and vendor messages."""
        registered = self._groups.get(job_id) if _valid_job_id(job_id) else None
        if registered is None:
            raise RcloneError("rclone 进度所属的复制任务尚未确认")
        _, group = registered
        result = self._request("core/stats", {"group": group, "short": True})
        counters = {key: result[key] if type(result.get(key)) is int and 0 <= result[key] < 2**63 else 0
                    for key in _COUNTERS}
        return {**counters, "speed": _speed_or_eta(result.get("speed"), 0),
                "eta": _speed_or_eta(result.get("eta"), None)}

    def stop(self, job_id: int, execute_id: str) -> None:
        """Stop only this copy's random group, never a recycled numeric job ID."""
        result = self.status(job_id, execute_id)
        if not result["finished"]:
            self._request("job/stopgroup", {"group": result["group"]})
