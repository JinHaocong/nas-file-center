"""Persist the in-flight FUSE hardlink before retiring either file binding."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class LinkIntent:
    """The latest link in one frozen unit, bound to both open directory inodes."""

    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def binding(source_fd: int, source: str, target_fd: int, target: str, identity: list[int]) -> dict:
        old_dir, new_dir = os.fstat(source_fd), os.fstat(target_fd)
        return {
            "source": [old_dir.st_dev, old_dir.st_ino, source],
            "target": [new_dir.st_dev, new_dir.st_ino, target], "identity": identity,
        }

    def save(self, binding: dict) -> None:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                prefix=f".{self.path.name}.", delete=False) as stream:
            staged = Path(stream.name)
            try:
                json.dump(binding, stream)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(staged, self.path)
                fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                staged.unlink(missing_ok=True)

    def matches(self, binding: dict) -> bool:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return False
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            return json.load(stream) == binding
