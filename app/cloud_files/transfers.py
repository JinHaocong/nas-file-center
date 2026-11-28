"""Present native transfer receipts without a local ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
import re


TERMINAL = frozenset({"completed", "cancelled", "failed"})
_OL_ID = re.compile(r"[A-Za-z0-9_.~-]{1,128}")
_RC_ID = re.compile(r"[1-9][0-9]{0,18}")
_INSTANCE = re.compile(r"[A-Za-z0-9_-]{1,128}")


def parse_task_id(task_id: str) -> tuple[str, str, str | None]:
    provider, _, tail = task_id.partition(".")
    if provider == "openlist" and _OL_ID.fullmatch(tail):
        return provider, tail, None
    if provider == "rclone":
        instance, _, native_id = tail.partition(".")
        if _INSTANCE.fullmatch(instance) and _RC_ID.fullmatch(native_id):
            return provider, native_id, instance
    raise ValueError("Invalid native transfer identity")


def _time(raw: str | None) -> str:
    try:
        parsed = datetime.fromisoformat(raw) if raw else None
        return parsed.astimezone(timezone.utc).isoformat() if parsed and parsed.tzinfo else ""
    except ValueError:
        return ""


def _openlist_files(record: dict) -> list[dict]:
    if record.get("is_directory") is not False:
        return []
    total, progress = record.get("total_bytes"), record.get("progress")
    count = int(total * progress / 100) if total is not None and progress is not None else None
    return [{"name": record["name"], "status": record["status"], "progress": progress,
             "bytes": count, "total_bytes": total, "speed": None}]


def local_destination(provider, record, config) -> str | None:
    """Translate only destinations below the operation's configured NAS mount."""
    root = config.openlist_root if provider == "openlist" else config.rclone_root
    reported = record.get("destination_path" if provider == "openlist" else "destination")
    if not (reported and root and config.local_root):
        return None
    path = PurePosixPath(reported)
    if not path.is_absolute() or any(part in (".", "..") for part in path.parts) or not path.is_relative_to(root):
        return None
    # OpenList describes the resulting object while rclone reports its local transfer root.
    if provider == "openlist":
        if path == root:
            return None
        path = path.parent
    return str(config.local_root / path.relative_to(root))


def transfer_view(provider, record, config, *, instance=None, destination=None) -> dict | None:
    if provider == "rclone":
        instance = instance or record.get("instance")
        if not instance:
            return None
        task_id = "rclone." + instance + "." + record["id"]
    else:
        task_id = "openlist." + record["id"]
    mapped = local_destination(provider, record, config)
    if not mapped and destination is None:
        return None
    status = record["status"]
    name = record.get("name") or "复制任务"
    source = record.get("source_path") or record.get("source") or ""
    remote = record.get("remote")
    if provider == "openlist" and source:
        source = str(PurePosixPath(source).parent).lstrip("/")
    elif provider == "rclone" and not remote and ":" in source:
        remote, source = source.split(":", 1)
    files = _openlist_files(record) if provider == "openlist" else record.get("files", [])
    result = {
        "id": task_id, "provider": provider, "remote": remote, "path": source,
        "destination": mapped or destination, "names": [name], "status": status,
        "progress": record.get("progress"), "speed": record.get("speed"), "error": record.get("error"),
        "created_at": _time(record.get("started_at") or record.get("ended_at")),
        "native_ids": [record["id"]], "files": files,
        "can_cancel": bool(mapped) and status in {"running", "queued"},
        "can_delete": bool(mapped) and (status in TERMINAL or (
            provider == "rclone" and record.get("history_only") is True
        )),
    }
    if (provider == "openlist" and status == "completed" and record.get("is_directory") is True
            and mapped and record.get("source_path")):
        result["verification"] = {
            "source_id": str(config.openlist_source.id), "remote_root": record["source_path"].lstrip("/"),
            "local_root": str(PurePosixPath(mapped) / name),
        }
    return result
