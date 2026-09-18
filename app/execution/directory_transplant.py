from __future__ import annotations

import errno
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


_STATE_FILE = "state.json"


class DirectoryTransplantConflict(OSError):
    pass


@dataclass(frozen=True)
class DirectoryTransplantResult:
    metadata_warnings: tuple[str, ...] = ()


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value) or "plan"


def _tx_dir(quarantine_root: Path | str, plan_id: str, sequence: int) -> Path:
    return (
        Path(quarantine_root)
        / ".utility-move-tx"
        / _safe_component(str(plan_id))
        / f"item-{int(sequence)}"
    )


def _state_path(quarantine_root: Path | str, plan_id: str, sequence: int) -> Path:
    return _tx_dir(quarantine_root, plan_id, sequence) / _STATE_FILE


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _load_state(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise OSError(errno.EIO, "Invalid directory transplant state")
    return data


def _identity(st: os.stat_result) -> tuple[int, int]:
    return int(st.st_dev), int(st.st_ino)


def _open_dir(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _stat_at(fd: int, name: str) -> os.stat_result:
    return os.stat(name, dir_fd=fd, follow_symlinks=False)


def _entry_exists_at(fd: int, name: str) -> bool:
    try:
        _stat_at(fd, name)
    except FileNotFoundError:
        return False
    return True


def _copy_directory_metadata(
    src_fd: int,
    dst_fd: int,
    *,
    rel_path: str,
    warnings: list[str],
) -> None:
    """Best-effort metadata preservation.

    Content publication/unlink is authoritative.  FUSE/zfuse may legitimately
    reject ownership, mode, xattr or timestamp mutation after data movement.
    Those failures must never turn an otherwise converged MOVE into a partial
    namespace transaction.
    """
    src_st = os.fstat(src_fd)
    dst_st = os.fstat(dst_fd)
    label = rel_path or "."

    if (
        hasattr(os, "fchown")
        and (
            int(dst_st.st_uid) != int(src_st.st_uid)
            or int(dst_st.st_gid) != int(src_st.st_gid)
        )
    ):
        try:
            os.fchown(dst_fd, int(src_st.st_uid), int(src_st.st_gid))
        except OSError as exc:
            warnings.append(f"metadata chown warning at {label}: {exc}")

    try:
        os.fchmod(dst_fd, stat.S_IMODE(src_st.st_mode))
    except OSError as exc:
        warnings.append(f"metadata chmod warning at {label}: {exc}")

    if all(hasattr(os, name) for name in ("listxattr", "getxattr", "setxattr")):
        try:
            xattrs = os.listxattr(src_fd)
        except OSError as exc:
            warnings.append(f"metadata xattr-list warning at {label}: {exc}")
            xattrs = []
        for name in xattrs:
            try:
                value = os.getxattr(src_fd, name)
                os.setxattr(dst_fd, name, value)
            except OSError as exc:
                warnings.append(f"metadata xattr warning at {label} ({name!r}): {exc}")

    try:
        os.utime(
            dst_fd,
            ns=(
                getattr(src_st, "st_atime_ns", int(src_st.st_atime * 1e9)),
                getattr(src_st, "st_mtime_ns", int(src_st.st_mtime * 1e9)),
            ),
        )
    except OSError as exc:
        warnings.append(f"metadata utime warning at {label}: {exc}")


def _preflight_tree_fd(dir_fd: int, root_device: int) -> None:
    with os.scandir(dir_fd) as entries:
        for entry in entries:
            st = entry.stat(follow_symlinks=False)
            if int(st.st_dev) != int(root_device):
                raise OSError(
                    errno.EXDEV,
                    f"Cross-filesystem nested entry is unsupported: {entry.name}",
                )
            mode = st.st_mode
            if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                continue
            if not stat.S_ISDIR(mode):
                raise OSError(
                    errno.EOPNOTSUPP,
                    f"Special filesystem entry is unsupported: {entry.name}",
                )
            child_fd = os.open(
                entry.name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=dir_fd,
            )
            try:
                _preflight_tree_fd(child_fd, root_device)
            finally:
                os.close(child_fd)


def directory_transplant_preflight(source: Path | str) -> bool:
    src = Path(source)
    try:
        src_st = os.lstat(src)
        if not stat.S_ISDIR(src_st.st_mode) or stat.S_ISLNK(src_st.st_mode):
            return False
        fd = _open_dir(src)
        try:
            _preflight_tree_fd(fd, int(src_st.st_dev))
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    _atomic_write_json(state_path, state)


def _record_created_dir(
    state_path: Path,
    state: dict[str, Any],
    rel_path: str,
    st: os.stat_result,
) -> None:
    created = state.setdefault("created_dirs", {})
    created[rel_path] = [int(st.st_dev), int(st.st_ino)]
    _save_state(state_path, state)


def _require_owned_dir(
    state: dict[str, Any],
    rel_path: str,
    st: os.stat_result,
) -> None:
    expected = (state.get("created_dirs") or {}).get(rel_path)
    if not isinstance(expected, list) or len(expected) != 2:
        raise DirectoryTransplantConflict(
            errno.EEXIST,
            f"Target directory was not created by this MOVE transaction: {rel_path}",
        )
    if [int(st.st_dev), int(st.st_ino)] != [int(expected[0]), int(expected[1])]:
        raise DirectoryTransplantConflict(
            errno.EEXIST,
            f"Target directory identity changed during MOVE transaction: {rel_path}",
        )


def _move_regular_file(src_fd: int, dst_fd: int, name: str, *, rel_path: str) -> None:
    src_st = _stat_at(src_fd, name)
    if _entry_exists_at(dst_fd, name):
        dst_st = _stat_at(dst_fd, name)
        if _identity(src_st) != _identity(dst_st) or not stat.S_ISREG(dst_st.st_mode):
            raise DirectoryTransplantConflict(
                errno.EEXIST,
                f"Foreign target entry appeared during directory MOVE: {name}",
            )
        try:
        os.unlink(name, dir_fd=src_fd)
    except OSError as exc:
        raise OSError(
            exc.errno or errno.EIO,
            f"TRANSPLANT_SYMLINK_SOURCE_UNLINK_FAILED at {rel_path}: {exc}",
        ) from exc
        return

    try:
        os.link(
            name,
            name,
            src_dir_fd=src_fd,
            dst_dir_fd=dst_fd,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise OSError(
            exc.errno or errno.EIO,
            f"TRANSPLANT_LINK_FAILED at {rel_path}: {exc}",
        ) from exc
    try:
        os.unlink(name, dir_fd=src_fd)
    except OSError:
        try:
            os.unlink(name, dir_fd=dst_fd)
        except OSError as rollback_error:
            raise OSError(
                errno.EIO,
                f"Directory MOVE file rollback failed for {name}: {rollback_error}",
            )
        raise OSError(
            unlink_error.errno or errno.EIO,
            f"TRANSPLANT_SOURCE_UNLINK_FAILED at {rel_path}: {unlink_error}",
        ) from unlink_error


def _move_symlink(
    src_fd: int,
    dst_fd: int,
    name: str,
    *,
    rel_path: str,
    state_path: Path,
    state: dict[str, Any],
    metadata_warnings: list[str],
) -> None:
    link_text = os.readlink(name, dir_fd=src_fd)
    published = state.setdefault("published_symlinks", {})

    if _entry_exists_at(dst_fd, name):
        if published.get(rel_path) != link_text:
            raise DirectoryTransplantConflict(
                errno.EEXIST,
                f"Foreign target symlink appeared during directory MOVE: {rel_path}",
            )
        dst_st = _stat_at(dst_fd, name)
        if not stat.S_ISLNK(dst_st.st_mode) or os.readlink(name, dir_fd=dst_fd) != link_text:
            raise DirectoryTransplantConflict(
                errno.EEXIST,
                f"Target symlink changed during directory MOVE: {rel_path}",
            )
        os.unlink(name, dir_fd=src_fd)
        return

    try:
        os.symlink(link_text, name, dir_fd=dst_fd)
    except OSError as exc:
        raise OSError(
            exc.errno or errno.EIO,
            f"TRANSPLANT_SYMLINK_PUBLISH_FAILED at {rel_path}: {exc}",
        ) from exc
    published[rel_path] = link_text
    _save_state(state_path, state)
    os.unlink(name, dir_fd=src_fd)


def _move_directory_contents(
    src_fd: int,
    dst_fd: int,
    *,
    rel_prefix: str,
    state_path: Path,
    state: dict[str, Any],
) -> None:
    with os.scandir(src_fd) as entries:
        names = sorted(entry.name for entry in entries)

    for name in names:
        try:
            src_st = _stat_at(src_fd, name)
        except FileNotFoundError:
            continue

        rel_path = f"{rel_prefix}/{name}" if rel_prefix else name
        mode = src_st.st_mode

        if stat.S_ISREG(mode):
            _move_regular_file(src_fd, dst_fd, name, rel_path=rel_path)
            continue

        if stat.S_ISLNK(mode):
            _move_symlink(
                src_fd,
                dst_fd,
                name,
                rel_path=rel_path,
                state_path=state_path,
                state=state,
            )
            continue

        if not stat.S_ISDIR(mode):
            raise OSError(
                errno.EOPNOTSUPP,
                f"Special filesystem entry is unsupported during MOVE: {rel_path}",
            )

        if _entry_exists_at(dst_fd, name):
            dst_st = _stat_at(dst_fd, name)
            if not stat.S_ISDIR(dst_st.st_mode) or stat.S_ISLNK(dst_st.st_mode):
                raise DirectoryTransplantConflict(
                    errno.EEXIST,
                    f"Foreign target entry appeared during directory MOVE: {rel_path}",
                )
            _require_owned_dir(state, rel_path, dst_st)
        else:
            try:
                os.mkdir(name, mode=0o700, dir_fd=dst_fd)
            except OSError as exc:
                raise OSError(
                    exc.errno or errno.EIO,
                    f"TRANSPLANT_MKDIR_FAILED at {rel_path}: {exc}",
                ) from exc
            dst_st = _stat_at(dst_fd, name)
            _record_created_dir(state_path, state, rel_path, dst_st)

        src_child_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=src_fd,
        )
        dst_child_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=dst_fd,
        )
        try:
            current_src_st = os.fstat(src_child_fd)
            if _identity(current_src_st) != _identity(src_st):
                raise OSError(
                    getattr(errno, "ESTALE", errno.EIO),
                    f"Source directory identity changed during MOVE: {rel_path}",
                )
            _move_directory_contents(
                src_child_fd,
                dst_child_fd,
                rel_prefix=rel_path,
                state_path=state_path,
                state=state,
                metadata_warnings=metadata_warnings,
            )
            _copy_directory_metadata(
                src_child_fd,
                dst_child_fd,
                rel_path=rel_path,
                warnings=metadata_warnings,
            )
        finally:
            os.close(dst_child_fd)
            os.close(src_child_fd)

        try:
            os.rmdir(name, dir_fd=src_fd)
        except OSError as exc:
            raise OSError(
                exc.errno or errno.EIO,
                f"TRANSPLANT_SOURCE_RMDIR_FAILED at {rel_path}: {exc}",
            ) from exc


def _cleanup_owned_empty_target_dirs(dst: Path, state: dict[str, Any]) -> None:
    """Best-effort cleanup for NFC-created target directories that remain empty."""
    created = state.get("created_dirs") or {}
    if not isinstance(created, dict):
        return
    rel_paths = sorted(
        (str(rel) for rel in created.keys()),
        key=lambda rel: len(Path(rel).parts) if rel else 0,
        reverse=True,
    )
    for rel_path in rel_paths:
        path = dst / rel_path if rel_path else dst
        expected = created.get(rel_path)
        if not isinstance(expected, list) or len(expected) != 2:
            continue
        try:
            st = os.lstat(path)
            if (
                not stat.S_ISDIR(st.st_mode)
                or stat.S_ISLNK(st.st_mode)
                or [int(st.st_dev), int(st.st_ino)] != [int(expected[0]), int(expected[1])]
            ):
                continue
            if os.listdir(path):
                continue
            os.rmdir(path)
        except OSError:
            continue


def move_directory_tree_noreplace(
    source: Path | str,
    target: Path | str,
    *,
    quarantine_root: Path | str,
    plan_id: str,
    sequence: int,
    expected_device: int = 0,
    expected_inode: int = 0,
) -> DirectoryTransplantResult:
    src = Path(source)
    dst = Path(target)
    state_path = _state_path(quarantine_root, plan_id, sequence)
    state = _load_state(state_path)

    try:
        src_st = os.lstat(src)
    except FileNotFoundError:
        if directory_transplant_reconciles_completed(
            quarantine_root,
            plan_id,
            sequence,
            source=src,
            target=dst,
        ):
            existing = _load_state(state_path) or {}
            return DirectoryTransplantResult(
                metadata_warnings=tuple(existing.get("metadata_warnings") or ())
            )
        raise

    if not stat.S_ISDIR(src_st.st_mode) or stat.S_ISLNK(src_st.st_mode):
        raise OSError(errno.EOPNOTSUPP, "Directory transplant requires a real directory")

    if expected_device and int(src_st.st_dev) != int(expected_device):
        raise OSError(getattr(errno, "ESTALE", errno.EIO), "Source directory device changed")
    if expected_inode and int(src_st.st_ino) != int(expected_inode):
        raise OSError(getattr(errno, "ESTALE", errno.EIO), "Source directory inode changed")

    src_fd = _open_dir(src)
    try:
        _preflight_tree_fd(src_fd, int(src_st.st_dev))
    finally:
        os.close(src_fd)

    token = hashlib.sha256(
        f"{plan_id}:{sequence}:{src}:{dst}:{src_st.st_dev}:{src_st.st_ino}".encode("utf-8")
    ).hexdigest()

    if state is None:
        state = {
            "version": 1,
            "token": token,
            "phase": "initializing",
            "source": str(src),
            "target": str(dst),
            "source_device": int(src_st.st_dev),
            "source_inode": int(src_st.st_ino),
            "created_dirs": {},
            "published_symlinks": {},
            "metadata_warnings": [],
        }
        _save_state(state_path, state)
    else:
        if (
            state.get("token") != token
            or state.get("source") != str(src)
            or state.get("target") != str(dst)
            or int(state.get("source_device", -1)) != int(src_st.st_dev)
            or int(state.get("source_inode", -1)) != int(src_st.st_ino)
        ):
            raise DirectoryTransplantConflict(
                errno.EEXIST,
                "Existing directory MOVE transaction does not match this frozen item",
            )

    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() or dst.is_symlink():
        dst_st = os.lstat(dst)
        expected_root = (state.get("created_dirs") or {}).get("")
        if not isinstance(expected_root, list) or [int(dst_st.st_dev), int(dst_st.st_ino)] != [
            int(expected_root[0]),
            int(expected_root[1]),
        ]:
            raise FileExistsError(errno.EEXIST, f"Target path already exists: {dst}", str(dst))
        if not stat.S_ISDIR(dst_st.st_mode) or stat.S_ISLNK(dst_st.st_mode):
            raise DirectoryTransplantConflict(errno.EEXIST, "Target root is no longer a directory")
    else:
        existing_root = (state.get("created_dirs") or {}).get("")
        if existing_root is not None:
            raise DirectoryTransplantConflict(
                errno.ENOENT,
                "Owned target root disappeared during directory MOVE transaction",
            )
        os.mkdir(dst, mode=0o700)
        dst_st = os.lstat(dst)
        _record_created_dir(state_path, state, "", dst_st)

    state["phase"] = "migrating"
    _save_state(state_path, state)

    metadata_warnings = list(state.get("metadata_warnings") or [])
    src_fd = _open_dir(src)
    dst_fd = _open_dir(dst)
    try:
        if _identity(os.fstat(src_fd)) != _identity(src_st):
            raise OSError(getattr(errno, "ESTALE", errno.EIO), "Source root identity changed")
        root_expected = (state.get("created_dirs") or {}).get("")
        dst_st = os.fstat(dst_fd)
        if not isinstance(root_expected, list) or [int(dst_st.st_dev), int(dst_st.st_ino)] != [
            int(root_expected[0]),
            int(root_expected[1]),
        ]:
            raise DirectoryTransplantConflict(errno.EEXIST, "Target root identity changed")

        _move_directory_contents(
            src_fd,
            dst_fd,
            rel_prefix="",
            state_path=state_path,
            state=state,
            metadata_warnings=metadata_warnings,
        )
        _copy_directory_metadata(
            src_fd,
            dst_fd,
            rel_path="",
            warnings=metadata_warnings,
        )
    except Exception:
        _cleanup_owned_empty_target_dirs(dst, state)
        raise
    finally:
        os.close(dst_fd)
        os.close(src_fd)

    try:
        os.rmdir(src)
    except OSError as exc:
        raise OSError(
            exc.errno or errno.EIO,
            f"TRANSPLANT_SOURCE_RMDIR_FAILED at .: {exc}",
        ) from exc
    state["phase"] = "transplanted"
    state["metadata_warnings"] = metadata_warnings
    _save_state(state_path, state)
    return DirectoryTransplantResult(metadata_warnings=tuple(metadata_warnings))


def directory_transplant_reconciles_completed(
    quarantine_root: Path | str,
    plan_id: str | int,
    sequence: int,
    *,
    source: Path | str,
    target: Path | str,
) -> bool:
    src = Path(source)
    dst = Path(target)
    state = _load_state(_state_path(quarantine_root, str(plan_id), sequence))
    if not state:
        return False
    if state.get("source") != str(src) or state.get("target") != str(dst):
        return False
    if src.exists() or src.is_symlink():
        return False
    try:
        dst_st = os.lstat(dst)
    except OSError:
        return False
    root_expected = (state.get("created_dirs") or {}).get("")
    if not isinstance(root_expected, list) or len(root_expected) != 2:
        return False
    return (
        stat.S_ISDIR(dst_st.st_mode)
        and not stat.S_ISLNK(dst_st.st_mode)
        and [int(dst_st.st_dev), int(dst_st.st_ino)]
        == [int(root_expected[0]), int(root_expected[1])]
        and state.get("phase") in {"migrating", "transplanted"}
    )


def cleanup_directory_transplant_state(
    quarantine_root: Path | str,
    plan_id: str | int,
    sequence: int,
) -> None:
    tx_dir = _tx_dir(quarantine_root, str(plan_id), sequence)
    state_file = tx_dir / _STATE_FILE
    try:
        state_file.unlink()
    except FileNotFoundError:
        pass
    try:
        tx_dir.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        return

    parent = tx_dir.parent
    try:
        parent.rmdir()
    except OSError:
        pass
