"""Execute a scoped rclone copy, then publish its verified directory without replacing files."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from sqlalchemy import text

from app.batch.directory_compare import _open_directory_absolute, _open_directory_relative
from app.config import Settings
from app.download_verification.engine import local_manifest
from app.download_verification.handler import source_client
from app.download_verification.models import DownloadVerificationSource
from app.download_verification.webdav import relative_parts, segment
from app.fs_ops import probe_directory_rename_noreplace_compat_at, rename_noreplace_at
from app.models import WorkJob
from app.tasks.handlers_base import TaskHandler, register_handler
from .rclone import RcloneClient, RcloneError


JOB_KIND = "cloud-copy"
STAGE_PREFIX = ".nfc-cloud-copy-"
_STAGE_NAME = re.compile(r"\.nfc-cloud-copy-[0-9a-f]{32}")
_SOURCE_ID = re.compile(r"[1-9][0-9]{0,18}")
_REMOTE_NAME = re.compile(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,63}")
_POLL_INTERVAL = 1
_MAX_SECONDS = 24 * 60 * 60
_RESERVED_NAMES = frozenset({".recycle", "#recycle", "@recycle", "@eadir", ".nas-file-center-trash"})


class CloudCopyError(ValueError):
    """A user-visible failure with a stable code and no remote response details."""

    def __init__(self, code: str, message: str):
        self.error_code = code
        super().__init__(message)


def valid_source_id(value: str) -> bool:
    return bool(_SOURCE_ID.fullmatch(value)) and (len(value) < 19 or value <= "9223372036854775807")


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if (not path.is_absolute() or path.anchor != "/" or os.path.normpath(value) != value
            or "\\" in value or any(ord(char) < 32 for char in value)):
        raise ValueError("Invalid absolute directory")
    return path


def _reserved_parts(parts) -> bool:
    return any(name.casefold().startswith(".nfc-") or name.casefold() in _RESERVED_NAMES for name in parts)


def remote_directory(value: str) -> tuple[str, ...]:
    parts = relative_parts(value)
    if not parts or _reserved_parts(parts):
        raise ValueError("Select a regular cloud subdirectory")
    return parts


def _protected(path: Path, settings: Settings) -> bool:
    return _reserved_parts(path.parts) or any(
        root is not None and path.is_relative_to(root.resolve())
        for root in (settings.quarantine_root, settings.media_package_root, settings.config_dir)
    )


@dataclass(frozen=True)
class Deployment:
    source_id: str
    local_root: Path
    rclone_local_root: Path
    remote: str
    url: str
    username: str
    password_file: Path

    def fingerprint(self) -> str:
        values = [self.source_id, str(self.local_root), str(self.rclone_local_root),
                  self.remote, self.url, self.username, str(self.password_file)]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def configured_deployment(settings: Settings) -> Deployment | None:
    source_id = settings.cloud_copy_source_id
    if (not valid_source_id(source_id) or not _REMOTE_NAME.fullmatch(settings.cloud_copy_rclone_remote)
            or not settings.cloud_copy_local_root or not settings.cloud_copy_rclone_url
            or not settings.cloud_copy_rclone_username or not settings.cloud_copy_rclone_password_file):
        return None
    try:
        local = _absolute_path(str(settings.cloud_copy_local_root))
        daemon = _absolute_path(settings.cloud_copy_rclone_local_root)
        secret = settings.cloud_copy_rclone_password_file
        if (local == Path("/") or daemon == Path("/") or not secret.is_absolute()
                or not any(local.is_relative_to(root) for root in settings.allowed_roots)
                or _protected(local, settings)):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return Deployment(source_id, local, daemon, settings.cloud_copy_rclone_remote,
                      settings.cloud_copy_rclone_url, settings.cloud_copy_rclone_username, secret)


def active_source(session, source_id: str) -> DownloadVerificationSource | None:
    source = session.get(DownloadVerificationSource, source_id)
    return source if source and source.active and source.provider == "openlist" else None


@contextmanager
def open_destination_parent(deployment: Deployment, settings: Settings, value: str, name: str):
    """Bind a literal NAS parent to the configured import mount, with no symlink traversal."""
    parent = _absolute_path(value)
    target = parent / segment(name)
    if (not parent.is_relative_to(deployment.local_root)
            or not any(parent.is_relative_to(root) for root in settings.allowed_roots)
            or _protected(parent, settings) or _protected(target, settings)
            or name != name.strip() or len(os.fsencode(name)) > 255):
        raise ValueError("Invalid local destination")
    base_fd = _open_directory_absolute(deployment.local_root)
    try:
        fd = _open_directory_relative(base_fd, parent.relative_to(deployment.local_root).parts)
        try:
            if os.fstat(fd).st_dev != os.fstat(base_fd).st_dev:
                raise ValueError("Copy destination crosses a mount boundary")
            yield parent, fd
        finally:
            os.close(fd)
    finally:
        os.close(base_fd)


def directory_identity(info: os.stat_result) -> list[int]:
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Expected ordinary directory")
    return [info.st_dev, info.st_ino]


def _path_identity(fd: int, name: str) -> list[int]:
    return directory_identity(os.stat(name, dir_fd=fd, follow_symlinks=False))


def require_new_folder(fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise CloudCopyError("CLOUD_COPY_DESTINATION_EXISTS", "目标名称已存在，请选择新的文件夹名称。")


def _remote_inventory(source, settings, parts, checkpoint) -> dict[str, dict]:
    try:
        client = source_client(source, settings, mode="metadata")
        return client.manifest(parts, checkpoint)
    except (OSError, ValueError):
        raise CloudCopyError("CLOUD_COPY_SOURCE_UNAVAILABLE", "无法读取 OpenList 目录清单，请检查来源授权。") from None


def _inventory_summary(items: dict[str, dict]) -> dict[str, tuple]:
    summary = {}
    for path, meta in items.items():
        parts = relative_parts(path)
        if not parts or _reserved_parts(parts):
            raise CloudCopyError("CLOUD_COPY_RESERVED_OBJECT", "复制目录包含系统保留的文件名。")
        summary[path] = (meta["kind"], meta["size"])
    return summary


def _publish_directory(fd: int, stage_name: str, name: str, stage_binding: list[int], authorize) -> None:
    try:
        rename_noreplace_at(fd, stage_name, fd, name)
    except FileExistsError:
        raise CloudCopyError("CLOUD_COPY_DESTINATION_EXISTS", "目标名称已被占用，已保留临时目录。") from None
    except OSError as exc:
        if exc.errno != errno.EOPNOTSUPP or probe_directory_rename_noreplace_compat_at(fd, fd) is not True:
            raise CloudCopyError("CLOUD_COPY_PUBLISH_UNAVAILABLE", "NAS 无法安全发布文件夹，已保留临时目录。") from None
        require_new_folder(fd, name)
        if _path_identity(fd, stage_name) != stage_binding:
            raise CloudCopyError("CLOUD_COPY_STAGE_CHANGED", "临时目录已变化，未发布文件夹。") from None
        authorize()
        try:
            os.rename(stage_name, name, src_dir_fd=fd, dst_dir_fd=fd)
        except OSError:
            raise CloudCopyError("CLOUD_COPY_PUBLISH_UNAVAILABLE", "NAS 无法安全发布文件夹，已保留临时目录。") from None


def _read_source(session, state):
    source = active_source(session, state["source_id"])
    if source is None or source.revision != state["source_revision"]:
        raise CloudCopyError("CLOUD_COPY_SOURCE_CHANGED", "OpenList 来源配置已变化，请重新创建复制任务。")
    return source


def _copy_to_stage(client, destination, source, context, expected_files, require_current_source):
    client.require_staging_directory(destination)
    checkpoint = {"schema_version": 1, "phase": "staging"}
    context.checkpoint(progress_total=expected_files, progress_message="正在提交 rclone 复制",
                       checkpoint_data=checkpoint)
    require_current_source()
    remote_job, instance = client.start_copy(source, destination)
    checkpoint.update(phase="copying", rclone_job_id=str(remote_job), rclone_instance=instance)
    current = 0
    finished = False
    expires = time.monotonic() + _MAX_SECONDS
    try:
        while time.monotonic() < expires:
            context.checkpoint(checkpoint_data=checkpoint)
            require_current_source()
            event = client.status(remote_job, instance)
            if event["finished"]:
                finished = True
                if event["success"]:
                    return
                reason = event.get("error") or "rclone 复制失败"
                raise CloudCopyError("CLOUD_COPY_TRANSFER_FAILED", f"{reason}，已保留临时目录。")
            try:
                stats = client.stats(remote_job)
            except RcloneError:
                # Missing metrics do not change the rclone job's outcome.
                time.sleep(_POLL_INTERVAL)
                continue
            current = max(current, min(stats["transfers"], expected_files))
            speed = f'{stats["speed"] / 1048576:.1f} MiB/s'
            context.checkpoint(progress_current=current,
                               progress_message=f"rclone 正在复制，速度 {speed}",
                               checkpoint_data=checkpoint)
            time.sleep(_POLL_INTERVAL)
        raise CloudCopyError("CLOUD_COPY_TIMEOUT", "rclone 复制超时，已保留临时目录。")
    except BaseException:
        # Stop only the known remote job. An unacknowledged submission is never retried.
        if not finished:
            try:
                client.stop(remote_job, instance)
            except RcloneError:
                pass
        raise


@register_handler
class CloudCopyHandler(TaskHandler):
    job_type = JOB_KIND
    supports_cancel = False
    supports_resume = False
    supports_retry = False

    def run(self, job: WorkJob, context, settings: Settings) -> None:
        if not settings.allow_mutation or not context.worker_id:
            raise CloudCopyError("CLOUD_COPY_WRITE_DISABLED", "云端复制需要开启 NAS 写入并由 Worker 执行。")
        deployment = configured_deployment(settings)
        state = json.loads(job.state_json)
        if (deployment is None or state["deployment"] != deployment.fingerprint()
                or state["source_id"] != deployment.source_id):
            raise CloudCopyError("CLOUD_COPY_CONFIG_CHANGED", "云端复制配置已变化，请重新创建任务。")
        parts = remote_directory(state["remote_root"])
        final = _absolute_path(state["local_root"])
        stage = _absolute_path(state["staging_path"])
        if stage.parent != final.parent or not _STAGE_NAME.fullmatch(stage.name):
            raise CloudCopyError("CLOUD_COPY_INVALID_STAGE", "云端复制临时目录记录无效。")
        with context.SessionLocal() as session:
            source = _read_source(session, state)

        def checkpoint():
            context.checkpoint()

        try:
            with open_destination_parent(deployment, settings, str(final.parent), final.name) as (_, fd):
                self._copy_with_parent(fd, final, stage, parts, source, deployment, state, context, settings, checkpoint)
        except RcloneError as exc:
            raise CloudCopyError("CLOUD_COPY_RCLONE_UNAVAILABLE", f"{exc}，请检查临时目录。") from None
        except CloudCopyError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise CloudCopyError("CLOUD_COPY_NAS_UNAVAILABLE", "NAS 目录已变化或无法写入，请检查临时目录。") from None

    def _copy_with_parent(self, fd, final, stage, parts, source, deployment, state, context, settings, checkpoint):
        from app.tasks.recovery import assert_active_worker_lease

        parent_binding = directory_identity(os.fstat(fd))
        if parent_binding != state["parent_identity"]:
            raise CloudCopyError("CLOUD_COPY_PARENT_CHANGED", "目标目录已变化，请重新选择。")
        require_new_folder(fd, final.name)
        context.checkpoint(progress_message="正在读取 OpenList 文件清单")
        remote = _inventory_summary(_remote_inventory(source, settings, parts, checkpoint))
        expected_files = sum(kind == "file" for kind, _ in remote.values())
        client = RcloneClient(base_url=deployment.url, username=deployment.username,
                              password_file=deployment.password_file)
        checkpoint()

        def require_current_source():
            with context.SessionLocal() as session:
                _read_source(session, state)

        require_current_source()
        with open_destination_parent(deployment, settings, str(final.parent), final.name) as (_, live_fd):
            if directory_identity(os.fstat(live_fd)) != parent_binding:
                raise CloudCopyError("CLOUD_COPY_PARENT_CHANGED", "目标目录已变化，请重新选择。")
            require_new_folder(live_fd, final.name)
            os.mkdir(stage.name, mode=0o700, dir_fd=live_fd)
            stage_binding = _path_identity(live_fd, stage.name)
        destination = deployment.rclone_local_root / stage.relative_to(deployment.local_root)
        _copy_to_stage(client, str(destination), deployment.remote + ":" + "/".join(parts),
                       context, expected_files, require_current_source)
        context.checkpoint(progress_message="正在核对到达 NAS 的文件清单")
        if (_inventory_summary(local_manifest(stage, checkpoint)) != remote
                or _inventory_summary(_remote_inventory(source, settings, parts, checkpoint)) != remote):
            raise CloudCopyError("CLOUD_COPY_MANIFEST_MISMATCH",
                                 "云端和 NAS 文件清单不一致或来源已变化，已保留临时目录。")
        with open_destination_parent(deployment, settings, str(final.parent), final.name) as (_, live_fd):
            # Source updates cannot interleave with the publication syscall.
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                assert_active_worker_lease(session, context.worker_id)
                running = session.get(WorkJob, context.job_id)
                if running is None or running.status != "running":
                    raise CloudCopyError("CLOUD_COPY_NOT_RUNNING", "复制任务已失效。")
                _read_source(session, state)
                if (directory_identity(os.fstat(live_fd)) != parent_binding
                        or _path_identity(live_fd, stage.name) != stage_binding):
                    raise CloudCopyError("CLOUD_COPY_STAGE_CHANGED", "目标或临时目录已变化，未发布文件夹。")
                require_new_folder(live_fd, final.name)
                _publish_directory(
                    live_fd, stage.name, final.name, stage_binding,
                    lambda: assert_active_worker_lease(session, context.worker_id),
                )
                session.commit()
        context.checkpoint(progress_current=expected_files, progress_total=expected_files,
                           progress_message="已复制到 NAS，路径及大小清单一致",
                           checkpoint_data={"schema_version": 1, "phase": "published"})
