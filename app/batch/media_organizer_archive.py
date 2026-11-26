"""Discover and safely remove redundant archive, work and photo wrappers."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from unicodedata import normalize

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_link_intent import LinkIntent
from app.batch.media_organizer_tree_lift import check_tree_lift, execute_tree_lift, validate_lift_layout
from app.batch.media_package_naming import MEDIA_BUCKET_PATTERN, numbered_name
from app.batch.media_package_organizer import MAX_DEPTH, MAX_FILES_PER_GROUP, MAX_PACKAGE_DIRECTORIES, MAX_PACKAGE_FILES, _classify
from app.fs_ops import probe_directory_rename_noreplace_compat_at, rename_noreplace_at

PROMOTE_ARCHIVE_CHILDREN = "promote_repeated_archive_children"
_ARCHIVE_LABELS = {"old", "archive", "backup", "bak", "旧版", "备份"}
_PHOTO_SHELLS = {"p", "photo", "photos", "images", "图", "图片", "照片"}
_NUMBERED_VOLUME = re.compile(r"[0-9]{1,3}")
_PHOTO_BUCKET_ALIAS = re.compile(r"p(?:_?[1-9][0-9]*)?")
_MAX_CHILDREN = 200


def is_repeated_archive(unit: Path) -> bool:
    """Only exact-name, explicitly named archive shells qualify."""
    return unit.name == unit.parent.name and unit.name.casefold() in _ARCHIVE_LABELS


def _lift_mode(unit: Path) -> str | None:
    if is_repeated_archive(unit):
        return "archive"
    if unit.name != unit.parent.name and unit.name.casefold() not in _PHOTO_SHELLS:
        return None
    from app.batch.media_organizer_planner import (
        _append_calendar_boundary, _calendar_author_layer, _declared_media_count_label,
    )

    if unit.name == unit.parent.name:
        if _declared_media_count_label(unit) and not _append_calendar_boundary(unit.name):
            return "work_volumes"
    elif (_calendar_author_layer(unit.parent)
          or _declared_media_count_label(unit.parent) is not None):
        return "photo_buckets"
    return None


def is_structural_media_wrapper(unit: Path) -> bool:
    """Recognize candidate media shells before checking their exact contents."""
    return _lift_mode(unit) in {"work_volumes", "photo_buckets"}


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


def _check_archive_scope(unit: Path, protected_roots: tuple[Path, ...]) -> str:
    mode = _lift_mode(unit)
    if (mode is None or not unit.is_absolute() or ".." in unit.parts
            or any(name.casefold().startswith(".nfc-") for name in unit.parts)
            or any(unit.parent.is_relative_to(root) or root.is_relative_to(unit)
                   for root in protected_roots)):
        raise ValueError("重复归档目录超出允许范围")
    return mode


def _file_identity(info: os.stat_result) -> list[int]:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("上提文件已变化")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _file_binding(parent_fd: int, name: str) -> list[int] | None:
    try:
        return _file_identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _valid_picture_bucket(path: Path, device: int, protected_roots: tuple[Path, ...]) -> bool:
    from app.batch.media_organizer_planner import _numbered_media_leaf, _regular_media_entries, _scoped_bucket_kind

    if _scoped_bucket_kind(path, device, protected_roots) != "P":
        return False
    files = _regular_media_entries(path, device)
    return len(files) <= MAX_FILES_PER_GROUP and _numbered_media_leaf(path, files, "P", device, protected_roots)


def _check_destination(unit: Path, mode: str, parent_fd: int, approved: set[str]) -> None:
    if mode == "archive":
        return
    others = set(os.listdir(parent_fd)) - approved - {unit.name}
    if mode == "work_volumes" and others:
        raise ValueError("外层同名目录已含有其他内容")
    if mode != "photo_buckets":
        return
    from app.batch.media_organizer_planner import _labelled_bucket_kind

    for name in others:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (stat.S_ISREG(info.st_mode) and _classify(name) == "P"
                or not stat.S_ISREG(info.st_mode) and (
                    _labelled_bucket_kind(name) == "P" or _fold(name) in _PHOTO_SHELLS
                    or _PHOTO_BUCKET_ALIAS.fullmatch(_fold(name)) or _fold(name) == "图包"
                )):
            raise ValueError("目标目录已有图片或图片分类桶")


def _valid_media_children(mode: str, children: dict, files: dict) -> bool:
    if mode == "archive":
        return not files
    if mode == "photo_buckets":
        indexes = []
        for name in children:
            match = MEDIA_BUCKET_PATTERN.fullmatch(name)
            if not match or match["kind"].upper() != "P":
                return False
            indexes.append(match["index"] or "0")
        return not files and set(indexes) == {str(index) for index in range(len(indexes))}
    ordinals = {name.lstrip("0") for name in children}
    return (len(children) >= 2 and len(ordinals) == len(children) and "" not in ordinals
            and all(_NUMBERED_VOLUME.fullmatch(name) for name in children)
            and len(files) <= 1
            and all(_classify(name) == "V" and name == numbered_name(1, name) and identity[2] > 0
                    for name, identity in files.items()))


def _tree_content_digest(unit: Path, identity: list[int], protected_roots: tuple[Path, ...],
                         check_cancelled: Callable[[], None] | None = None, *,
                         layout: dict | None = None) -> str:
    """Bind the file identity multiset while allowing media renames inside the same child."""
    if any(unit.is_relative_to(root) or root.is_relative_to(unit) for root in protected_roots):
        raise ValueError("重复归档包含受保护目录")
    pending = [(unit, 0, layout)]
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
        path, depth, tree = pending.pop()
        directories += 1
        if depth > MAX_DEPTH or directories > MAX_PACKAGE_DIRECTORIES:
            raise ValueError("重复归档超过目录范围限制")
        checkpoint()
        with _directory(path) as fd:
            before = os.fstat(fd)
            current = _identity(before)
            if current[0] != identity[0] or (depth == 0 and current != identity):
                raise ValueError("重复归档目录身份或磁盘已变化")
            if tree is not None:
                tree.update(identity=current, directories={}, files={})
            with os.scandir(fd) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    if info.st_dev != identity[0] or entry.name.casefold().startswith(".nfc-"):
                        raise ValueError("重复归档包含跨设备目录或待恢复文件")
                    if stat.S_ISDIR(info.st_mode):
                        child = tree["directories"].setdefault(entry.name, {}) if tree is not None else None
                        pending.append((path / entry.name, depth + 1, child))
                        if directories + len(pending) > MAX_PACKAGE_DIRECTORIES:
                            raise ValueError("重复归档超过目录范围限制")
                    elif stat.S_ISREG(info.st_mode):
                        # Keep duplicate identities: they account for distinct hardlinks
                        # and must not disappear during a previous media operation.
                        file_identity = _file_identity(info)
                        files.append(file_identity)
                        if tree is not None:
                            tree["files"][entry.name] = file_identity
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
              check_cancelled: Callable[[], None] | None = None, *,
              lift_layouts: dict | None = None) -> dict:
    mode = _check_archive_scope(unit, protected_roots)
    with _directory(unit.parent) as archive_fd, _directory(unit) as wrapper_fd:
        archive = _identity(os.fstat(archive_fd))
        wrapper = _identity(os.fstat(wrapper_fd))
        if wrapper[0] != archive[0] or wrapper != _binding(archive_fd, unit.name):
            raise ValueError("重复归档目录身份或磁盘已变化")
        names = sorted(os.listdir(wrapper_fd), key=lambda name: (_fold(name), name))
        if not 0 < len(names) <= _MAX_CHILDREN:
            raise ValueError("重复归档层不包含可上提的子目录")
        _check_destination(unit, mode, archive_fd, set())
        occupied = {_fold(name) for name in os.listdir(archive_fd)}
        children, files = {}, {}
        for name in names:
            key = _fold(name)
            if key in occupied or key.startswith(".nfc-"):
                raise ValueError(f"重复归档上提目标已占用或保留：{unit.parent / name}")
            occupied.add(key)
            if any((unit.parent / name).is_relative_to(root) or root.is_relative_to(unit.parent / name)
                   for root in protected_roots):
                raise ValueError("重复归档目标目录受保护")
            info = os.stat(name, dir_fd=wrapper_fd, follow_symlinks=False)
            if info.st_dev != archive[0]:
                raise ValueError("上提目录包含跨设备内容")
            child = unit / name
            if mode == "work_volumes" and stat.S_ISREG(info.st_mode):
                files[name] = _file_identity(info)
                continue
            identity = _identity(info)
            if mode == "photo_buckets" and not _valid_picture_bucket(child, archive[0], protected_roots):
                raise ValueError("照片桶的数量、大小或编号尚未通过验证")
            if mode == "work_volumes":
                from app.batch.media_organizer_planner import _media_leaf_kinds

                kinds = _media_leaf_kinds(child, archive[0], protected_roots, allow_partial_bucketing=False)
                if not kinds or kinds - {"P", "V"}:
                    raise ValueError("同名目录内的分册并非独立媒体")
            layout = lift_layouts.setdefault(name, {}) if lift_layouts is not None else None
            content = _tree_content_digest(child, identity, protected_roots, check_cancelled, layout=layout)
            children[name] = {"identity": identity, "content": content}
        if not _valid_media_children(mode, children, files):
            raise ValueError("上提目录包含未确认的分类或文件")
        return {"archive": archive, "wrapper": wrapper, "children": children,
                **({"files": files} if files else {})}


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
        "kind": "V", "bytes": identity[2],
    } for name, identity in snapshot.get("files", {}).items()]
    moves.extend({
        "source": str(unit / name), "target": str(unit.parent / name), "target_name": name,
        "kind": "Directory", "bytes": 0,
    } for name in snapshot["children"])
    reason = {"archive": "重复归档层的子目录整体上提", "work_volumes": "同名标题中的分册和直属视频整体上提",
              "photo_buckets": "已整理的图片桶整体上提"}[_lift_mode(unit)]
    return {
        "unit": str(unit), "organizer_mode": "semantic", "operation": PROMOTE_ARCHIVE_CHILDREN,
        "status": "ready", "reason": reason, "read_only": True,
        "totals": {"P": 0, "V": 0, "Other": 0}, "total_files": 0, "total_bytes": 0,
        "groups": [], "conflicts": [], "total_proposals": len(moves), "needed_moves": len(moves),
        "renamed_count": 0, "actual_moves": len(moves), "wrapper_cleanup": [str(unit)],
        "input_fingerprint": _fingerprint(snapshot), "_mapping_items": moves, "sample_moves": moves[:10],
    }


def freeze_repeated_archive(unit: Path, protected_roots: tuple[Path, ...], fingerprint: str,
                            job_id: int, *, check_cancelled: Callable[[], None],
                            allow_fuse_compat: bool = False) -> dict:
    """Bind the preview to the exact source and target directory identities."""
    from app.batch.media_package_execution import MANIFEST_VERSION

    layouts = {} if allow_fuse_compat and is_structural_media_wrapper(unit) else None
    snapshot = _snapshot(unit, protected_roots, check_cancelled, lift_layouts=layouts)
    if fingerprint != _fingerprint(snapshot):
        raise ValueError("重复归档目录在预览后已变化")
    return {
        "package": str(unit), "schema_version": MANIFEST_VERSION, "job_id": job_id,
        "organizer_mode": "semantic", "operation": PROMOTE_ARCHIVE_CHILDREN,
        "snapshot": snapshot, "input_fingerprint": fingerprint,
        **({"lift_layouts": layouts} if layouts is not None else {}),
    }


def _location(unit: Path, archive_fd: int, wrapper_fd: int | None, name: str, identity: list[int]) -> Path:
    """Accept either the frozen source or the identical already published directory."""
    origin = _binding(wrapper_fd, name) if wrapper_fd is not None else None
    destination = _binding(archive_fd, name)
    _check_target_name(unit, archive_fd, name)
    if origin == identity and destination is None:
        return unit / name
    if origin is None and destination == identity:
        return unit.parent / name
    raise ValueError(f"重复归档源或目标身份已变化：{name}")


def _check_target_name(unit: Path, parent_fd: int, name: str) -> None:
    if any(other != name and _fold(other) == _fold(name) for other in os.listdir(parent_fd)):
        raise ValueError(f"重复归档目标与同名目录冲突：{unit.parent / name}")


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
    if not isinstance(snapshot, dict) or snapshot.keys() not in (
        {"archive", "wrapper", "children"}, {"archive", "wrapper", "children", "files"},
    ):
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
    files = snapshot.get("files", {})
    if not isinstance(files, dict) or len(files) > 1:
        return False
    for name, identity in files.items():
        if (not isinstance(name, str) or not name or "\x00" in name or Path(name).name != name
                or _fold(name) in folded or _classify(name) != "V" or name != numbered_name(1, name)
                or not isinstance(identity, list) or len(identity) != 4
                or any(type(value) is not int for value in identity)
                or identity[0] != archive[0] or identity[1] <= 0 or identity[2] <= 0):
            return False
    return True


def _verify_content(path: Path, child: dict, mode: str, protected_roots: tuple[Path, ...],
                    lease_fence: Callable[[], None]) -> None:
    if _tree_content_digest(path, child["identity"], protected_roots, lease_fence) != child["content"]:
        raise ValueError(f"重复归档内的文件清单在预览后已变化：{path}")
    if mode == "photo_buckets" and not _valid_picture_bucket(path, child["identity"][0], protected_roots):
        raise ValueError(f"图片桶的编号或标签在预览后已变化：{path}")


def _lift_file_state(
    archive_fd: int, wrapper_fd: int, name: str, identity: list[int], link_intent: LinkIntent | None,
) -> str:
    """Recognize the frozen source, published target, or our durable two-link state."""
    origin, destination = _file_binding(wrapper_fd, name), _file_binding(archive_fd, name)
    if any(other != name and _fold(other) == _fold(name) for other in os.listdir(archive_fd)):
        raise ValueError(f"上提文件与同名路径冲突：{name}")
    if origin == identity and destination is None:
        return "source"
    if origin is None and destination == identity:
        return "target"
    if (origin == destination == identity and link_intent is not None
            and link_intent.matches(link_intent.binding(wrapper_fd, name, archive_fd, name, identity))):
        return "linked"
    raise ValueError(f"上提文件的源或目标已变化：{name}")


def execute_repeated_archive(unit: Path, manifest: dict, protected_roots: tuple[Path, ...],
                             fingerprint: str, *, allow_fuse_compat: bool,
                             lease_fence: Callable[[], None],
                             link_intent: LinkIntent | None = None) -> None:
    """Reconcile a partial move through the frozen identities before any further write."""
    mode = _check_archive_scope(unit, protected_roots)
    snapshot = manifest.get("snapshot")
    if (manifest.get("operation") != PROMOTE_ARCHIVE_CHILDREN or manifest.get("organizer_mode") != "semantic"
            or not _valid_snapshot(snapshot, unit.name) or manifest.get("input_fingerprint") != fingerprint
            or _fingerprint(snapshot) != fingerprint):
        raise ValueError("重复归档冻结记录与原预览不一致")
    children, files = snapshot["children"], snapshot.get("files", {})
    if not _valid_media_children(mode, children, files):
        raise ValueError("上提清单与目录结构不一致")
    layouts = manifest.get("lift_layouts")
    token = ""
    if layouts is not None:
        from app.batch.media_package_execution import _manifest_checksum

        if mode == "archive" or not isinstance(layouts, dict) or layouts.keys() != children.keys():
            raise ValueError("上提布局与冻结记录不一致")
        for name, layout in layouts.items():
            validate_lift_layout(layout, children[name])
        token = _manifest_checksum(manifest)
    layouts = layouts or {}
    approved = children.keys() | files.keys()
    with _directory(unit.parent) as archive_fd:
        if _identity(os.fstat(archive_fd)) != snapshot["archive"]:
            raise ValueError("重复归档目标父目录身份已变化")
        _check_destination(unit, mode, archive_fd, approved)
        wrapper_id = _binding(archive_fd, unit.name)

        def uses_tree_lift(name: str, identity: list[int]) -> bool:
            target = _binding(archive_fd, name) if name in layouts else None
            return target is not None and target != identity

        def verify_child(wrapper_fd: int | None, name: str, child: dict) -> None:
            if any((unit.parent / name).is_relative_to(root) or root.is_relative_to(unit.parent / name)
                   for root in protected_roots):
                raise ValueError("重复归档目标目录受保护")
            if uses_tree_lift(name, child["identity"]):
                if not allow_fuse_compat:
                    raise ValueError("FUSE 目录上提兼容模式已关闭")
                _check_target_name(unit, archive_fd, name)
                check_tree_lift(wrapper_fd, archive_fd, name, layouts[name], token, checkpoint=lease_fence)
            else:
                current = _location(unit, archive_fd, wrapper_fd, name, child["identity"])
                _verify_content(current, child, mode, protected_roots, lease_fence)

        if wrapper_id is None:
            # Recovery after successful cleanup, before the batch result was committed.
            for name, child in children.items():
                verify_child(None, name, child)
            for name, identity in files.items():
                if _file_binding(archive_fd, name) != identity:
                    raise ValueError(f"上提后的直属文件已变化：{name}")
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
                _check_destination(unit, mode, archive_fd, approved)
                if set(os.listdir(wrapper_fd)) - approved:
                    raise ValueError("重复归档层出现新的子目录或文件")

            check_parents()
            for name, child in children.items():
                verify_child(wrapper_fd, name, child)
            for name, identity in files.items():
                if any((unit.parent / name).is_relative_to(root) or root.is_relative_to(unit.parent / name)
                       for root in protected_roots):
                    raise ValueError("上提文件的目标路径受保护")
                _lift_file_state(archive_fd, wrapper_fd, name, identity, link_intent)
            for name, child in children.items():
                identity = child["identity"]
                lease_fence()
                check_parents()
                def tree_fence() -> None:
                    lease_fence()
                    check_parents()
                    _check_target_name(unit, archive_fd, name)

                if uses_tree_lift(name, identity):
                    execute_tree_lift(wrapper_fd, archive_fd, name, layouts[name], token,
                                      checkpoint=lease_fence, fence=tree_fence)
                    continue
                if _location(unit, archive_fd, wrapper_fd, name, identity).parent == unit:
                    def revalidate() -> None:
                        lease_fence()
                        check_parents()
                        if _location(unit, archive_fd, wrapper_fd, name, identity).parent != unit:
                            raise ValueError("重复归档源在重命名前已变化")
                        _verify_content(unit / name, child, mode, protected_roots, lease_fence)

                    try:
                        _promote(wrapper_fd, archive_fd, name, allow_fuse_compat=allow_fuse_compat,
                                 revalidate=revalidate)
                    except FileExistsError as exc:
                        raise ValueError(f"重复归档上提目标已占用：{unit.parent / name}") from exc
                    except OSError as exc:
                        if exc.errno != errno.EOPNOTSUPP or not allow_fuse_compat or name not in layouts:
                            raise
                        revalidate()
                        execute_tree_lift(wrapper_fd, archive_fd, name, layouts[name], token,
                                          checkpoint=lease_fence, fence=tree_fence)
                        continue
                    if _location(unit, archive_fd, wrapper_fd, name, identity).parent != unit.parent:
                        raise ValueError("重复归档目标目录身份未通过校验")
                    _verify_content(unit.parent / name, child, mode, protected_roots, lease_fence)
                    os.fsync(archive_fd)
                    os.fsync(wrapper_fd)
            for name, identity in files.items():
                from app.batch.media_package_execution import _move_file_at, _retire_link

                def file_fence() -> None:
                    lease_fence()
                    check_parents()
                    _lift_file_state(archive_fd, wrapper_fd, name, identity, link_intent)

                source, target = unit / name, unit.parent / name
                state = _lift_file_state(archive_fd, wrapper_fd, name, identity, link_intent)
                if state == "source":
                    _move_file_at(source, target, wrapper_fd, archive_fd, identity, file_fence, link_intent)
                elif state == "linked":
                    _retire_link(source, target, wrapper_fd, archive_fd, identity, file_fence, durable=True)
                os.fsync(archive_fd)
                os.fsync(wrapper_fd)
            lease_fence()
            check_parents()
            if os.listdir(wrapper_fd):
                raise ValueError("重复归档层仍含有未确认的文件")
            os.rmdir(unit.name, dir_fd=archive_fd)
            os.fsync(archive_fd)
