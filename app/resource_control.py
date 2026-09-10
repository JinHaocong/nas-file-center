from dataclasses import dataclass
from datetime import datetime, time
from functools import lru_cache
import re
from typing import Any, Literal
import zoneinfo

class ResourcePolicyValidationError(ValueError):
    pass

class ResourcePolicyConfigError(RuntimeError):
    pass

ProfileType = Literal["full", "limited", "pause"]
IOLimitType = Literal["low", "normal", "unlimited"]
JobPriorityType = Literal["normal", "background"]
OutsideWindowModeType = Literal["limited", "pause"]

@dataclass(frozen=True)
class ResourcePolicySnapshot:
    scan_threads: int
    hash_threads: int
    io_limit: str
    job_priority: str
    active_window_enabled: bool
    active_window_start: str | None
    active_window_end: str | None
    active_window_timezone: str | None
    outside_window_mode: str
    revision: int = 1

@dataclass(frozen=True)
class EffectiveResourcePolicy:
    profile: ProfileType
    inside_active_window: bool | None
    resource_jobs_admitted: bool
    effective_thread_cap: int
    revision: int

def resource_policy_row_fingerprint(row: Any) -> tuple | None:
    if row is None:
        return None
    return (
        row.revision,
        row.scan_threads,
        row.hash_threads,
        row.io_limit,
        row.job_priority,
        row.active_window_enabled,
        row.active_window_start,
        row.active_window_end,
        row.active_window_timezone,
        row.outside_window_mode,
    )

@lru_cache(maxsize=32)
def resolve_timezone(name: str) -> zoneinfo.ZoneInfo:
    if not isinstance(name, str) or not name.strip():
        raise ResourcePolicyValidationError("Timezone name must be a non-empty string")
    try:
        return zoneinfo.ZoneInfo(name)
    except Exception as exc:
        raise ResourcePolicyValidationError(f"Invalid timezone: {name}") from exc

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

def _parse_time(t_str: str) -> time:
    m = _TIME_RE.match(t_str)
    if not m:
        raise ResourcePolicyValidationError(f"Invalid time format: {t_str}, expected HH:MM")
    return time(int(m.group(1)), int(m.group(2)))

def validate_resource_policy_snapshot(snapshot: ResourcePolicySnapshot) -> None:
    if isinstance(snapshot.scan_threads, bool) or not isinstance(snapshot.scan_threads, int):
        raise ResourcePolicyValidationError("scan_threads must be an integer")
    if isinstance(snapshot.hash_threads, bool) or not isinstance(snapshot.hash_threads, int):
        raise ResourcePolicyValidationError("hash_threads must be an integer")
    if not isinstance(snapshot.active_window_enabled, bool):
        raise ResourcePolicyValidationError("active_window_enabled must be a boolean")

    if not (1 <= snapshot.scan_threads <= 32):
        raise ResourcePolicyValidationError(f"scan_threads must be between 1 and 32, got {snapshot.scan_threads}")
    if not (1 <= snapshot.hash_threads <= 32):
        raise ResourcePolicyValidationError(f"hash_threads must be between 1 and 32, got {snapshot.hash_threads}")

    if snapshot.io_limit not in ("low", "normal", "unlimited"):
        raise ResourcePolicyValidationError(f"Invalid io_limit: {snapshot.io_limit}")
    if snapshot.job_priority not in ("normal", "background"):
        raise ResourcePolicyValidationError(f"Invalid job_priority: {snapshot.job_priority}")
    if snapshot.outside_window_mode not in ("limited", "pause"):
        raise ResourcePolicyValidationError(f"Invalid outside_window_mode: {snapshot.outside_window_mode}")

    if snapshot.active_window_enabled:
        if not snapshot.active_window_start or not snapshot.active_window_end or not snapshot.active_window_timezone:
            raise ResourcePolicyValidationError("active_window_start, active_window_end, and active_window_timezone are required when active window is enabled")
        t_start = _parse_time(snapshot.active_window_start)
        t_end = _parse_time(snapshot.active_window_end)
        if t_start == t_end:
            raise ResourcePolicyValidationError("active_window_start and active_window_end cannot be equal")
        resolve_timezone(snapshot.active_window_timezone)
    else:
        if snapshot.active_window_start is not None:
            _parse_time(snapshot.active_window_start)
        if snapshot.active_window_end is not None:
            _parse_time(snapshot.active_window_end)
        if snapshot.active_window_start is not None and snapshot.active_window_end is not None:
            if _parse_time(snapshot.active_window_start) == _parse_time(snapshot.active_window_end):
                raise ResourcePolicyValidationError("active_window_start and active_window_end cannot be equal")
        if snapshot.active_window_timezone is not None:
            resolve_timezone(snapshot.active_window_timezone)

def evaluate_resource_policy(
    snapshot: ResourcePolicySnapshot,
    *,
    now_utc: datetime,
    resolved_timezone: zoneinfo.ZoneInfo | None = None,
) -> EffectiveResourcePolicy:
    if snapshot.io_limit == "low":
        io_cap = 1
    elif snapshot.io_limit == "normal":
        io_cap = 2
    elif snapshot.io_limit == "unlimited":
        io_cap = 32
    else:
        io_cap = 2

    normal_cap = min(snapshot.scan_threads, snapshot.hash_threads, io_cap)

    if not snapshot.active_window_enabled:
        return EffectiveResourcePolicy(
            profile="full",
            inside_active_window=None,
            resource_jobs_admitted=True,
            effective_thread_cap=normal_cap,
            revision=snapshot.revision,
        )

    tz = resolved_timezone or resolve_timezone(snapshot.active_window_timezone or "UTC")
    local_dt = now_utc.astimezone(tz)
    cur_time = local_dt.time()
    t_start = _parse_time(snapshot.active_window_start or "00:00")
    t_end = _parse_time(snapshot.active_window_end or "00:00")

    if t_start < t_end:
        inside = (t_start <= cur_time < t_end)
    else:
        inside = (cur_time >= t_start or cur_time < t_end)

    if inside:
        return EffectiveResourcePolicy(
            profile="full",
            inside_active_window=True,
            resource_jobs_admitted=True,
            effective_thread_cap=normal_cap,
            revision=snapshot.revision,
        )

    if snapshot.outside_window_mode == "limited":
        return EffectiveResourcePolicy(
            profile="limited",
            inside_active_window=False,
            resource_jobs_admitted=True,
            effective_thread_cap=min(normal_cap, 1),
            revision=snapshot.revision,
        )
    else:
        return EffectiveResourcePolicy(
            profile="pause",
            inside_active_window=False,
            resource_jobs_admitted=False,
            effective_thread_cap=min(normal_cap, 1),
            revision=snapshot.revision,
        )

def parse_positive_thread_ceiling(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, bool):
        raise ResourcePolicyConfigError("Thread ceiling cannot be boolean")
    if isinstance(val, int):
        if val <= 0:
            raise ResourcePolicyConfigError("Thread ceiling must be positive")
        return val
    if isinstance(val, str):
        try:
            n = int(val)
            if n <= 0:
                raise ResourcePolicyConfigError("Thread ceiling must be positive")
            return n
        except ValueError as exc:
            raise ResourcePolicyConfigError(f"Invalid thread ceiling: {val}") from exc
    raise ResourcePolicyConfigError(f"Unsupported thread ceiling type: {type(val)}")

def compose_fclones_thread_cap(
    policy_effective_cap: int,
    legacy_fclones_threads: Any = None,
    requested_task_threads: Any = None,
) -> int:
    candidates = [policy_effective_cap]
    legacy = parse_positive_thread_ceiling(legacy_fclones_threads)
    if legacy is not None:
        candidates.append(legacy)
    task = parse_positive_thread_ceiling(requested_task_threads)
    if task is not None:
        candidates.append(task)
    return min(candidates)

def is_resource_controlled_job(kind: str) -> bool:
    return kind in ("index-root", "fclones-scan")
