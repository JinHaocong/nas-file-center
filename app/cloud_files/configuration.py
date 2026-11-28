from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.cloud_copy.handler import _absolute_path, _protected, _reserved_parts, active_source, valid_source_id
from app.config import Settings
from app.download_verification.models import DownloadVerificationSource
from app.download_verification.sources import validate_source_url


def _root(value: str) -> Path | None:
    try:
        path = _absolute_path(value)
        return path if path != Path("/") and not _reserved_parts(path.parts) else None
    except ValueError:
        return None


def _web_link(value: str) -> str | None:
    try:
        url = urlsplit(value)
        if (url.scheme in ("http", "https") and url.hostname and url.username is None
                and url.password is None and not url.query and not url.fragment):
            return url.geturl().rstrip("/")
    except ValueError:
        pass
    return None


@dataclass(frozen=True)
class CloudConfiguration:
    local_root: Path | None
    rclone_root: Path | None
    openlist_root: Path | None
    openlist_source: DownloadVerificationSource | None
    rclone_enabled: bool
    rclone_origin: str


def read_configuration(session, settings: Settings) -> CloudConfiguration:
    local = _root(str(settings.cloud_copy_local_root or ""))
    if local and (_protected(local, settings) or not any(local.is_relative_to(root) for root in settings.allowed_roots)):
        local = None
    openlist_root = _root(settings.cloud_files_openlist_nas_path)
    source_id = settings.cloud_files_openlist_source_id or settings.cloud_copy_source_id
    source = active_source(session, source_id) if openlist_root and valid_source_id(source_id) else None
    rclone_root = _root(settings.cloud_copy_rclone_local_root)
    try:
        origin = validate_source_url(settings.cloud_copy_rclone_url)
    except ValueError:
        origin = ""
    secret = settings.cloud_copy_rclone_password_file
    rclone = bool(rclone_root and origin and settings.cloud_copy_rclone_username and secret and secret.is_absolute())
    return CloudConfiguration(local, rclone_root, openlist_root, source, rclone, origin)


def public_configuration(config: CloudConfiguration, settings: Settings) -> dict:
    source = config.openlist_source
    return {
        "enabled": bool(config.local_root and (source or config.rclone_enabled)),
        "writable": bool(settings.allow_mutation and config.local_root),
        "local_root": str(config.local_root) if config.local_root else None,
        "openlist": {"enabled": bool(source), "name": source.name if source else None,
                     "web_url": _web_link(settings.cloud_files_openlist_web_url)},
        "rclone": {"enabled": config.rclone_enabled, "web_url": _web_link(settings.cloud_files_rclone_web_url)},
    }
