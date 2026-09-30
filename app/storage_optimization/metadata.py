from __future__ import annotations

import base64
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Any


class StorageMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class FrozenFileMetadata:
    mode: int
    uid: int
    gid: int
    size: int
    link_count: int
    atime_ns: int
    mtime_ns: int
    xattrs: tuple[tuple[str, bytes], ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "size": self.size,
            "link_count": self.link_count,
            "atime_ns": self.atime_ns,
            "mtime_ns": self.mtime_ns,
            "xattrs": [
                {
                    "name": name,
                    "value_base64": base64.b64encode(value).decode("ascii"),
                }
                for name, value in self.xattrs
            ],
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> "FrozenFileMetadata":
        try:
            xattrs_raw = raw.get("xattrs", [])
            if not isinstance(xattrs_raw, list):
                raise TypeError("xattrs must be a list")
            xattrs: list[tuple[str, bytes]] = []
            for item in xattrs_raw:
                if not isinstance(item, dict):
                    raise TypeError("xattr entry must be an object")
                name = item["name"]
                encoded = item["value_base64"]
                if not isinstance(name, str) or not isinstance(encoded, str):
                    raise TypeError("xattr name/value must be strings")
                xattrs.append((name, base64.b64decode(encoded, validate=True)))
            return cls(
                mode=int(raw["mode"]),
                uid=int(raw["uid"]),
                gid=int(raw["gid"]),
                size=int(raw["size"]),
                link_count=int(raw["link_count"]),
                atime_ns=int(raw["atime_ns"]),
                mtime_ns=int(raw["mtime_ns"]),
                xattrs=tuple(sorted(xattrs)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageMetadataError(f"invalid frozen storage metadata: {exc}") from exc


def _read_xattrs(path: Path) -> tuple[tuple[str, bytes], ...]:
    if not hasattr(os, "listxattr") or not hasattr(os, "getxattr"):
        raise StorageMetadataError("extended attribute APIs are unavailable")
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except OSError as exc:
        raise StorageMetadataError(f"cannot enumerate extended attributes: {exc}") from exc

    values: list[tuple[str, bytes]] = []
    for name in sorted(names):
        try:
            value = os.getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            raise StorageMetadataError(
                f"cannot read extended attribute {name!r}: {exc}"
            ) from exc
        values.append((str(name), bytes(value)))
    return tuple(values)


def capture_file_metadata(path: Path | str) -> FrozenFileMetadata:
    source = Path(path)
    try:
        st = os.lstat(source)
    except OSError as exc:
        raise StorageMetadataError(f"cannot stat file metadata: {exc}") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise StorageMetadataError("storage optimization metadata requires a regular non-symlink file")
    return FrozenFileMetadata(
        mode=stat.S_IMODE(st.st_mode),
        uid=int(st.st_uid),
        gid=int(st.st_gid),
        size=int(st.st_size),
        link_count=int(st.st_nlink),
        atime_ns=int(getattr(st, "st_atime_ns", int(st.st_atime * 1e9))),
        mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
        xattrs=_read_xattrs(source),
    )


def hardlink_metadata_compatibility(
    keep_path: Path | str,
    source_path: Path | str,
) -> tuple[bool, str, FrozenFileMetadata, FrozenFileMetadata]:
    keep = capture_file_metadata(keep_path)
    source = capture_file_metadata(source_path)

    checks = (
        ("mode", keep.mode, source.mode),
        ("uid", keep.uid, source.uid),
        ("gid", keep.gid, source.gid),
        ("size", keep.size, source.size),
        ("xattrs", keep.xattrs, source.xattrs),
    )
    for field, keep_value, source_value in checks:
        if keep_value != source_value:
            return False, f"HARDLINK_METADATA_MISMATCH:{field}", keep, source
    return True, "HARDLINK_METADATA_COMPATIBLE", keep, source


def ownership_can_be_preserved(metadata: FrozenFileMetadata) -> bool:
    """Conservative preflight for creating a replacement inode.

    Root can preserve arbitrary uid/gid. A non-root process may preserve only
    its own uid and a group it currently belongs to.
    """
    if not hasattr(os, "geteuid"):
        return False
    euid = int(os.geteuid())
    if euid == 0:
        return True
    if metadata.uid != euid:
        return False
    groups = {int(os.getegid())}
    try:
        groups.update(int(group) for group in os.getgroups())
    except OSError:
        return False
    return metadata.gid in groups


def apply_frozen_metadata_fd(fd: int, metadata: FrozenFileMetadata) -> None:
    """Apply SOURCE-facing metadata to a newly-created reflink inode."""
    try:
        current = os.fstat(fd)
        if int(current.st_uid) != metadata.uid or int(current.st_gid) != metadata.gid:
            os.fchown(fd, metadata.uid, metadata.gid)
        os.fchmod(fd, metadata.mode)

        if not hasattr(os, "setxattr"):
            if metadata.xattrs:
                raise StorageMetadataError("extended attribute write API is unavailable")
        else:
            for name, value in metadata.xattrs:
                os.setxattr(fd, name, value)

        os.utime(fd, ns=(metadata.atime_ns, metadata.mtime_ns))
    except (OSError, TypeError, ValueError) as exc:
        raise StorageMetadataError(f"cannot preserve reflink source metadata: {exc}") from exc


def capture_file_metadata_fd(fd: int) -> FrozenFileMetadata:
    try:
        st = os.fstat(fd)
    except OSError as exc:
        raise StorageMetadataError(f"cannot stat file descriptor metadata: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise StorageMetadataError("storage optimization metadata requires a regular file descriptor")

    if not hasattr(os, "listxattr") or not hasattr(os, "getxattr"):
        raise StorageMetadataError("extended attribute APIs are unavailable")
    try:
        names = os.listxattr(fd)
        xattrs = tuple(
            (str(name), bytes(os.getxattr(fd, name)))
            for name in sorted(names)
        )
    except OSError as exc:
        raise StorageMetadataError(f"cannot read descriptor extended attributes: {exc}") from exc

    return FrozenFileMetadata(
        mode=stat.S_IMODE(st.st_mode),
        uid=int(st.st_uid),
        gid=int(st.st_gid),
        size=int(st.st_size),
        link_count=int(st.st_nlink),
        atime_ns=int(getattr(st, "st_atime_ns", int(st.st_atime * 1e9))),
        mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
        xattrs=xattrs,
    )


def replacement_metadata_matches(
    actual: FrozenFileMetadata,
    expected: FrozenFileMetadata,
) -> bool:
    """Compare metadata that must survive replacement.

    atime is intentionally excluded because content verification itself may
    advance it on strict-atime filesystems before this check.
    """
    return (
        actual.mode == expected.mode
        and actual.uid == expected.uid
        and actual.gid == expected.gid
        and actual.size == expected.size
        and actual.link_count == expected.link_count
        and actual.mtime_ns == expected.mtime_ns
        and actual.xattrs == expected.xattrs
    )
