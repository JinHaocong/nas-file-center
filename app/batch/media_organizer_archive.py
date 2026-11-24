"""Read-only discovery and resumable whole-directory moves for repeated archive shells."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from unicodedata import normalize

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_organizer import MAX_DEPTH, MAX_PACKAGE_DIRECTORIES, MAX_PACKAGE_FILES
from app.fs_ops import probe_directory_rename_noreplace_compat_at, rename_noreplace_at

PROMOTE_ARCHIVE_CHILDREN = "promote_repeated_archive_children"
_ARCHIVE_LABELS = {"old", "archive", "backup", "bak", "旧版", "备份"}
_MAX_CHILDREN = 200


def is_repeated_archive(unit: Path) -> bool:
    """Only exact-name, explicitly named archive shells qualify."""
    return unit.name == unit.parent.name and unit.name.casefold() in _ARCHIVE_LABELS


def _fold(name: str) -> str:
    return normalize("NFC", name).casefold()


def _identity(info: os.stat_result) -> list[int]:
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("归档目录身份已变化")
    return [info.st_dev, info.st_ino]


@contextmanager
def _directory(path: Path):
    fd = _open_directory_nofollow(path)
    try:
        yield fd
    finally:
        os.close(fd)


def _binding(parent_fd: int, name: str) -> list[int] | None:
    try:
        return _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _check_archive_scope(unit: Path, protected_roots: tuple[Path, ...]) -> None:
    if (not is_repeated_archive(unit) or not unit.is_absolute() or ".." in unit.parts
            or any(name.casefold().startswith(".nfc-") for name in unit.parts)
            or any(unit.parent.is_relative_to(root) or root.is_relative_to(unit)
                   for root in protected_roots)):
        raise ValueError("重复归档目录超出允许范围")


def _tree_content_digest(unit: Path, identity: list[int], protected_roots: tuple[Path, ...],
                         check_cancelled: Callable[[], None] | None = None) -> str:
    """Bind the file identity multiset while allowing media renames inside the same child."""
    if any(unit.is_relative_to(root) or root.is_relative_to(unit) for root in protected_roots):
        raise ValueError("重复归档包含受保护目录")
    pending = [(unit, 0)]
    directories = 0
    files = []
    last_check = 0.0

    def checkpoint() -> None:
        nonlocal last_check
        now = time.monotonic()
        if check_cancelled is not None and now - last_check >= 0.8:
            check_cancelled()
            last_check = now

    while pending:
        path, depth = pending.pop()
        directories += 1
        if depth > MAX_DEPTH or directories > MAX_PACKAGE_DIRECTORIES:
            raise ValueError("重复归档超过目录范围限制")
        checkpoint()
        with _directory(path) as fd:
            before = os.fstat(fd)
            current = _identity(before)
            if current[0] != identity[0] or (depth == 0 and current != identity):
                raise ValueError("重复归档目录身份或磁盘已变化")
            with os.scandir(fd) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    if info.st_dev != identity[0] or entry.name.casefold().startswith(".nfc-"):
                        raise ValueError("重复归档包含跨设备目录或待恢复文件")
                    if stat.S_ISDIR(info.st_mode):
                        pending.append((path / entry.name, depth + 1))
                        if directories + len(pending) > MAX_PACKAGE_DIRECTORIES:
                            raise ValueError("重复归档超过目录范围限制")
                    elif stat.S_ISREG(info.st_mode):
                        # Keep duplicate identities: they account for distinct hardlinks
                        # and must not disappear during a previous media operation.
                        files.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
                        if len(files) > MAX_PACKAGE_FILES:
                            raise ValueError("重复归档超过文件数量限制")
                        if len(files) % 256 == 0:
                            checkpoint()
                    else:
                        raise ValueError("重复归档包含符号链接或特殊文件")
            after = os.fstat(fd)
            if (after.st_mtime_ns, after.st_ctime_ns) != (before.st_mtime_ns, before.st_ctime_ns):
                raise ValueError(f"读取重复归档目录时内容已变化：{path}")
    files.sort()
    digest = hashlib.sha256()
    for device, inode, size, mtime_ns in files:
        digest.update(f"{device}:{inode}:{size}:{mtime_ns}\n".encode("ascii"))
    return digest.hexdigest()


def _snapshot(unit: Path, protected_roots: tuple[Path, ...],
              check_cancelled: Callable[[], None] | None = None) -> dict:
    _check_archive_scope(unit, protected_roots)
    with _directory(unit.parent) as archive_fd, _directory(unit) as wrapper_fd:
        archive = _identity(os.fstat(archive_fd))
        wrapper = _identity(os.fstat(wrapper_fd))
        if wrapper[0] != archive[0] or wrapper != _binding(archive_fd, unit.name):
            raise ValueError("重复归档目录身份或磁盘已变化")
        names = sorted(os.listdir(wrapper_fd), key=lambda name: (_fold(name), name))
        if not 0 < len(names) <= _MAX_CHILDREN:
            raise ValueError("重复归档层不包含可上提的子目录")
        occupied = {_fold(name) for name in os.listdir(archive_fd)}
        children = {}
        for name in names:
            key = _fold(name)
            if key in occupied or key.startswith(".nfc-"):
                raise ValueError(f"重复归档上提目标已占用或保留：{unit.parent / name}")
            occupied.add(key)
            identity = _binding(wrapper_fd, name)
            if identity is None:
                raise ValueError("重复归档子目录已变化")
            content = _tree_content_digest(unit / name, identity, protected_roots, check_cancelled)
            if any((unit.parent / name).is_relative_to(root) or root.is_relative_to(unit.parent / name)
                   for root in protected_roots):
                raise ValueError("重复归档目标目录受保护")
            children[name] = {"identity": identity, "content": content}
        return {"archive": archive, "wrapper": wrapper, "children": children}


def preview_repeated_archive(unit: Path, protected_roots: tuple[Path, ...],
                             check_cancelled: Callable[[], None] | None = None) -> dict | None:
    """Describe whole-child moves without counting descendants twice."""
    try:
        snapshot = _snapshot(unit, protected_roots, check_cancelled)
    except (OSError, ValueError):
        # A rejected shell still has its independent descendant media plans.
        return None
    moves = [{
        "source": str(unit / name), "target": str(unit.parent / name), "target_name": name,
        "kind": "Directory", "bytes": 0,
    } for name in snapshot["children"]]
    return {
        "unit": str(unit), "organizer_mode": "semantic", "operation": PROMOTE_ARCHIVE_CHILDREN,
        "status": "ready", "reason": "重复归档层的子目录整体上提", "read_only": True,
        "totals": {"P": 0, "V": 0, "Other": 0}, "total_files": 0, "total_bytes": 0,
        "groups": [], "conflicts": [], "total_proposals": len(moves), "needed_moves": len(moves),
        "renamed_count": 0, "actual_moves": len(moves), "wrapper_cleanup": [str(unit)],
        "input_fingerprint": _fingerprint(snapshot), "_mapping_items": moves, "sample_moves": moves[:10],
    }


def freeze_repeated_archive(unit: Path, protected_roots: tuple[Path, ...], fingerprint: str,
                            job_id: int, *, check_cancelled: Callable[[], None]) -> dict:
    """Bind the preview to the exact source and target directory identities."""
    from app.batch.media_package_execution import MANIFEST_VERSION

    snapshot = _snapshot(unit, protected_roots, check_cancelled)
    if fingerprint != _fingerprint(snapshot):
        raise ValueError("重复归档目录在预览后已变化")
    return {
        "package": str(unit), "schema_version": MANIFEST_VERSION, "job_id": job_id,
        "organizer_mode": "semantic", "operation": PROMOTE_ARCHIVE_CHILDREN,
        "snapshot": snapshot, "input_fingerprint": fingerprint,
    }


def _location(unit: Path, archive_fd: int, wrapper_fd: int | None, name: str, identity: list[int]) -> Path:
    """Accept either the frozen source or the identical already published directory."""
    origin = _binding(wrapper_fd, name) if wrapper_fd is not None else None
    destination = _binding(archive_fd, name)
    wanted = _fold(name)
    if any(other != name and _fold(other) == wanted for other in os.listdir(archive_fd)):
        raise ValueError(f"重复归档目标与同名目录冲突：{unit.parent / name}")
    if origin == identity and destination is None:
        return unit / name
    if origin is None and destination == identity:
        return unit.parent / name
    raise ValueError(f"重复归档源或目标身份已变化：{name}")


def _promote(source_fd: int, target_fd: int, name: str, *, allow_fuse_compat: bool,
             revalidate: Callable[[], None]) -> None:
    try:
        try:
            rename_noreplace_at(source_fd, name, target_fd, name)
        except NotImplementedError as exc:
            raise OSError(errno.EOPNOTSUPP, str(exc)) from exc
    except OSError as exc:
        if (exc.errno != errno.EOPNOTSUPP or not allow_fuse_compat
                or probe_directory_rename_noreplace_compat_at(source_fd, target_fd) is not True):
            raise
        # The probe may take time. Recheck lease and path bindings again before
        # the proven no-clobber relocation on the same open descriptors.
        revalidate()
        os.rename(name, name, src_dir_fd=source_fd, dst_dir_fd=target_fd)


def _is_directory_identity(value: object) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and type(value[0]) is int and value[0] >= 0
            and type(value[1]) is int and value[1] > 0)


def _valid_child(child: object, device: int) -> bool:
    if not isinstance(child, dict) or child.keys() != {"identity", "content"}:
        return False
    identity, digest = child["identity"], child["content"]
    return (_is_directory_identity(identity) and identity[0] == device
            and isinstance(digest, str) and len(digest) == 64
            and all(char in "0123456789abcdef" for char in digest))


def _valid_snapshot(snapshot: object, wrapper_name: str) -> bool:
    """Validate structural manifests separately from the file manifest format."""
    if not isinstance(snapshot, dict) or snapshot.keys() != {"archive", "wrapper", "children"}:
        return False
    archive, wrapper, children = (snapshot[key] for key in ("archive", "wrapper", "children"))
    if (not _is_directory_identity(archive) or not _is_directory_identity(wrapper)
            or archive[0] != wrapper[0] or not isinstance(children, dict)
            or not 0 < len(children) <= _MAX_CHILDREN):
        return False
    folded = {_fold(wrapper_name)}
    for name, child in children.items():
        if (not isinstance(name, str) or not name or name in {".", ".."} or "\x00" in name
                or Path(name).name != name or not _valid_child(child, archive[0])):
            return False
        canonical = _fold(name)
        if canonical in folded or canonical.startswith(".nfc-"):
            return False
        folded.add(canonical)
    return True


def _verify_content(path: Path, child: dict, protected_roots: tuple[Path, ...],
                    lease_fence: Callable[[], None]) -> None:
    if _tree_content_digest(path, child["identity"], protected_roots, lease_fence) != child["content"]:
        raise ValueError(f"重复归档内的文件清单在预览后已变化：{path}")


def execute_repeated_archive(unit: Path, manifest: dict, protected_roots: tuple[Path, ...],
                             fingerprint: str, *, allow_fuse_compat: bool,
                             lease_fence: Callable[[], None]) -> None:
    """Reconcile a partial move through the frozen identities before any further write."""
    _check_archive_scope(unit, protected_roots)
    snapshot = manifest.get("snapshot")
    if (manifest.get("operation") != PROMOTE_ARCHIVE_CHILDREN or manifest.get("organizer_mode") != "semantic"
            or not _valid_snapshot(snapshot, unit.name) or manifest.get("input_fingerprint") != fingerprint
            or _fingerprint(snapshot) != fingerprint):
        raise ValueError("重复归档冻结记录与原预览不一致")
    children = snapshot["children"]
    with _directory(unit.parent) as archive_fd:
        if _identity(os.fstat(archive_fd)) != snapshot["archive"]:
            raise ValueError("重复归档目标父目录身份已变化")
        wrapper_id = _binding(archive_fd, unit.name)
        if wrapper_id is None:
            # Recovery after successful cleanup, before the batch result was committed.
            for name, child in children.items():
                current = _location(unit, archive_fd, None, name, child["identity"])
                _verify_content(current, child, protected_roots, lease_fence)
            os.fsync(archive_fd)
            return
        with _directory(unit) as wrapper_fd:
            def check_parents() -> None:
                if (_identity(os.fstat(wrapper_fd)) != wrapper_id or wrapper_id != snapshot["wrapper"]
                        or _binding(archive_fd, unit.name) != wrapper_id):
                    raise ValueError("重复归档包装目录身份已变化")
                with _directory(unit.parent) as live_fd:
                    if _identity(os.fstat(live_fd)) != snapshot["archive"]:
                        raise ValueError("重复归档目标父目录身份已变化")
                if set(os.listdir(wrapper_fd)) - children.keys():
                    raise ValueError("重复归档层出现新的子目录或文件")

            check_parents()
            for name, child in children.items():
                # Validate both the current source and its prospective target against current protection.
                if any((unit.parent / name).is_relative_to(root) or root.is_relative_to(unit.parent / name)
                       for root in protected_roots):
                    raise ValueError("重复归档目标目录受保护")
                current = _location(unit, archive_fd, wrapper_fd, name, child["identity"])
                _verify_content(current, child, protected_roots, lease_fence)
            for name, child in children.items():
                identity = child["identity"]
                lease_fence()
                check_parents()
                if _location(unit, archive_fd, wrapper_fd, name, identity).parent == unit:
                    def revalidate() -> None:
                        lease_fence()
                        check_parents()
                        if _location(unit, archive_fd, wrapper_fd, name, identity).parent != unit:
                            raise ValueError("重复归档源在重命名前已变化")
                        _verify_content(unit / name, child, protected_roots, lease_fence)

                    try:
                        _promote(wrapper_fd, archive_fd, name, allow_fuse_compat=allow_fuse_compat,
                                 revalidate=revalidate)
                    except FileExistsError as exc:
                        raise ValueError(f"重复归档上提目标已占用：{unit.parent / name}") from exc
                    if _location(unit, archive_fd, wrapper_fd, name, identity).parent != unit.parent:
                        raise ValueError("重复归档目标目录身份未通过校验")
                    _verify_content(unit.parent / name, child, protected_roots, lease_fence)
                    os.fsync(archive_fd)
                    os.fsync(wrapper_fd)
            lease_fence()
            check_parents()
            if os.listdir(wrapper_fd):
                raise ValueError("重复归档层仍含有未确认的文件")
            os.rmdir(unit.name, dir_fd=archive_fd)
            os.fsync(archive_fd)
