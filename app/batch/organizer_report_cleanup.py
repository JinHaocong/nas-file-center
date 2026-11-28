"""Recoverable cleanup of the two smart organizer report namespaces."""

from contextlib import contextmanager
from datetime import timedelta
import errno
from itertools import zip_longest
import json
import os
from pathlib import Path
import re
import stat
import time

from sqlalchemy import String, case, cast, func, or_, select, text

from app.batch.file_rename import _open_directory_nofollow
from app.models import BatchPlan, TaskEvent, WorkJob, utcnow
from app.tasks.logging import sanitize_text
from app.tasks.state_machine import TERMINAL_STATES

PREVIEW = "media-organizer-preview"
BATCH = "media-organizer-batch"
KINDS = (PREVIEW, BATCH)
FLOW = "recursive-batch-v1"
RESULT = "media_organizer_unit_result"
KEY = "organizer_report_cleanup"
KEY_BYTES = "reclaimed_bytes"
_RECLAIMED_BYTES = "organizer_report_reclaimed_bytes"
ARCHIVED_SUMMARY = "organizer_archived_result"
_NAMESPACES = {PREVIEW: "organizer-v1-previews", BATCH: "organizer-v1-executions"}
_PREVIEW_FILE = re.compile(r"(?:summary\.json|units\.jsonl|(?:loose-)?[0-9a-f]{64}\.jsonl)")
_EXECUTION_ORDINAL = r"(?:0|[1-9][0-9]*)"
_EXECUTION_FILE = re.compile(rf"{_EXECUTION_ORDINAL}\.(?:link\.)?json")
_EXECUTION_MANIFEST_FILE = re.compile(rf"{_EXECUTION_ORDINAL}\.json")
_ARTIFACT_REJECTION = "报告目录包含未知文件或链接"
_MANIFEST_LINKS_RECHECKED = "manifest_links_rechecked"
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _object(raw):
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def organizer_checkpoint(job):
    return _object(job.checkpoint_json)


def report_state(job):
    """Read the existing checkpoint record without creating one."""
    value = _object(job.checkpoint_json).get(KEY)
    return value if isinstance(value, dict) else {}


def preview_unavailable(job):
    """A reserved preview cannot back a new batch or an assignment."""
    marker = report_state(job)
    return job.kind == PREVIEW and (marker.get("status") in ("pending", "released")
                                   or marker.get("approved") or report_reclaimed(job))


def report_reclaimed(job):
    return (_RECLAIMED_BYTES in _object(job.checkpoint_json)
            or report_state(job).get("status") == "released")


def archived_result(job):
    """Keep summaries from older versions that had already discarded result events."""
    return (_object(job.checkpoint_json).get(ARCHIVED_SUMMARY)
            or report_state(job).get("summary"))


def _forget_marker(job, *, reclaimed=None):
    checkpoint = _object(job.checkpoint_json)
    marker = checkpoint.pop(KEY, {})
    if reclaimed is not None:
        checkpoint[_RECLAIMED_BYTES] = reclaimed
    elif marker.get("status") == "released":
        checkpoint[_RECLAIMED_BYTES] = marker.get(KEY_BYTES, 0)
        if job.kind == BATCH and marker.get("summary"):
            checkpoint[ARCHIVED_SUMMARY] = marker["summary"]
    job.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)


def _mark(job, state, *, hide=False):
    checkpoint = _object(job.checkpoint_json)
    checkpoint[KEY] = state
    if hide:
        checkpoint["_task_queue_dismissed"] = True
    job.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)


def _json_field(column, path):
    return func.json_extract(case((func.json_valid(column), column), else_="{}"), path)


def is_report_task(job):
    """Identify the organizer workflow that owns the two managed report namespaces."""
    return job.kind in KINDS and _object(job.state_json).get("organizer_flow") == FLOW


def report_task_filter():
    flow = func.coalesce(_json_field(WorkJob.state_json, "$.organizer_flow"), "")
    return WorkJob.kind.in_(KINDS) & (flow == FLOW)


def _has_references(session, preview_id, *, except_job=None, active_only=False):
    value = str(preview_id)
    jobs = select(WorkJob.id).where(cast(_json_field(WorkJob.state_json, "$.preview_job_id"), String) == value)
    if except_job is not None:
        jobs = jobs.where(WorkJob.id != except_job)
    if active_only:
        jobs = jobs.where(WorkJob.status.not_in(TERMINAL_STATES))
    plans = select(BatchPlan.id).where(
        cast(_json_field(BatchPlan.metadata_json, "$.luolcy_assignment.preview_job_id"), String) == value,
    )
    return session.scalar(jobs.limit(1)) is not None or session.scalar(plans.limit(1)) is not None


def closed_result_counts(session, job, archived_counts=None):
    """Verify every unit closed successfully, including any previously archived prefix."""
    if (job.progress_total <= 0 or job.progress_current != job.progress_total
            or job.error_text or job.error_code):
        return None
    status = _json_field(TaskEvent.context_json, "$.status")
    counts = dict(session.execute(select(status, func.count()).where(
        TaskEvent.job_id == job.id, TaskEvent.event_type == RESULT,
    ).group_by(status)).all())
    for state, count in (archived_counts or {}).items():
        counts[state] = counts.get(state, 0) + count
    if (set(counts) - {"success", "skipped"} or not counts.get("success")
            or sum(counts.values()) != job.progress_total):
        return None
    return {f"{state}_count": counts.get(state, 0) for state in ("success", "skipped", "failed", "conflict")}


def _eligible(session, job):
    """Return the batch's preview or the standalone preview itself, with a summary."""
    if not is_report_task(job) or job.status != "completed" or job.error_text or job.error_code:
        return None
    if job.kind == PREVIEW:
        return None if _has_references(session, job.id) else (job, {})
    batch = _object(job.state_json)
    preview_id = batch.get("preview_job_id")
    if not isinstance(preview_id, (int, str)) or not re.fullmatch(r"[1-9][0-9]*", str(preview_id)):
        return None
    preview = session.get(WorkJob, preview_id)
    preview_state = _object(preview.state_json) if preview is not None else {}
    if (preview is None or preview.kind != PREVIEW or preview.status != "completed"
            or preview_state.get("organizer_flow") != FLOW
            or not batch.get("selection") or preview_state.get("selection") != batch["selection"]
            or _has_references(session, preview.id, except_job=job.id)):
        return None
    marker = report_state(preview)
    if marker and marker.get("owner") != str(job.id):
        return None
    counts = closed_result_counts(session, job)
    return (preview, counts) if counts is not None else None


def request_report_cleanup(session, job, settings):
    """Reserve report ownership under the caller's BEGIN IMMEDIATE transaction."""
    marker = report_state(job)
    if marker.get("status") == "pending" or report_reclaimed(job):
        return None
    if marker.get("approved"):
        return "retained_count"
    candidate = _eligible(session, job)
    if candidate is None:
        return "retained_count"
    preview, summary = candidate
    reports = [preview] if preview.id == job.id else [preview, job]
    bindings = {}
    try:
        for report in reports:
            path = _report_path(settings, report.kind, str(report.id))
            with _directory(path) as fd:
                bindings[report.kind] = _binding(os.fstat(fd))
    except (OSError, ValueError):
        return "retained_count"
    state = {"status": "pending", "owner": str(job.id), "preview_id": str(preview.id), "bindings": bindings}
    if summary:
        state["summary"] = summary
        _mark(preview, {**state}, hide=True)
    _mark(job, state, hide=True)
    return "queued_count"


@contextmanager
def _directory(path, *, parent_fd=None):
    fd = (_open_directory_nofollow(path) if parent_fd is None
          else os.open(path.name, _FLAGS, dir_fd=parent_fd))
    try:
        yield fd
    finally:
        os.close(fd)


def _identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]


def _binding(info):
    return [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns]


def _report_path(settings, kind, job_id):
    if not re.fullmatch(r"[1-9][0-9]*", job_id):
        raise ValueError("报告任务编号无效")
    return settings.reports_dir / _NAMESPACES[kind] / job_id


def report_missing(settings, kind, job_id):
    """Confirm absence or an empty directory. Unknown and inaccessible paths stay protected."""
    try:
        with _directory(settings.config_dir):
            try:
                with _directory(_report_path(settings, kind, str(job_id))) as fd:
                    with os.scandir(fd) as entries:
                        return next(entries, None) is None
            except FileNotFoundError:
                return True
    except (OSError, ValueError):
        return False


def _snapshot(settings, kind, job_id, *, expected=None):
    """Record only regular, application-owned artifact names and their identities."""
    path = _report_path(settings, kind, job_id)
    pattern = _PREVIEW_FILE if kind == PREVIEW else _EXECUTION_FILE
    with _directory(path.parent) as parent, _directory(path, parent_fd=parent) as fd:
        root = os.fstat(fd)
        if root.st_dev != os.fstat(parent).st_dev:
            raise ValueError("报告目录跨越了挂载边界")
        if expected is not None and _binding(root) != expected:
            raise ValueError("报告目录在删除请求后已变化")
        files = {}
        shared_inodes = set()
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                # Frozen manifests are published with a hardlink. The batch
                # verification checks the exact file and its checksum before unlinking.
                shared_manifest = (kind == BATCH and info.st_nlink == 2
                                   and _EXECUTION_MANIFEST_FILE.fullmatch(entry.name))
                if (not pattern.fullmatch(entry.name) or not stat.S_ISREG(info.st_mode)
                        or info.st_dev != root.st_dev or (info.st_nlink != 1 and not shared_manifest)):
                    raise ValueError(_ARTIFACT_REJECTION)
                if shared_manifest:
                    binding = (info.st_dev, info.st_ino)
                    if binding in shared_inodes:
                        raise ValueError(_ARTIFACT_REJECTION)
                    shared_inodes.add(binding)
                files[entry.name] = _identity(info)
        if _binding(os.fstat(fd)) != _binding(root):
            raise ValueError("报告目录在核对期间已变化")
        return {"kind": kind, "job_id": job_id, "root": [root.st_dev, root.st_ino], "files": files}


@contextmanager
def _bound_report_file(fd, name, binding):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(handle, "r", encoding="utf-8") as stream:
        if _identity(os.fstat(stream.fileno())) != binding:
            raise ValueError("报告文件已变化")
        yield stream


def _read_rows(fd, name, binding):
    with _bound_report_file(fd, name, binding) as stream:
        yield from (json.loads(line) for line in stream)


def _lift_destination(path: Path, ordinal: int, lifts: list[tuple[int, Path, Path]]) -> Path:
    """Resolve a recorded path through the structural operations that followed it."""
    for step, source, target in lifts:
        if step > ordinal and path.is_relative_to(source):
            path = target / path.relative_to(source)
    return path


def _check_closed_batch(settings, job, preview_plan, execution_plan, events, fence):
    """Prove each originally ready unit finished and has no owned staging directory."""
    from app.batch.media_organizer_archive import PROMOTE_ARCHIVE_CHILDREN, _file_binding, _fingerprint, _valid_snapshot
    from app.batch.media_organizer_jobs import _selection
    from app.batch.media_organizer_recycle import RECYCLE_DOWNLOAD_EXTRAS
    from app.batch.media_package_execution import _validate_frozen_manifest_body

    preview = _report_path(settings, PREVIEW, preview_plan["job_id"])
    execution = _report_path(settings, BATCH, execution_plan["job_id"])
    selection = _selection(_object(job.state_json)["selection"], settings)
    manifests = set()
    packages = []
    direct_files = []
    lifts = []
    lift_layouts = []
    next_check = 0.0

    def pulse():
        nonlocal next_check
        if time.monotonic() >= next_check:
            fence()
            next_check = time.monotonic() + 0.8

    with _directory(preview) as fd, _directory(execution) as execution_fd:
        units = _read_rows(fd, "units.jsonl", preview_plan["files"]["units.jsonl"])
        try:
            for ordinal, (unit, event) in enumerate(zip_longest(units, events)):
                pulse()
                if unit is None or event is None or sanitize_text(unit["unit"]) != event.get("unit"):
                    raise ValueError("找不到完整的整理结果")
                if unit["status"] != "ready":
                    if unit["status"] not in ("already_organized", "skipped") or event.get("status") != "skipped":
                        raise ValueError("整理仍有未完成的单元")
                    continue
                if event.get("status") != "success":
                    raise ValueError("整理仍有未完成的单元")
                package = _selection(unit["unit"], settings)
                if unit.get("operation") == RECYCLE_DOWNLOAD_EXTRAS:
                    if event.get("operation") != RECYCLE_DOWNLOAD_EXTRAS or not package.is_relative_to(selection):
                        raise ValueError("极空间回收结果与预览不一致")
                    continue
                name = f"{ordinal}.json"
                if not package.is_relative_to(selection) or name not in execution_plan["files"]:
                    raise ValueError("整理范围或冻结清单不完整")
                manifests.add(name)
                with _bound_report_file(execution_fd, name, execution_plan["files"][name]) as stream:
                    manifest = _validate_frozen_manifest_body(json.load(stream), job_id=job.id, package=package)
                if any(manifest.get(key) != unit.get(key)
                       for key in ("operation", "input_fingerprint", "organizer_mode")):
                    raise ValueError("冻结清单与执行记录不一致")
                if manifest["operation"] == PROMOTE_ARCHIVE_CHILDREN:
                    snapshot = manifest["snapshot"]
                    if (not _valid_snapshot(snapshot, package.name)
                            or _fingerprint(snapshot) != unit["input_fingerprint"]):
                        raise ValueError("归档提层清单无效")
                    layouts = manifest.get("lift_layouts")
                    if layouts is not None and (not isinstance(layouts, dict)
                                                or layouts.keys() != snapshot["children"].keys()):
                        raise ValueError("归档提层目录清单无效")
                    for name, child in snapshot["children"].items():
                        destination = package.parent / name
                        lifts.append((ordinal, package / name, destination))
                        packages.append((ordinal, destination, child["identity"]))
                        if layouts is not None:
                            lift_layouts.append((ordinal, destination, child, layouts[name]))
                    for name, identity in snapshot.get("files", {}).items():
                        direct_files.append((ordinal, package.parent / name, identity))
                else:
                    packages.append((ordinal, package, [manifest["package_dev"], manifest["package_ino"]]))
        finally:
            units.close()
    if {name.replace(".link.json", ".json") for name in execution_plan["files"]} != manifests:
        raise ValueError("无法核对全部执行清单")
    recreated = {}
    if lift_layouts:
        from app.batch.media_organizer_planner import _resolved_protected_roots
        from app.batch.media_organizer_tree_lift import verify_completed_lift

        protected = _resolved_protected_roots(settings.media_package_root, settings.quarantine_root)
        for ordinal, destination, child, layout in lift_layouts:
            pulse()
            final = _lift_destination(destination, ordinal, lifts)
            if (not _selection(str(final), settings).is_relative_to(selection)
                    or any(final.is_relative_to(root) or root.is_relative_to(final) for root in protected)):
                raise ValueError("上提目录超出原确认范围")
            with _directory(final) as fd:
                info = os.fstat(fd)
                if [info.st_dev, info.st_ino] == child["identity"]:
                    continue
            for folder, (original, published) in verify_completed_lift(final, layout, child, checkpoint=pulse).items():
                recreated.setdefault(folder, set()).add((tuple(original), tuple(published)))
    for ordinal, path, identity in direct_files:
        pulse()
        final = _lift_destination(path, ordinal, lifts)
        if not _selection(str(final.parent), settings).is_relative_to(selection):
            raise ValueError("上提文件超出原确认范围")
        with _directory(final.parent) as fd:
            if _file_binding(fd, final.name) != identity:
                raise ValueError("上提文件身份已变化")
    prefix = f".nfc-media_package-stage-{job.id}-"
    for ordinal, package, identity in packages:
        pulse()
        # Later structural units can lift a directory whose media was already organized.
        final = _lift_destination(package, ordinal, lifts)
        if not _selection(str(final), settings).is_relative_to(selection):
            raise ValueError("完成目录超出原确认范围")
        with _directory(final) as fd:
            info = os.fstat(fd)
            actual = (info.st_dev, info.st_ino)
            frozen = tuple(identity)
            if actual != frozen and (frozen, actual) not in recreated.get(final, ()):
                raise ValueError("整理完成的目录身份已变化")
            if any(name.casefold().startswith(prefix) for name in os.listdir(fd)):
                raise ValueError("整理目录仍有暂存文件")
        if final != package:
            try:
                with _directory(package) as fd:
                    if any(name.casefold().startswith(prefix) for name in os.listdir(fd)):
                        raise ValueError("整理原路径仍有暂存文件")
            except FileNotFoundError:
                pass


def _retire(settings, plan, fence):
    """Remove only bindings recorded before the first unlink; safe to repeat after a crash."""
    path = _report_path(settings, plan["kind"], plan["job_id"])
    with _directory(path.parent) as parent:
        try:
            fd = os.open(path.name, _FLAGS, dir_fd=parent)
        except FileNotFoundError:
            os.fsync(parent)
            return
        try:
            info = os.fstat(fd)
            if [info.st_dev, info.st_ino] != plan["root"]:
                raise ValueError("报告目录已变化")
            files = plan["files"]
            names = os.listdir(fd)
            pattern = _PREVIEW_FILE if plan["kind"] == PREVIEW else _EXECUTION_FILE
            if not set(names) <= files.keys() or any(not pattern.fullmatch(name) for name in names):
                raise ValueError("报告目录出现未核对的文件")
            for name in names:
                if _identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != files[name]:
                    raise ValueError("报告文件已变化")
            for name in names:
                fence()
                if _identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != files[name]:
                    raise ValueError("报告文件已变化")
                os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)
        fence()
        live = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if [live.st_dev, live.st_ino] != plan["root"] or not stat.S_ISDIR(live.st_mode):
            raise ValueError("报告目录已变化")
        os.rmdir(path.name, dir_fd=parent)
        os.fsync(parent)


def _update_request(session_factory, job_id, old, new, *, per_report_bytes=None):
    with session_factory.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        job = session.get(WorkJob, job_id)
        if job is None or report_state(job) != old:
            return False
        preview = session.get(WorkJob, old["preview_id"])
        if preview is None or report_state(preview).get("owner") != str(job.id):
            return False
        # Refuse further deletion if a dependency appeared before approval.
        if new.get("plan") and not old.get("plan") and _eligible(session, job) is None:
            return False
        if new["status"] == "released":
            _forget_marker(job, reclaimed=per_report_bytes.get(job.kind, 0))
            if preview.id != job.id:
                _forget_marker(preview, reclaimed=per_report_bytes.get(PREVIEW, 0))
            return True
        _mark(job, new)
        if preview.id != job.id:
            related = {key: val for key, val in new.items() if key not in ("plan", "summary")}
            _mark(preview, related)
        return True


def process_pending_reports(session_factory, settings, fence, *, now=None):
    """Process at most one owner request. Leave durable intent on transient I/O failures."""
    now = now or utcnow()
    with session_factory() as session:
        status = _json_field(WorkJob.checkpoint_json, f"$.{KEY}.status")
        owner = _json_field(WorkJob.checkpoint_json, f"$.{KEY}.owner")
        retry = _json_field(WorkJob.checkpoint_json, f"$.{KEY}.retry_at")
        reason = _json_field(WorkJob.checkpoint_json, f"$.{KEY}.reason")
        approved = _json_field(WorkJob.checkpoint_json, f"$.{KEY}.approved")
        rechecked = _json_field(WorkJob.checkpoint_json, f"$.{KEY}.{_MANIFEST_LINKS_RECHECKED}")
        pending = status == "pending"
        legacy_rejection = ((WorkJob.kind == BATCH) & (status == "retained") & (reason == _ARTIFACT_REJECTION)
                            & (func.coalesce(approved, 0) == 0) & (func.coalesce(rechecked, 0) == 0))
        job = session.scalar(select(WorkJob).where(
            WorkJob.kind.in_(KINDS), or_(pending, legacy_rejection), owner == cast(WorkJob.id, String),
            func.coalesce(retry, "") <= now.isoformat(),
        ).order_by(pending.desc(), WorkJob.id).limit(1))
        if job is None:
            return
        marker = report_state(job)
        eligible = _eligible(session, job)
        events = [_object(raw) for raw in session.scalars(select(TaskEvent.context_json).where(
            TaskEvent.job_id == job.id, TaskEvent.event_type == RESULT,
        ).order_by(TaskEvent.id))] if job.kind == BATCH and not marker.get("plan") else []
    fence()
    try:
        if marker["status"] == "retained":
            # Recheck pre-upgrade requests once using their original directory bindings.
            pending_marker = {**marker, "status": "pending", _MANIFEST_LINKS_RECHECKED: True}
            if not _update_request(session_factory, job.id, marker, pending_marker):
                return
            marker = pending_marker
        if eligible is None:
            raise ValueError("仍有任务引用或恢复证据不足")
        plan = marker.get("plan")
        if plan is None:
            preview = _snapshot(settings, PREVIEW, marker["preview_id"], expected=marker["bindings"][PREVIEW])
            plan = [preview]
            if job.kind == BATCH:
                execution = _snapshot(settings, BATCH, str(job.id), expected=marker["bindings"][BATCH])
                _check_closed_batch(settings, job, preview, execution, events, fence)
                plan.insert(0, execution)
            approved = {**marker, "plan": plan, "approved": True}
            fence()
            if not _update_request(session_factory, job.id, marker, approved):
                return
            marker = approved
        owned = {PREVIEW: marker["preview_id"]}
        if job.kind == BATCH:
            owned[BATCH] = str(job.id)
        if len(plan) != len(owned) or {item["kind"]: item["job_id"] for item in plan} != owned:
            raise ValueError("回收清单与任务不一致")
        for report in plan:
            _retire(settings, report, fence)
        released = {k: v for k, v in marker.items() if k not in ("plan", "bindings", "retry_at", "reason")}
        released["status"] = "released"
        # A removed report name may still have a surviving link outside the report directory.
        sizes = {report["kind"]: sum(item[2] for item in report["files"].values() if item[-1] == 1)
                 for report in plan}
        fence()
        _update_request(session_factory, job.id, marker, released, per_report_bytes=sizes)
    except OSError as error:
        fence()
        if error.errno in (errno.ENOTDIR, errno.ELOOP):
            _hold_request(session_factory, job.id, marker, "报告路径包含未知目录或链接")
        elif isinstance(error, FileNotFoundError) and not marker.get("plan"):
            _hold_request(session_factory, job.id, marker, "报告或恢复证据缺失，保留现有文件")
        else:
            reason = ("暂时无法写入报告目录，等待 Worker 重试" if isinstance(error, PermissionError)
                      else "磁盘操作失败，等待 Worker 重试")
            _update_request(session_factory, job.id, marker, {
                **marker, "reason": reason, "retry_at": (now + timedelta(minutes=1)).isoformat(),
            })
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        fence()
        _hold_request(session_factory, job.id, marker, str(exc))


def _hold_request(session_factory, job_id, marker, reason):
    held = {key: val for key, val in marker.items() if key not in ("plan", "retry_at")}
    if reason == _ARTIFACT_REJECTION:
        held[_MANIFEST_LINKS_RECHECKED] = True
    _update_request(session_factory, job_id, marker, {**held, "status": "retained", "reason": reason})


def prune_missing_report_markers(session_factory, settings, fence):
    """Discard stale DB cleanup state only after all reports in a terminal group are gone."""
    owner_field = _json_field(WorkJob.checkpoint_json, f"$.{KEY}.owner")
    with session_factory() as session:
        owners = list(session.scalars(select(owner_field).where(
            report_task_filter(), owner_field.is_not(None),
        ).distinct()))
    for owner in owners:
        fence()
        with session_factory.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            related = list(session.scalars(select(WorkJob).where(report_task_filter(), owner_field == owner)))
            if not related or any(job.status not in TERMINAL_STATES for job in related):
                continue
            if any(not report_missing(settings, job.kind, job.id) for job in related):
                continue
            if any(job.kind == PREVIEW and _has_references(session, job.id, active_only=True)
                   for job in related):
                continue
            for job in related:
                _forget_marker(job)


def inventory(session_factory, settings, *, page, page_size):
    """List only smart organizer report sizes and eligibility without modifying state."""
    items = []
    with session_factory() as session:
        reclaimed = session.scalar(select(func.sum(func.coalesce(
            _json_field(WorkJob.checkpoint_json, f"$.{_RECLAIMED_BYTES}"),
            _json_field(WorkJob.checkpoint_json, f"$.{KEY}.{KEY_BYTES}"), 0,
        ))).where(WorkJob.kind.in_(KINDS))) or 0
        for kind, namespace in _NAMESPACES.items():
            try:
                with _directory(settings.reports_dir / namespace) as parent:
                    names = sorted(os.listdir(parent))
            except FileNotFoundError:
                names = []
            for job_id in names:
                if not re.fullmatch(r"[1-9][0-9]*", job_id):
                    continue
                job = session.get(WorkJob, job_id)
                if job is not None and job.kind != kind:
                    job = None
                marker = report_state(job) if job is not None else {}
                status = marker.get("status")
                if status is None:
                    if job is not None:
                        status = "reclaimable" if _eligible(session, job) else "retained"
                    else:
                        referenced = kind == PREVIEW and _has_references(session, job_id)
                        status = "orphan" if kind == PREVIEW and not referenced else "retained"
                row = {"job_id": job_id, "kind": "preview" if kind == PREVIEW else "execution",
                       "status": status, "reason": marker.get("reason", _REASONS[status]), "bytes": 0, "files": 0}
                try:
                    files = _snapshot(settings, kind, job_id)["files"]
                except FileNotFoundError:
                    continue
                except (OSError, ValueError):
                    if status != "pending":
                        row.update(status="unknown", reason=_REASONS["unknown"])
                else:
                    if not files:
                        continue
                    row.update(files=len(files), bytes=sum(file[2] for file in files.values()))
                items.append(row)
    items.sort(key=lambda row: (len(row["job_id"]), row["job_id"]), reverse=True)
    start = (page - 1) * page_size
    return {"read_only": True, "items": items[start:start + page_size], "total": len(items),
            "page": page, "page_size": page_size, "pending_count": sum(r["status"] == "pending" for r in items),
            "total_bytes": sum(r["bytes"] for r in items),
            "reclaimed_bytes": reclaimed}


_REASONS = {
    "pending": "等待 Worker 回收",
    "released": "报告已回收",
    "retained": "报告仍有引用或需保留恢复证据",
    "reclaimable": "可随任务申请回收，Worker 将核对报告",
    "orphan": "无任务记录或已知引用，供人工核对",
    "unknown": "报告内容或路径无法验证",
}
