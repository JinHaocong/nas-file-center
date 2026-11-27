from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time


PROBE_NAME = ".nfc-zspace-recycle-probe"
_CLI_TIMEOUT = 12
_CONFIRM_TIMEOUT = 5.0
_CLI_ENV = ("PATH", "HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "TMPDIR", "LANG", "LC_ALL",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY")


class ZSpaceRecycleError(OSError):
    """The official recycle operation did not reach a confirmed outcome."""


def _valid_parts(parts: Sequence[str]) -> bool:
    return all(part not in {"", ".", ".."} and part.casefold() != ".recycle"
               and "\\" not in part and all(ord(char) >= 32 for char in part) for part in parts)


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


@dataclass(frozen=True)
class ZSpaceRecycleClient:
    executable: Path
    profile: str
    local_root: Path
    remote_root: str
    cli_home: Path | None = None

    def __post_init__(self) -> None:
        if not self.executable.is_absolute() or not self.local_root.is_absolute():
            raise ValueError("极空间命令和容器映射根必须使用绝对路径")
        if self.local_root.anchor != "/" or not self.local_root.parts[1:] or not _valid_parts(self.local_root.parts[1:]):
            raise ValueError("容器映射根无效")
        if not self.remote_root.startswith("/") or not _valid_parts(self.remote_root[1:].split("/")):
            raise ValueError("极空间映射根无效")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.profile) or self.profile.endswith("."):
            raise ValueError("极空间授权 profile 名称无效")
        home = self.cli_home
        if home is None and os.environ.get("ZSPACE_CLI_HOME"):
            home = Path(os.environ["ZSPACE_CLI_HOME"])
        if home is not None and not home.is_absolute():
            raise ValueError("极空间授权目录必须使用绝对路径")
        object.__setattr__(self, "cli_home", home)

    def remote_path(self, source: Path) -> str:
        """Translate a descendant without resolving it into a different share."""
        if not source.is_relative_to(self.local_root):
            raise ValueError("文件超出极空间映射范围")
        relative = source.relative_to(self.local_root)
        if not relative.parts or not _valid_parts(relative.parts):
            raise ValueError("极空间文件路径无效")
        return self.remote_root + "/" + relative.as_posix()

    def _run(self, action: str, params: dict, *, confirm: bool = False):
        args = ["file", action, "--params", json.dumps(params, ensure_ascii=False)]
        if confirm:
            args.append("--yes")
        return self.run_cli(*args)

    def cli_arguments(self, *args: str) -> list[str]:
        return [str(self.executable), "--profile", self.profile, "--timeout", str(_CLI_TIMEOUT), *args]

    def cli_environment(self) -> dict[str, str]:
        # The official CLI needs its runtime and credential location, never the application's secrets.
        env = {key: os.environ[key] for key in _CLI_ENV if key in os.environ}
        if self.cli_home is not None:
            env["ZSPACE_CLI_HOME"] = str(self.cli_home)
        return env

    def run_cli(self, *args: str):
        try:
            result = subprocess.run(
                self.cli_arguments(*args), env=self.cli_environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=_CLI_TIMEOUT + 3,
            )
        except subprocess.TimeoutExpired:
            raise ZSpaceRecycleError("极空间命令超时，回收结果待核对") from None
        except OSError:
            raise ZSpaceRecycleError("无法启动极空间官方命令") from None
        if result.returncode != 0:
            raise ZSpaceRecycleError("极空间命令未返回成功")
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError):
            raise ZSpaceRecycleError("极空间命令返回了无法验证的结果") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True or "data" not in payload:
            raise ZSpaceRecycleError("极空间命令未确认成功")
        return payload["data"]

    def _read_probe(self) -> bytes:
        probe = self.local_root / PROBE_NAME
        try:
            if self.local_root.resolve(strict=True) != self.local_root:
                raise ValueError
            initial = probe.lstat()
            if not stat.S_ISREG(initial.st_mode) or initial.st_size not in (64, 65) or initial.st_nlink != 1:
                raise ValueError
            fd = os.open(probe, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                opened = os.fstat(fd)
                if not stat.S_ISREG(opened.st_mode) or _identity(initial) != _identity(opened):
                    raise ValueError
                content = os.read(fd, 66)
                if _identity(os.fstat(fd)) != _identity(initial) or _identity(probe.lstat()) != _identity(initial):
                    raise ValueError
            finally:
                os.close(fd)
        except (OSError, RuntimeError, ValueError):
            raise ZSpaceRecycleError("容器映射根的极空间验证标记缺失、无效或已变化") from None
        if not re.fullmatch(rb"[0-9a-f]{64}\n?", content):
            raise ZSpaceRecycleError("容器映射根的极空间验证标记格式无效")
        return content

    def _binding_id(self, probe: bytes) -> str:
        home = [str(self.cli_home)] if self.cli_home is not None else [
            str(Path.home()), os.environ.get("XDG_CONFIG_HOME", ""),
        ]
        config = [str(self.executable), self.profile, str(self.local_root), self.remote_root,
                  *home]
        return hashlib.sha256(json.dumps(config).encode("utf-8") + b"\0" + probe).hexdigest()

    def binding_id(self) -> str:
        """Freeze the selected local configuration and probe without any NAS request."""
        return self._binding_id(self._read_probe())

    def verify_mapping(self) -> str:
        """Use a bounded NAS read to prove the configured profile exposes the same root."""
        expected = self._read_probe()
        path = self.remote_path(self.local_root / PROBE_NAME)
        data = self._run("read", {"path": path, "max_bytes": 66, "encoding": "base64"})
        try:
            if (not isinstance(data, dict) or data.get("path") != path or data.get("encoding") != "base64"
                    or data.get("offset") != 0 or data.get("truncated") is not False
                    or data.get("size") != len(expected) or data.get("bytes") != len(expected)):
                raise ValueError
            encoded = data.get("content")
            if not isinstance(encoded, str) or len(encoded) > 88:
                raise ValueError
            observed = base64.b64decode(encoded, validate=True)
            if observed != expected or self._read_probe() != expected:
                raise ValueError
        except ValueError:
            raise ZSpaceRecycleError("极空间验证标记与容器路径不匹配") from None
        return self._binding_id(expected)

    def _local_identity(self, path: Path) -> tuple[int, int, int, int] | None:
        try:
            if path.parent.resolve(strict=True) != path.parent:
                raise ZSpaceRecycleError("回收文件的父目录已变化")
            try:
                info = path.lstat()
            except FileNotFoundError:
                return None
            if not stat.S_ISREG(info.st_mode):
                raise ZSpaceRecycleError("回收路径已不再指向原普通文件")
            return _identity(info)
        except ZSpaceRecycleError:
            raise
        except (OSError, RuntimeError):
            raise ZSpaceRecycleError("无法核对回收文件原路径") from None

    def recycle(self, source: Path, *, identity: Sequence[int], fence: Callable[[], None]) -> None:
        """Request one native soft deletion and verify the confirmed file left its path."""
        path = self.remote_path(source)
        expected = tuple(identity)
        fence()
        if self._local_identity(source) != expected:
            raise ZSpaceRecycleError("回收文件已变化，需重新预览")
        self._run("delete", {"paths": [path]}, confirm=True)
        deadline = time.monotonic() + _CONFIRM_TIMEOUT
        while True:
            current = self._local_identity(source)
            if current is None:
                fence()
                return
            if current != expected:
                raise ZSpaceRecycleError("回收期间原路径已被替换，结果待核对")
            if time.monotonic() >= deadline:
                raise ZSpaceRecycleError("极空间已接收请求，原文件仍在，回收结果待核对")
            time.sleep(0.1)
