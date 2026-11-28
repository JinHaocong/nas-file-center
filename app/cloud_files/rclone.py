"""Fixed native rclone operations for the Cloud Files workspace."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re

from app.cloud_copy.rclone import (
    RcloneClient, RcloneError, RcloneJobNotFound, _COPY_MAX_DURATION, _copy_failure,
    _speed_or_eta, _valid_execution_id, _valid_job_id,
)
from app.download_verification.webdav import relative_parts, segment

# Match configured names, including spaces, without accepting on-the-fly
# backends or option-bearing strings in rclone's filesystem syntax.
_REMOTE_NAME = re.compile(r"[\w.+@]+(?:[ -]+[\w.+@-]+)*")
_TEXT_JOB_ID = re.compile(r"[1-9][0-9]{0,18}")
_NATIVE_GROUP = re.compile(r"job/([1-9][0-9]{0,18})")
_LIST_RESPONSE_LIMIT = 4 * 1024 * 1024


class _InstanceChanged(RcloneError):
    """The same numeric ID belongs to a different rclone daemon."""


def _valid_remote(name: object) -> bool:
    return isinstance(name, str) and len(name) <= 128 and _REMOTE_NAME.fullmatch(name) is not None


def _literal_path(parts: tuple[str, ...]) -> str:
    try:
        path = "/".join(segment(part) for part in parts)
        if relative_parts(path) != parts or any(ord(char) == 127 for char in path):
            raise ValueError
        path.encode()
        return path
    except (ValueError, TypeError):
        raise RcloneError("rclone 文件路径无效") from None


def _quantity(value: object) -> int | None:
    return value if type(value) is int and 0 <= value < 2**63 else None


def _literal_fs(remote: str, path: tuple[str, ...] = ()) -> str:
    if not _valid_remote(remote):
        raise RcloneError("rclone 远程存储名称无效")
    return remote + ":" + _literal_path(path)


def _validate_destination(path: Path) -> None:
    if path.anchor != "/" or len(path.parts) < 2:
        raise RcloneError("rclone 的 NAS 目标路径无效")
    _literal_path(path.parts[1:])


def _validate_job_reference(job_id: str, instance: str) -> None:
    if (not isinstance(job_id, str) or not _TEXT_JOB_ID.fullmatch(job_id)
            or (len(job_id) == 19 and job_id > "9223372036854775807")
            or not _valid_execution_id(instance)):
        raise RcloneError("rclone 任务编号无效")


def _completion(bytes_transferred: int | None, total: int | None) -> float | None:
    if bytes_transferred is None or not total:
        return None
    return min(100.0, 100 * bytes_transferred / total)


def _date(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return value if datetime.fromisoformat(value).year > 1 else None
    except ValueError:
        return None


def _normalized_file(raw: object, *, active: bool) -> dict | None:
    if not isinstance(raw, dict) or raw.get("checked") is True:
        return None
    try:
        name = _literal_path(relative_parts(raw.get("name")))
    except ValueError:
        return None
    if not name:
        return None
    count, total = _quantity(raw.get("bytes")), _quantity(raw.get("size"))
    if active:
        status, failure = "running", None
        progress = _speed_or_eta(raw.get("percentage"), _completion(count, total))
        if progress is not None:
            progress = min(100.0, progress)
        speed = _speed_or_eta(raw.get("speedAvg"), _speed_or_eta(raw.get("speed"), None))
        eta = _speed_or_eta(raw.get("eta"), None)
    else:
        is_failed = isinstance(raw.get("error"), str) and bool(raw["error"])
        status = "failed" if is_failed else "completed"
        failure = _copy_failure(raw["error"]) if is_failed else None
        progress = _completion(count, total) if is_failed else 100.0
        speed = eta = None
    return {"name": name, "status": status, "progress": progress, "bytes": count,
            "total_bytes": total, "speed": speed, "eta": eta, "error": failure}


def _file_metrics(stats: dict, history: dict) -> list[dict]:
    # A retried file may have an older history entry. Prefer the live attempt.
    files: dict[str, dict] = {}
    for result, key, active in ((history, "transferred", False), (stats, "transferring", True)):
        for entry in _copy_rows(result, key):
            file = _normalized_file(entry, active=active)
            if file is not None:
                files[file["name"]] = file
    return sorted(files.values(), key=lambda file: (file["status"] != "running", file["name"].casefold()))


def _copy_rows(data: dict, key: str, group: str | None = None) -> list[dict]:
    rows = data.get(key)
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, dict) and row.get("checked") is not True
        and row.get("what") in (None, "transferring")
        and (group is None or row.get("group") == group)
    ]


def _local_destination(rows: list[dict]) -> str | None:
    if not rows:
        return None
    targets = []
    for row in rows:
        absolute = row.get("dstFs")
        if not isinstance(absolute, str) or not absolute.startswith("/"):
            return None
        try:
            path = Path(absolute)
            _validate_destination(path)
        except ValueError:
            return None
        if str(path) != absolute:
            return None
        targets.append(absolute)
    return os.path.commonpath(targets)


def _source_path(rows: list[dict]) -> str | None:
    if not rows:
        return None
    fs = rows[0].get("srcFs")
    if not isinstance(fs, str) or any(row.get("srcFs") != fs for row in rows):
        return None
    remote, separator, parent = fs.partition(":")
    if not separator or not _valid_remote(remote):
        return None
    try:
        parent_parts = relative_parts(parent)
        if len(rows) > 1:
            return _literal_fs(remote, parent_parts)
        return _literal_fs(remote, (*parent_parts, *relative_parts(rows[0].get("name"))))
    except ValueError:
        return None


def _job_index(send) -> tuple[str, set[str], set[str]]:
    result = send("job/list", {})
    instance = result.get("executeId")
    if not _valid_execution_id(instance):
        raise RcloneError("rclone 返回的任务实例无效")

    def ids(key: str) -> set[str]:
        raw = result.get(key)
        if raw is None:
            return set()
        if not isinstance(raw, list) or any(not _valid_job_id(job) for job in raw):
            raise RcloneError("rclone 返回的任务清单无效")
        return {str(job) for job in raw}

    return instance, ids("runningIds"), ids("finishedIds")


def _transfer_view(job_id: str, instance: str, result: dict | None, stats: dict, history: dict) -> dict:
    failure = result.get("error") if result else None
    if result is None:
        status, message = "unknown", None
    elif not result["finished"]:
        status, message = "running", None
    elif result["success"]:
        status, message = "completed", None
    elif isinstance(failure, str) and "context canceled" in failure.casefold():
        status, message = "cancelled", None
    else:
        status, message = "failed", _copy_failure(failure)
    count, total = _quantity(stats.get("bytes")), _quantity(stats.get("totalBytes"))
    rows = _copy_rows(stats, "transferring") + _copy_rows(history, "transferred")
    destination = _local_destination(rows)
    files = _file_metrics(stats, history)
    name = files[0]["name"] if len(files) == 1 else (Path(destination).name if destination else "")
    return {
        "id": job_id, "instance": instance, "name": name or "rclone #" + job_id,
        "destination": destination, "source_path": _source_path(rows), "status": status,
        "bytes": count, "total_bytes": total, "history_only": result is None,
        "progress": 100.0 if status == "completed" else _completion(count, total),
        "speed": _speed_or_eta(stats.get("speed"), None) if status == "running" else None,
        "eta": _speed_or_eta(stats.get("eta"), None) if status == "running" else None,
        "error": message, "files": files,
        "started_at": _date(result.get("startTime")) if result else None,
        "ended_at": _date(result.get("endTime")) if result else None,
    }


def _native_status(send, job_id: str, instance: str) -> dict | None:
    try:
        result = send("job/status", {"jobid": job_id})
    except RcloneJobNotFound:
        return None
    if (not _valid_job_id(result.get("id")) or str(result["id"]) != job_id
            or not _valid_execution_id(result.get("executeId"))):
        raise RcloneError("rclone 返回的任务编号无效")
    if result["executeId"] != instance:
        raise _InstanceChanged("rclone 任务实例已变化")
    if result.get("group") != f"job/{job_id}":
        raise RcloneError("rclone 返回的原生任务分组不匹配")
    finished, success = result.get("finished"), result.get("success")
    if type(finished) is not bool or type(success) is not bool or (success and not finished):
        raise RcloneError("rclone 返回的任务状态无效")
    return result


class RcloneProvider(RcloneClient):
    """Operate on named remotes and native rclone jobs visible in rclone Web."""

    def remotes(self) -> list[str]:
        result = self._request("config/listremotes", {})
        names = result.get("remotes")
        if not isinstance(names, list):
            raise RcloneError("rclone 返回的远程存储清单无效")
        return sorted({name for name in names if _valid_remote(name)}, key=str.casefold)

    def entries(self, remote: str, path: tuple[str, ...]) -> list[dict]:
        directory = _literal_path(path)
        result = self._request("operations/list", {
            "fs": _literal_fs(remote), "remote": directory,
            "opt": {"noModTime": True, "noMimeType": True},
        }, response_limit=_LIST_RESPONSE_LIMIT)
        raw = result.get("list")
        if not isinstance(raw, list):
            raise RcloneError("rclone 返回的目录清单无效")
        entries = {}
        for entry in raw:
            if not isinstance(entry, dict) or type(entry.get("IsDir")) is not bool:
                raise RcloneError("rclone 返回的目录条目无效")
            name = entry.get("Name")
            _literal_path((name,))
            if entry.get("Path") not in (name, f"{directory}/{name}") or name in entries:
                raise RcloneError("rclone 返回的目录条目不明确")
            entries[name] = {"name": name, "kind": "directory" if entry["IsDir"] else "file",
                             "size": None if entry["IsDir"] else _quantity(entry.get("Size"))}
        return sorted(entries.values(), key=lambda entry: (entry["kind"] != "directory", entry["name"].casefold()))

    def require_destination(self, path: Path) -> None:
        """Confirm that rclone sees the configured destination as a directory."""
        _validate_destination(path)
        result = self._request("operations/stat", {"fs": str(path.parent), "remote": path.name})
        item = result.get("item")
        if (not isinstance(item, dict) or item.get("IsDir") is not True
                or item.get("Name") != path.name or item.get("Path") != path.name):
            raise RcloneError("rclone 无法看到 NAS 目标目录，请核对挂载映射")

    def start(self, remote: str, path: tuple[str, ...], name: str, is_directory: bool, destination: Path) -> dict:
        _validate_destination(destination)
        name = _literal_path((name,))
        settings = {"Immutable": True, "DryRun": False, "Links": False, "MaxDuration": _COPY_MAX_DURATION}
        if is_directory:
            endpoint = "sync/copy"
            payload = {"srcFs": _literal_fs(remote, (*path, name)), "dstFs": str(destination),
                       "createEmptySrcDirs": True}
        else:
            endpoint = "operations/copyfile"
            payload = {"srcFs": _literal_fs(remote, path), "srcRemote": name,
                       "dstFs": str(destination.parent), "dstRemote": destination.name}
        # Keeping the native default job/<id> group makes transfers visible in rclone Web.
        result = self._request(endpoint, {**payload, "_async": True, "_config": settings})
        job_id, instance = result.get("jobid"), result.get("executeId")
        if not _valid_job_id(job_id) or not _valid_execution_id(instance):
            raise RcloneError("rclone 未返回可确认的复制任务编号")
        return {"id": str(job_id), "instance": instance}

    def get(self, job_id: str, instance: str) -> dict | None:
        _validate_job_reference(job_id, instance)
        with self._pinned_request() as send:
            try:
                result = _native_status(send, job_id, instance)
            except _InstanceChanged:
                return None
            if result is None:
                current, running, _ = _job_index(send)
                if current != instance or job_id in running:
                    return None
                group = "job/" + job_id
                history = send("core/transferred", {"group": group}, response_limit=_LIST_RESPONSE_LIMIT)
                rows = _copy_rows(history, "transferred", group)
                if not rows:
                    return None
                return _transfer_view(job_id, instance, None, {}, {"transferred": rows})
            query = {"group": result["group"]}
            stats = send("core/stats", query, response_limit=_LIST_RESPONSE_LIMIT)
            history = send("core/transferred", query, response_limit=_LIST_RESPONSE_LIMIT)
        return _transfer_view(job_id, instance, result, stats, history)

    def list_transfers(self) -> list[dict]:
        """Discover native transfers without keeping application-owned job records."""
        with self._pinned_request() as send:
            instance, running, finished = _job_index(send)
            active = send("core/stats", {}, response_limit=_LIST_RESPONSE_LIMIT)
            history = send("core/transferred", {}, response_limit=_LIST_RESPONSE_LIMIT)
            groups: dict[str, dict[str, list[dict]]] = {}
            for data, key in ((active, "transferring"), (history, "transferred")):
                for row in _copy_rows(data, key):
                    group = row.get("group")
                    matched = _NATIVE_GROUP.fullmatch(group) if isinstance(group, str) else None
                    if matched:
                        job_id = matched[1]
                        _validate_job_reference(job_id, instance)
                        groups.setdefault(job_id, {"transferring": [], "transferred": []})[key].append(row)
            transfers = []
            for job_id, rows in groups.items():
                status = _native_status(send, job_id, instance) if job_id in finished else None
                if job_id in running or rows["transferring"]:
                    status = {"finished": False, "success": False}
                stats = {"transferring": rows["transferring"]}
                if status is not None and not status["finished"]:
                    per_job = send("core/stats", {"group": "job/" + job_id})
                    stats.update({key: per_job.get(key) for key in ("bytes", "totalBytes", "speed", "eta")})
                transfers.append(_transfer_view(job_id, instance, status, stats, rows))
        return sorted(transfers, key=lambda row: (row["status"] == "running", len(row["id"]), row["id"]),
                      reverse=True)

    def cancel(self, job_id: str, instance: str) -> bool:
        _validate_job_reference(job_id, instance)
        with self._pinned_request() as send:
            try:
                result = _native_status(send, job_id, instance)
            except _InstanceChanged:
                return False
            if result is None or result["finished"]:
                return False
            try:
                send("job/stop", {"jobid": job_id})
            except RcloneJobNotFound:
                return False
            return True

    def delete_history(self, job_id: str, instance: str) -> bool:
        """Forget an observed native job's transfer stats while preserving files."""
        _validate_job_reference(job_id, instance)
        with self._pinned_request() as send:
            current, running, _ = _job_index(send)
            if current != instance or job_id in running:
                return False
            try:
                result = _native_status(send, job_id, instance)
            except _InstanceChanged:
                return False
            if result is not None and not result["finished"]:
                return False
            group = "job/" + job_id
            history = send("core/transferred", {"group": group}, response_limit=_LIST_RESPONSE_LIMIT)
            if not _copy_rows(history, "transferred", group):
                return False
            send("core/stats-delete", {"group": group})
            return True
