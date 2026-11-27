"""Short-lived browser handoffs to the existing official ZSpace Worker profile."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
import re
import secrets
from selectors import DefaultSelector, EVENT_READ
import stat
import subprocess
from threading import Lock, Timer
import time
from urllib.parse import parse_qs, urlsplit

from app.batch.media_organizer_recycle import zspace_client
from app.batch.zspace_recycle import ZSpaceRecycleClient, ZSpaceRecycleError
from app.config import Settings


_START_TIMEOUT = 8
_COMPLETE_TIMEOUT = 25
_MAX_AUTH_LIFETIME = 180
_MAX_EVENT_BYTES = 4096


class ZSpaceAuthorizationError(Exception):
    """A safe authorization message, with no vendor output or secrets."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class _Pending:
    id: str
    owner: str = field(repr=False)
    url: str = field(repr=False)
    expires: float
    process: subprocess.Popen[bytes] = field(repr=False)
    timer: Timer = field(repr=False)


def _available_client(settings: Settings) -> ZSpaceRecycleClient | None:
    try:
        client = zspace_client(settings)
        if client is None:
            return None
        home = client.cli_home
        executable = client.executable
        if (home is None or home.resolve(strict=True) != home
                or executable.resolve(strict=True) != executable):
            raise ValueError
        info, binary = home.stat(), executable.stat()
        effective_user = os.geteuid()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != effective_user
                or stat.S_IMODE(info.st_mode) != 0o700 or not stat.S_ISREG(binary.st_mode)
                or binary.st_uid not in (0, effective_user) or binary.st_mode & 0o022
                or not os.access(home, os.W_OK | os.X_OK)
                or not os.access(executable, os.X_OK)):
            raise ValueError
    except (ValueError, OSError, RuntimeError):
        raise ZSpaceAuthorizationError(503, "极空间授权需要已挂载的官方 CLI 和私有凭证目录") from None
    return client


def _authorization_event(process: subprocess.Popen[bytes]) -> tuple[str, int]:
    """Read a bounded event with a finite deadline even on a stuck CLI pipe."""
    assert process.stdout is not None
    deadline = time.monotonic() + _START_TIMEOUT
    data = bytearray()
    with DefaultSelector() as ready:
        ready.register(process.stdout, EVENT_READ)
        while len(data) < _MAX_EVENT_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not ready.select(remaining):
                raise ValueError
            chunk = os.read(process.stdout.fileno(), _MAX_EVENT_BYTES - len(data))
            if not chunk:
                raise ValueError
            data.extend(chunk)
            if b"\n" in data:
                break
    if b"\n" not in data:
        raise ValueError
    result = json.loads(data.partition(b"\n")[0])
    if not isinstance(result, dict):
        raise ValueError
    url, expires = result.get("url"), result.get("expires_in")
    if (result.get("event") != "oauth_authorization" or result.get("code_input") != "stdin"
            or type(expires) is not int or not 0 < expires <= _MAX_AUTH_LIFETIME
            or not isinstance(url, str) or not url.isascii() or len(url) > 1000
            or any(ord(char) < 33 or ord(char) == 127 for char in url)):
        raise ValueError
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "oauth.zconnect.cn"
            or parsed.path != "/wbui/authorize" or parsed.fragment):
        raise ValueError
    params = parse_qs(parsed.query, strict_parsing=True, max_num_fields=2)
    states = params.get("state", [])
    if (set(params) != {"state", "client_id"} or params["client_id"] != ["ZspCli"]
            or len(states) != 1 or not re.fullmatch(r"[0-9a-f]{32}", states[0])):
        raise ValueError
    return url, expires


def _stop(process: subprocess.Popen[bytes]) -> None:
    for pipe in (process.stdin, process.stdout):
        if pipe is not None:
            pipe.close()
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass


class ZSpaceAuthorization:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = Lock()
        self._pending: _Pending | None = None

    def status(self) -> str:
        try:
            client = _available_client(self._settings)
            if client is None:
                return "unconfigured"
            result = client.run_cli("status")
            if not isinstance(result, dict) or type(result.get("logged_in")) is not bool:
                return "unavailable"
            return "authorized" if result["logged_in"] else "needs_login"
        except (ZSpaceAuthorizationError, ZSpaceRecycleError):
            return "unavailable"

    def _discard(self) -> None:
        """Called under the lock. Cancelling a handoff never logs the Worker out."""
        pending, self._pending = self._pending, None
        if pending is not None:
            pending.timer.cancel()
            _stop(pending.process)

    def _current(self) -> _Pending | None:
        pending = self._pending
        if pending is not None and (pending.expires <= time.monotonic() or pending.process.poll() is not None):
            self._discard()
        return self._pending

    def _expire(self, authorization_id: str) -> None:
        with self._lock:
            if self._pending is not None and self._pending.id == authorization_id:
                self._discard()

    def close(self) -> None:
        with self._lock:
            self._discard()

    def start(self, owner: str) -> dict:
        client = _available_client(self._settings)
        if client is None:
            raise ZSpaceAuthorizationError(409, "请先配置极空间回收参数")
        with self._lock:
            pending = self._current()
            if pending is not None:
                if pending.owner != owner:
                    raise ZSpaceAuthorizationError(409, "已有管理员正在授权，请稍后重试")
                return self._public_pending(pending)
            started = time.monotonic()
            process = None
            try:
                process = subprocess.Popen(
                    client.cli_arguments("login", "--no-open", "--auth-code-stdin"),
                    env=client.cli_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                url, lifetime = _authorization_event(process)
                deadline = started + lifetime
                if deadline <= time.monotonic() or process.poll() is not None:
                    raise ValueError
            except (OSError, ValueError):
                if process is not None:
                    _stop(process)
                raise ZSpaceAuthorizationError(503, "无法生成极空间授权链接，请检查 NAS 网络和授权目录") from None
            authorization_id = secrets.token_urlsafe(24)
            timer = Timer(max(0, deadline - time.monotonic()), self._expire, args=(authorization_id,))
            timer.daemon = True
            pending = _Pending(authorization_id, owner, url, deadline, process, timer)
            self._pending = pending
            timer.start()
            return self._public_pending(pending)

    @staticmethod
    def _public_pending(pending: _Pending) -> dict:
        return {"id": pending.id, "url": pending.url,
                "expires_in": max(0, math.ceil(pending.expires - time.monotonic()))}

    def _owned(self, owner: str, authorization_id: str) -> _Pending:
        pending = self._current()
        if pending is None or pending.owner != owner or pending.id != authorization_id:
            raise ZSpaceAuthorizationError(409, "授权会话已失效，请重新发起授权")
        return pending

    def cancel(self, owner: str, authorization_id: str) -> None:
        with self._lock:
            self._owned(owner, authorization_id)
            self._discard()

    def complete(self, owner: str, authorization_id: str, code: str) -> dict:
        client = _available_client(self._settings)
        if client is None:
            raise ZSpaceAuthorizationError(409, "请先配置极空间回收参数")
        with self._lock:
            pending = self._owned(owner, authorization_id)
            try:
                # Send only to the live official process. Ignore all CLI diagnostics.
                pending.process.communicate((code + "\n").encode("ascii"), _COMPLETE_TIMEOUT)
                if pending.process.returncode:
                    raise ZSpaceAuthorizationError(409, "极空间未完成授权，请生成新链接并重试")
                state = client.run_cli("status")
                if not isinstance(state, dict) or state.get("logged_in") is not True:
                    raise ZSpaceAuthorizationError(409, "极空间未完成授权，请生成新链接并重试")
            except (OSError, subprocess.TimeoutExpired):
                raise ZSpaceAuthorizationError(409, "极空间授权请求失败，请生成新链接并重试") from None
            finally:
                self._discard()
            try:
                client.run_cli("doctor")
                client.verify_mapping()
                verified = True
            except ZSpaceRecycleError:
                verified = False
            return {"status": "authorized", "mapping_verified": verified}
