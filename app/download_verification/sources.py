"""Read-only AList/OpenList file-list API; origins configured by administrators only."""
from __future__ import annotations

import ipaddress
import hashlib
import time
from uuid import uuid4
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPHandler, HTTPSHandler
from urllib.error import HTTPError, URLError

from .webdav import WebDAVError, _NoRedirect, MAX_ENTRIES, relative_parts, segment

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
PAGE_SIZE = 200


def validate_source_url(value: str) -> str:
    """Require a single HTTP(S) origin, never URL-supplied credentials or paths."""
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("INVALID_SOURCE_URL")
    parsed = urlsplit(value.strip())
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment or
            parsed.port == 0):
        raise ValueError("INVALID_SOURCE_URL")
    host = parsed.hostname.lower().rstrip(".")
    if host in ("localhost", "localhost.localdomain", "metadata.google.internal"):
        raise ValueError("FORBIDDEN_SOURCE_HOST")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", host):
            raise ValueError("INVALID_SOURCE_HOST")
        if parsed.scheme == "http" and "." in host:
            # Insecure HTTP is permitted only for an internal Docker service DNS name.
            raise ValueError("HTTP_REQUIRES_DOCKER_SERVICE_NAME")
    else:
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError("FORBIDDEN_SOURCE_HOST")
        if parsed.scheme == "http" and not ip.is_private:
            raise ValueError("HTTP_REQUIRES_PRIVATE_NETWORK")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), "", "", ""))


def source_secret_path(config_dir: Path, filename: str) -> Path:
    if not re.fullmatch(r"source-[0-9a-f]{32}\.secret", filename):
        raise ValueError("INVALID_SOURCE_SECRET")
    return Path(config_dir) / "download-verification-secrets" / filename


def write_secret(config_dir: Path, filename: str, password: str) -> None:
    """Create an exclusive 0600 credential, never in logs, env, SQLite or API output."""
    if not password or len(password.encode("utf-8")) > 4096:
        raise ValueError("INVALID_SOURCE_PASSWORD")
    path = source_secret_path(config_dir, filename)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(password.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _session_path(config_dir: Path, secret_filename: str) -> Path:
    return source_secret_path(config_dir, secret_filename).with_suffix(".session")


def _session_binding(base_url: str, username: str, secret_filename: str) -> str:
    return hashlib.sha256(json.dumps([base_url, username, secret_filename]).encode()).hexdigest()


def read_source_session(config_dir: Path, secret_filename: str, base_url: str, username: str) -> str:
    """Tokens are scoped to the exact origin/account/secret, shared by API and Worker."""
    path = _session_path(config_dir, secret_filename)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
            return ""
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("binding") != _session_binding(base_url, username, secret_filename)
                or type(data.get("expires_at")) not in (int, float)
                or data["expires_at"] <= time.time()):
            return ""
        token = data.get("token")
        return token if isinstance(token, str) and 0 < len(token) <= 4096 else ""
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def save_source_session(config_dir: Path, secret_filename: str, base_url: str,
                        username: str, token: str) -> None:
    """Atomic, mode-0600 cache. Never put tokens/OTP in SQLite, job state or API output."""
    if not token or len(token) > 4096:
        raise ValueError("INVALID_SOURCE_TOKEN")
    path = _session_path(config_dir, secret_filename)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"binding": _session_binding(base_url, username, secret_filename),
                       "token": token, "expires_at": time.time() + 24 * 3600}, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def clear_source_session(config_dir: Path, secret_filename: str | None) -> None:
    if secret_filename:
        _session_path(config_dir, secret_filename).unlink(missing_ok=True)


class AListAPIClient:
    """AList/OpenList compatible API: login (optional) and paginated /api/fs/list."""

    def __init__(self, *, base_url: str, username: str = "", password_file: str | None = None,
                 opener=None, session_config_dir: Path | None = None,
                 session_secret_name: str | None = None, otp_code: str | None = None):
        self.base = validate_source_url(base_url)
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirect(), HTTPHandler(), HTTPSHandler())
        self._token = ""
        self._session_config_dir = session_config_dir
        self._session_secret_name = session_secret_name
        if (session_config_dir is not None and session_secret_name and username
                and otp_code is None):
            self._token = read_source_session(session_config_dir, session_secret_name, self.base, username)
        if username and not self._token:
            if not password_file:
                raise WebDAVError("SOURCE_AUTH_REQUIRED")
            file = Path(password_file)
            if not file.is_file() or file.stat().st_size > 4096:
                raise WebDAVError("SOURCE_SECRET_MISSING")
            password = file.read_text(encoding="utf-8").rstrip("\r\n")
            # Password is never serialized into a queued job or a result record.
            payload = {"username": username, "password": password}
            if otp_code is not None:
                if not re.fullmatch(r"[0-9]{6,8}", otp_code):
                    raise WebDAVError("SOURCE_OTP_INVALID")
                payload["otp_code"] = otp_code
            result = self._json("/api/auth/login", payload)
            token = result.get("data", {}).get("token") if isinstance(result.get("data"), dict) else None
            if not isinstance(token, str) or not token:
                raise WebDAVError("SOURCE_AUTH_FAILED")
            self._token = token
            if session_config_dir is not None and session_secret_name:
                save_source_session(session_config_dir, session_secret_name, self.base, username, token)

    def _json(self, path: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "Accept-Encoding": "identity"}
        if self._token:
            headers["Authorization"] = self._token
        req = Request(self.base + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      method="POST", headers=headers)
        try:
            with self._opener.open(req, timeout=30) as response:
                if response.status != 200 or response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise WebDAVError("SOURCE_API_UNAVAILABLE")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, OSError, TimeoutError):
            raise WebDAVError("SOURCE_API_UNAVAILABLE") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WebDAVError("SOURCE_RESPONSE_LIMIT")
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise WebDAVError("SOURCE_INVALID_RESPONSE") from None
        if not isinstance(parsed, dict) or parsed.get("code") != 200:
            if self._token and path == "/api/fs/list":
                if self._session_config_dir is not None:
                    clear_source_session(self._session_config_dir, self._session_secret_name)
                raise WebDAVError("SOURCE_SESSION_EXPIRED")
            if path == "/api/auth/login":
                raise WebDAVError("SOURCE_AUTH_FAILED_OR_OTP_REQUIRED")
            raise WebDAVError("SOURCE_API_DENIED")
        return parsed

    def list_directory(self, parts: tuple[str, ...]) -> dict[tuple[str, ...], dict]:
        parts = tuple(segment(x) for x in parts)
        path = "/" + "/".join(parts)
        items: dict[tuple[str, ...], dict] = {}
        page = 1
        total = None
        while True:
            response = self._json("/api/fs/list", {
                "path": path, "password": "", "page": page, "per_page": PAGE_SIZE,
                "refresh": False
            })
            data = response.get("data")
            if not isinstance(data, dict):
                raise WebDAVError("SOURCE_INVALID_LIST")
            entries = data.get("content") or []
            count = data.get("total")
            if not isinstance(entries, list) or not isinstance(count, int) or count < 0 or count > MAX_ENTRIES:
                raise WebDAVError("SOURCE_INVALID_LIST")
            if total is None:
                total = count
            elif total != count:
                raise WebDAVError("SOURCE_LIST_CHANGED")
            if len(entries) > PAGE_SIZE or (not entries and len(items) < total):
                raise WebDAVError("SOURCE_PAGINATION_INCOMPLETE")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise WebDAVError("SOURCE_INVALID_ENTRY")
                name = segment(entry.get("name"))
                key = parts + (name,)
                size = entry.get("size")
                is_dir = entry.get("is_dir")
                if key in items or not isinstance(is_dir, bool):
                    raise WebDAVError("SOURCE_DUPLICATE_OR_INVALID")
                if not is_dir and (type(size) is not int or size < 0):
                    raise WebDAVError("SOURCE_FILE_SIZE_UNKNOWN")
                items[key] = {"kind": "directory" if is_dir else "file",
                              "size": None if is_dir else size, "etag": None, "mtime": None}
            if len(items) >= total:
                if len(items) != total:
                    raise WebDAVError("SOURCE_PAGINATION_INCONSISTENT")
                return items
            page += 1
            if page > (MAX_ENTRIES // PAGE_SIZE) + 2:
                raise WebDAVError("SOURCE_LIST_LIMIT")

    def manifest(self, root: tuple[str, ...], checkpoint=lambda: None) -> dict[str, dict]:
        root = tuple(segment(x) for x in root)
        result: dict[str, dict] = {}
        pending = [root]
        while pending:
            parent = pending.pop()
            for path, meta in self.list_directory(parent).items():
                relative = "/".join(path[len(root):])
                if not relative or relative in result or len(result) >= MAX_ENTRIES:
                    raise WebDAVError("SOURCE_DUPLICATE_OR_LIMIT")
                result[relative] = meta
                if meta["kind"] == "directory":
                    pending.append(path)
                if len(result) % 100 == 0:
                    checkpoint()
        return result
