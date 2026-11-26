"""Publish a frozen directory tree on mounts without no-replace rename."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
from unicodedata import normalize

from app.batch.media_package_organizer import MAX_DEPTH, MAX_PACKAGE_DIRECTORIES, MAX_PACKAGE_FILES


_OWNER = ".nfc-lift-owner.json"


def _identity(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino]


def _fold(name: str) -> str:
    return normalize("NFC", name).casefold()


def _entry(parent: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _safe_name(name: str) -> bool:
    return (isinstance(name, str) and name not in {"", ".", ".."} and "/" not in name
            and "\0" not in name and not _fold(name).startswith(".nfc-"))


def validate_lift_layout(layout: dict, child: dict) -> dict[Path, list[int]]:
    """Bind exact names and source directories to the previously confirmed file inventory."""
    directories = {}
    files = []
    device = child["identity"][0]
    pending = [(Path(), layout, 0)]
    while pending:
        relative, tree, depth = pending.pop()
        if (depth > MAX_DEPTH or not isinstance(tree, dict)
                or tree.keys() != {"identity", "directories", "files"}):
            raise ValueError("上提的目录布局无效")
        identity, children, rows = tree["identity"], tree["directories"], tree["files"]
        if (not _valid_identity(identity, 2, device) or not isinstance(children, dict)
                or not isinstance(rows, dict) or children.keys() & rows.keys()):
            raise ValueError("上提的目录布局无效")
        names = children.keys() | rows.keys()
        if (not all(_safe_name(name) for name in names)
                or len({_fold(name) for name in names}) != len(names)):
            raise ValueError("上提布局含无效或重名路径")
        directories[relative] = identity
        pending.extend((relative / name, value, depth + 1) for name, value in children.items())
        if (len(directories) + len(pending) > MAX_PACKAGE_DIRECTORIES
                or len(files) + len(rows) > MAX_PACKAGE_FILES):
            raise ValueError("上提的目录布局超过范围限制")
        for entry in rows.values():
            if not _valid_identity(entry, 4, device) or entry[2] < 0:
                raise ValueError("上提的文件身份无效")
            files.append(entry)
    digest = hashlib.sha256()
    for entry in sorted(files):
        digest.update(":".join(map(str, entry)).encode("ascii") + b"\n")
    if directories[Path()] != child["identity"] or digest.hexdigest() != child["content"]:
        raise ValueError("上提布局与原确认的目录内容不一致")
    return directories


def _valid_identity(identity: object, length: int, device: int) -> bool:
    return (isinstance(identity, list) and len(identity) == length
            and all(type(value) is int for value in identity)
            and identity[0] == device and identity[1] > 0)


@contextmanager
def _open(parent: int | None, name: str):
    if parent is None:
        yield None
        return
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError:
        yield None
    else:
        try:
            yield fd
        finally:
            os.close(fd)


def _check_file(fd: int | None, name: str, identity: list[int]) -> bool:
    info = _entry(fd, name) if fd is not None else None
    if info is None:
        return False
    if (not stat.S_ISREG(info.st_mode)
            or [*_identity(info), info.st_size, info.st_mtime_ns] != identity):
        raise ValueError(f"上提文件身份已变化：{name}")
    return True


def _check_binding(parent: int | None, name: str, fd: int | None) -> None:
    if parent is not None:
        info = _entry(parent, name)
        if fd is None and info is None:
            return
        if (fd is not None and info is not None and stat.S_ISDIR(info.st_mode)
                and _identity(info) == _identity(os.fstat(fd))):
            return
        raise ValueError(f"上提目录在执行期间已变化：{name}")


class _Lift:
    def __init__(self, token: str, *, source_active: bool, checkpoint: Callable[[], None]):
        self.token = token
        self.source_active = source_active
        self.checkpoint = checkpoint
        self.completed: dict[Path, list[int]] = {}

    def _marker(self, path: Path, fd: int) -> bytes:
        binding = [self.token, path.as_posix(), _identity(os.fstat(fd))]
        return json.dumps(binding, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _check_target(self, fd: int, path: Path, phase: str) -> set[str]:
        from app.batch.media_package_execution import _compat_marker_matches

        names = set(os.listdir(fd))
        if _OWNER in names:
            if phase == "completed":
                raise ValueError(f"上提目录仍有恢复记录：{path}")
            if not _compat_marker_matches(fd, _OWNER, self._marker(path, fd)):
                raise ValueError(f"上提目录的恢复记录已变化：{path}")
            names.remove(_OWNER)
        elif self.source_active and phase not in {"clean", "completed"}:
            raise ValueError(f"上提目标已存在且不属于当前任务：{path}")
        return names

    def _create_target(self, parent: int, name: str, path: Path, source: int,
                       guard: Callable[[], None]) -> None:
        from app.batch.media_package_execution import _compat_create_marker

        os.fsync(parent)
        guard()
        if any(_fold(entry) == _fold(name) for entry in os.listdir(parent)):
            raise ValueError(f"上提目标已被占用：{path}")
        try:
            os.mkdir(name, mode=stat.S_IMODE(os.fstat(source).st_mode), dir_fd=parent)
        except FileExistsError as exc:
            raise ValueError(f"上提目标已被占用：{path}") from exc
        with _open(parent, name) as target:
            if target is None or os.listdir(target):
                raise ValueError(f"新建上提目标已变化：{path}")
            _check_binding(parent, name, target)
            _compat_create_marker(target, _OWNER, self._marker(path, target))
        os.fsync(parent)

    def walk(self, source_parent: int | None, target_parent: int | None, name: str, path: Path,
             tree: dict, phase: str, parent_guard: Callable[[], None]) -> None:
        """Reconcile one tree using anchored directory descriptors at every level."""
        self.checkpoint()
        with _open(source_parent, name) as source:
            if source is not None and _identity(os.fstat(source)) != tree["identity"]:
                raise ValueError(f"上提源目录身份已变化：{path}")
            if phase == "publish" and _entry(target_parent, name) is None and source is not None:
                def before_create() -> None:
                    parent_guard()
                    _check_binding(source_parent, name, source)

                self._create_target(target_parent, name, path, source, before_create)
            with _open(target_parent, name) as target:
                def guard() -> None:
                    parent_guard()
                    _check_binding(source_parent, name, source)
                    _check_binding(target_parent, name, target)

                if target is not None and os.fstat(target).st_dev != tree["identity"][0]:
                    raise ValueError(f"上提目标跨越了挂载边界：{path}")
                if (source is None and target is None) or (phase != "check" and target is None):
                    raise ValueError(f"缺少上提目录：{path}")
                guard()
                allowed = tree["files"].keys() | tree["directories"].keys()
                source_names = set(os.listdir(source)) if source is not None else set()
                target_names = self._check_target(target, path, phase) if target is not None else set()
                if source_names - allowed or target_names - allowed:
                    raise ValueError(f"上提目录出现未确认的内容：{path}")
                for child, layout in tree["directories"].items():
                    self.walk(source, target, child, path / child, layout, phase, guard)
                for leaf, identity in tree["files"].items():
                    self._file(source, target, leaf, identity, phase, guard)
                self._finish(source_parent, source, target, name, path, phase, guard)

    @staticmethod
    def _file(source: int | None, target: int | None, name: str, identity: list[int],
              phase: str, guard: Callable[[], None]) -> None:
        origin = _check_file(source, name, identity)
        destination = _check_file(target, name, identity)
        if not (origin or destination) or (not destination and phase not in {"check", "publish"}):
            raise ValueError(f"上提文件缺失：{name}")
        if phase == "publish" and not destination:
            guard()
            if not _check_file(source, name, identity):
                raise ValueError(f"上提文件已离开源目录：{name}")
            try:
                os.link(name, name, src_dir_fd=source, dst_dir_fd=target, follow_symlinks=False)
            except FileExistsError as exc:
                raise ValueError(f"上提目标文件已被占用：{name}") from exc
            if not _check_file(target, name, identity):
                raise ValueError(f"上提链接未能校验：{name}")
        elif phase == "retire" and origin:
            guard()
            if not (_check_file(source, name, identity) and _check_file(target, name, identity)):
                raise ValueError(f"无法核对上提文件的两条链接：{name}")
            os.unlink(name, dir_fd=source)

    def _finish(self, source_parent: int | None, source: int | None, target: int | None,
                name: str, path: Path, phase: str, guard: Callable[[], None]) -> None:
        if phase == "completed":
            guard()
            self.completed[path] = _identity(os.fstat(target))
        elif phase == "publish":
            os.fsync(target)
        elif phase == "retire" and source is not None:
            guard()
            os.fsync(source)
            os.rmdir(name, dir_fd=source_parent)
            os.fsync(source_parent)
        elif phase == "clean" and _entry(target, _OWNER) is not None:
            from app.batch.media_package_execution import _compat_marker_matches

            guard()
            if _compat_marker_matches(target, _OWNER, self._marker(path, target)):
                os.unlink(_OWNER, dir_fd=target)
                os.fsync(target)


def check_tree_lift(source: int | None, target: int, name: str, tree: dict, token: str,
                    *, checkpoint: Callable[[], None]) -> None:
    has_source = source is not None and _entry(source, name) is not None
    lift = _Lift(token, source_active=has_source, checkpoint=checkpoint)
    lift.walk(source, target, name, Path(name), tree, "check" if has_source else "complete", checkpoint)


def execute_tree_lift(source: int | None, target: int, name: str, tree: dict, token: str,
                      *, checkpoint: Callable[[], None], fence: Callable[[], None]) -> None:
    has_source = source is not None and _entry(source, name) is not None
    lift = _Lift(token, source_active=has_source, checkpoint=checkpoint)
    if has_source:
        lift.walk(source, target, name, Path(name), tree, "check", checkpoint)
        lift.walk(source, target, name, Path(name), tree, "publish", fence)
        os.fsync(target)
        lift.walk(source, target, name, Path(name), tree, "complete", checkpoint)
        lift.walk(source, target, name, Path(name), tree, "retire", fence)
    else:
        lift.walk(source, target, name, Path(name), tree, "complete", checkpoint)
    lift.walk(source, target, name, Path(name), tree, "clean", fence)
    lift.walk(source, target, name, Path(name), tree, "completed", checkpoint)


def verify_completed_lift(path: Path, layout: dict, child: dict, *,
                          checkpoint: Callable[[], None]) -> dict[Path, tuple[list[int], list[int]]]:
    """Prove a final tree and return each directory's original and current identities."""
    from app.batch.media_package_execution import _open_folder

    directories = validate_lift_layout(layout, child)
    fd = _open_folder(path.parent)
    try:
        lift = _Lift("", source_active=False, checkpoint=checkpoint)
        lift.walk(None, fd, path.name, Path(path.name), layout, "completed", checkpoint)
    finally:
        os.close(fd)
    return {path / relative: (identity, lift.completed[Path(path.name) / relative])
            for relative, identity in directories.items()}
