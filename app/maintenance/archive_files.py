from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Iterator
import zlib


class HistoryArchiveUnavailable(OSError):
    """An archived history chunk cannot be verified or read."""


@contextmanager
def durable_file(directory: Path, *, directory_mode: int = 0o700) -> Iterator[Path]:
    """Stage a private file on the same filesystem as its eventual destination."""
    # The caller supplies a direct child of the application's initialized config directory.
    try:
        directory.mkdir(mode=directory_mode)
    except FileExistsError:
        pass
    else:
        directory.chmod(directory_mode)
    sync_directory(directory.parent)
    with NamedTemporaryFile(dir=directory, prefix=".pending-", delete=False) as temporary:
        path = Path(temporary.name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def sync_directory(directory: Path) -> None:
    """Make published archive or backup names durable before proceeding."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_archive_content(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        try:
            with gzip.GzipFile(fileobj=source, mode="rb") as archived:
                return archived.read()
        except (EOFError, zlib.error) as error:
            raise OSError(f"Unusable history archive: {path.name}") from error


def read_history_archive(archive_dir: Path, stream: str, name: str) -> list[dict]:
    """Return archive rows only when the file name, stream, and checksum agree."""
    match = re.fullmatch(rf"{re.escape(stream)}-([a-f0-9]{{64}})\.json\.gz", name)
    if match is None or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", stream) is None:
        raise HistoryArchiveUnavailable("Invalid history archive file name")
    try:
        content = _read_archive_content(archive_dir / name)
        if hashlib.sha256(content).hexdigest() != match[1]:
            raise ValueError("History archive checksum mismatch")
        payload = json.loads(content)
        if (not isinstance(payload, dict) or payload.get("version") != 1
                or payload.get("stream") != stream or not isinstance(payload.get("rows"), list)):
            raise ValueError("Invalid history archive contents")
        return payload["rows"]
    except (OSError, ValueError) as error:
        raise HistoryArchiveUnavailable(name) from error


def write_history_archive(
    archive_dir: Path, stream: str, rows: Iterable[dict],
) -> Path:
    """Publish a content-addressed archive before the caller removes source rows."""
    if re.fullmatch(r"[a-z][a-z0-9-]{0,63}", stream) is None:
        raise ValueError("Invalid history archive stream")
    payload = {"version": 1, "stream": stream, "rows": list(rows)}
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    name = f"{stream}-{hashlib.sha256(content).hexdigest()}.json.gz"
    destination = archive_dir / name
    # API and Worker can run under separate UIDs that share the application group.
    with durable_file(archive_dir, directory_mode=0o2770) as staged:
        with staged.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", compresslevel=6, fileobj=output, mtime=0) as archived:
                archived.write(content)
            output.flush()
            os.fchmod(output.fileno(), 0o640)
            os.fsync(output.fileno())
        try:
            os.link(staged, destination)
        except FileExistsError:
            # A prior DB transaction may have rolled back after publishing this file.
            # Reuse only an exact copy, and leave a mismatched file in place for inspection.
            if _read_archive_content(destination) != content:
                raise OSError(f"History archive contents do not match: {name}")
        sync_directory(archive_dir)
    return destination
