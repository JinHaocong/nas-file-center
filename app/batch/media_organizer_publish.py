"""Crash-resumable, no-replace publication of a fully staged media unit.

Each public binding is an exclusive hardlink to a frozen, still-retained
stage inode. Public group folders require a checksum-bound owner witness.
The stage and publication witnesses are deliberately retained; final
retirement/cleanup is a separate, independently reviewed operation.

The gated Worker uses only defer_directory_cleanup=True for new frozen jobs.
Legacy auto-wrapper retirement is historical library behavior for isolated
synthetic tests and is refused for every cleanup_policy=deferred manifest.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Callable

from app.batch.file_rename import _open_directory_nofollow
from app.config_sharing import shared_config_gid
from app.batch.media_organizer_manifest import (
    load_frozen_preview_manifest, FrozenPreviewError, _checksum,
)
from app.batch.media_organizer_stage import (
    _authority, _check_identity, _read_marker, _write_marker,
    _assert_private_stage_fd, _inspect_stage, stage_frozen_sources, StagingConflict,
)
from app.batch.media_organizer_path_roles import classify_path_roles, uses_path_roles
from app.batch.media_organizer_planner import _check_scope
from app.fs_ops import rename_noreplace_at
from app.batch.media_organizer_authority import (
    assert_operation_authorized, is_maintenance_session, maintenance_session_settings, publication_fence,
)
from app.nas_compat_worker import is_nas_compat_root_worker
from app.batch.media_organizer_fd_link import link_pinned_inode_noreplace

_PUBLIC_OWNER = ".nfc-publish-owner"
_PUBLIC_COMPLETE = ".nfc-publish-complete"


class PublishingConflict(ValueError):
    """An existing output or unsafe path cannot be trusted or overwritten."""


def _check_unit(unit: Path, manifest: dict, fence: Callable[[], None]) -> None:
    fd = _open_directory_nofollow(unit)
    try:
        st = os.fstat(fd)
        if ([int(st.st_dev), int(st.st_ino)] !=
                [manifest["unit_dev"], manifest["unit_ino"]]):
            raise PublishingConflict("unit directory identity changed")
    finally:
        os.close(fd)
    fence()


def _entry(fd: int, name: str):
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _validate_shape(manifest: dict, unit: Path) -> tuple[list[dict], dict[str, list[dict]]]:
    rows = manifest.get("moves")
    groups = manifest.get("groups")
    cleanup = manifest.get("wrapper_cleanup")
    bindings = manifest.get("wrapper_identities")
    if (not isinstance(rows, list) or not rows or not isinstance(groups, list)
            or not isinstance(cleanup, list) or not isinstance(bindings, dict)
            or not set(cleanup).issubset(set(bindings))):
        raise PublishingConflict("invalid frozen source wrapper or group metadata")
    group_rows: dict[str, list[dict]] = {}
    group_names: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise PublishingConflict("invalid frozen group")
        name = group.get("name")
        kind = group.get("kind")
        count = group.get("count")
        byte_size = group.get("bytes")
        if (not isinstance(name, str) or not name or Path(name).name != name
                or name in (".", "..") or name.casefold() in group_names
                or kind not in ("P", "V", "Other")
                or not isinstance(count, int) or count < 1
                or (kind != "Other" and count > 200)
                or not isinstance(byte_size, int) or byte_size < 0
                or group.get("destination") != str(unit / name)):
            raise PublishingConflict("untrusted public group specification")
        group_names.add(name.casefold())
        group_rows[name] = []
    if manifest.get("operation") == "flatten_pure_media" and groups:
        raise PublishingConflict("flat plan must not have bucket destinations")
    if manifest.get("operation") != "flatten_pure_media" and not groups:
        raise PublishingConflict("grouped plan has no buckets")
    stage = unit / manifest["stage_directory"]
    public: set[str] = set()
    temporary: set[str] = set()
    for ordinal, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise PublishingConflict("invalid frozen file row")
        src, final, target = (Path(row.get(key, "")) for key in ("source", "final", "target"))
        if (not src.is_absolute() or not final.is_absolute() or not target.is_absolute()
                or not src.is_relative_to(unit) or src == unit
                or not final.is_relative_to(unit) or final == unit
                or target != stage / f"{ordinal:06d}{src.suffix}"
                or row.get("target_name") != final.name
                or src.suffix != final.suffix or
                any(".." in p.parts for p in (src, final, target))
                or str(final).casefold() in public or str(target) in temporary):
            raise PublishingConflict("untrusted frozen public file binding")
        public.add(str(final).casefold())
        temporary.add(str(target))
        identity = row.get("identity")
        if (not isinstance(identity, list) or len(identity) != 4
                or not all(isinstance(x, int) and not isinstance(x, bool) for x in identity)
                or identity[0] != manifest["unit_dev"]):
            raise PublishingConflict("invalid frozen file identity")
        if groups:
            if final.parent != unit or row["group"] != "Other":
                if final.parent == unit or final.parent.parent != unit:
                    raise PublishingConflict("public destination escaped group folder")
                name = final.parent.name
                if name not in group_rows:
                    raise PublishingConflict("public group was not frozen")
                expected = next(x for x in groups if x["name"] == name)
                if row["group"] != expected["kind"]:
                    raise PublishingConflict("public file kind does not match group")
                group_rows[name].append(row)
            else:
                raise PublishingConflict("Other files must use their frozen group")
        elif final.parent != unit:
            raise PublishingConflict("flat public path must be directly in unit")
    for group in groups:
        part = group_rows[group["name"]]
        if (len(part) != group["count"]
                or sum(row["identity"][2] for row in part) != group["bytes"]
                or len({Path(row["final"]).name.casefold() for row in part}) != len(part)):
            raise PublishingConflict("frozen group file counts or sizes differ")
    group_paths = {str(unit / group["name"]) for group in groups}
    for name, identity in bindings.items():
        path = Path(name)
        if (not path.is_relative_to(unit) or path == unit
                or not isinstance(identity, list) or len(identity) != 2
                or identity[0] != manifest["unit_dev"]):
            raise PublishingConflict("unsafe frozen wrapper binding")
        if name not in cleanup:
            # A correctly named old bucket can be a frozen source of this
            # same job. Such additional input folders must correspond to an
            # exact proposed group and contribute at least one frozen source.
            if (name not in group_paths or
                    not any(Path(row["source"]).is_relative_to(path) for row in rows)):
                raise PublishingConflict("untrusted additional source bucket")
    return rows, group_rows



def _group_receipt_path(frozen_manifest_path: Path, ordinal: int) -> Path:
    path = Path(frozen_manifest_path)
    return path.with_name(f"{path.name}.group-{ordinal:06d}.json")


def _group_receipt_record(manifest: dict, name: str, ordinal: int,
                          identity: tuple[int, int]) -> dict:
    return {
        "schema_version": 1, "job_id": manifest["job_id"],
        "manifest_checksum": _checksum(manifest),
        "name": name, "ordinal": ordinal,
        "dev": identity[0], "ino": identity[1],
    }


def _group_receipt_digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _read_group_receipt(path: Path, manifest: dict, name: str,
                        ordinal: int) -> tuple[int, int]:
    """Check the original group inode independently of a copyable owner marker."""
    directory_fd = _open_directory_nofollow(Path(path).parent)
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        except OSError as exc:
            raise PublishingConflict("private public-group identity receipt missing") from exc
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or (info.st_mode & 0o077) != 0
                    or not 0 < info.st_size <= 4096):
                raise PublishingConflict("public-group identity receipt unsafe")
            raw = stream.read(4097)
    finally:
        os.close(directory_fd)
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise PublishingConflict("public-group identity receipt corrupted") from exc
    if not isinstance(document, dict) or not isinstance(document.get("record"), dict):
        raise PublishingConflict("public-group identity receipt malformed")
    record = document["record"]
    if (record.get("schema_version") != 1 or
            record.get("manifest_checksum") != _checksum(manifest) or
            record.get("job_id") != manifest["job_id"] or
            record.get("name") != name or record.get("ordinal") != ordinal or
            not all(isinstance(record.get(k), int) and not isinstance(record.get(k), bool)
                    for k in ("dev", "ino")) or
            document.get("sha256") != _group_receipt_digest(record)):
        raise PublishingConflict("public-group identity receipt authority changed")
    return int(record["dev"]), int(record["ino"])


def _write_group_receipt(path: Path, manifest: dict, name: str,
                         ordinal: int, identity: tuple[int, int]) -> None:
    record = _group_receipt_record(manifest, name, ordinal, identity)
    raw = json.dumps({"record": record, "sha256": _group_receipt_digest(record)},
                     ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    directory_fd = _open_directory_nofollow(Path(path).parent)
    try:
        try:
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            # Never overwrite a receipt, even if an old task still exists.
            if _read_group_receipt(path, manifest, name, ordinal) != identity:
                raise PublishingConflict("public-group directory identity changed")
            return
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _group_receipts(manifest: dict, frozen_manifest_path: Path) -> dict[str, tuple[int, int]]:
    result = {}
    for ordinal, group in enumerate(manifest["groups"], 1):
        result[group["name"]] = _read_group_receipt(
            _group_receipt_path(frozen_manifest_path, ordinal),
            manifest, group["name"], ordinal,
        )
    return result


def _owned_public(directory: Path, witness: bytes) -> bool:
    if not os.path.lexists(directory):
        return False
    fd = _open_directory_nofollow(directory)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise PublishingConflict("public group is not a directory")
        return _read_marker(fd, _PUBLIC_OWNER, witness)
    finally:
        os.close(fd)


def _inspect_existing_group(directory: Path, part: list[dict], witness: bytes,
                            *, require_owner: bool) -> bool:
    fd = _open_directory_nofollow(directory)
    try:
        if require_owner and not _read_marker(fd, _PUBLIC_OWNER, witness):
            raise PublishingConflict("public group owner witness missing")
        expected = {Path(row["final"]).name: row for row in part}
        permitted = set(expected) | {_PUBLIC_OWNER, _PUBLIC_COMPLETE}
        with os.scandir(fd) as entries:
            observed = set()
            for entry in entries:
                if entry.name not in permitted:
                    raise PublishingConflict("foreign entry in public group")
                observed.add(entry.name)
                if entry.name in expected:
                    _check_identity(entry.stat(follow_symlinks=False),
                                    expected[entry.name]["identity"],
                                    directory / entry.name)
                elif not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                    raise PublishingConflict("unsafe public group witness")
        completed = _read_marker(fd, _PUBLIC_COMPLETE, witness)
        if completed and not set(expected).issubset(observed):
            raise PublishingConflict("public completion marker is inconsistent")
        return completed
    finally:
        os.close(fd)


def _foreign_preflight(unit: Path, manifest: dict, group_rows: dict[str, list[dict]],
                       rows: list[dict], witness: bytes, resume: bool,
                       frozen_manifest_path: Path) -> None:
    bindings = manifest["wrapper_identities"]
    if group_rows:
        for name, part in group_rows.items():
            group = unit / name
            if not os.path.lexists(group):
                continue
            if resume and _owned_public(group, witness):
                ordinal = [g["name"] for g in manifest["groups"]].index(name) + 1
                bound = _read_group_receipt(
                    _group_receipt_path(frozen_manifest_path, ordinal),
                    manifest, name, ordinal,
                )
                fd = _open_directory_nofollow(group)
                try:
                    opened = os.fstat(fd)
                    if (int(opened.st_dev), int(opened.st_ino)) != bound:
                        raise PublishingConflict("public group identity replaced after freezing")
                finally:
                    os.close(fd)
                _inspect_existing_group(group, part, witness, require_owner=True)
                continue
            if str(group) not in bindings:
                raise PublishingConflict("foreign public group folder occupied")
            fd = _open_directory_nofollow(group)
            try:
                info = os.fstat(fd)
                if [int(info.st_dev), int(info.st_ino)] != bindings[str(group)]:
                    raise PublishingConflict("foreign group replaced a frozen wrapper")
            finally:
                os.close(fd)
    else:
        for row in rows:
            target = Path(row["final"])
            if not os.path.lexists(target):
                continue
            if not resume:
                raise PublishingConflict("foreign flat output occupied")
            st = os.lstat(target)
            _check_identity(st, row["identity"], target)


def _retire_one_wrapper(path: Path, *, unit: Path, manifest: dict,
                        ordinal: int, witness: bytes, fence: Callable[[], None],
                        resume: bool) -> int:
    identity = manifest["wrapper_identities"][str(path)]
    groups = {str(unit / g["name"]) for g in manifest["groups"]}
    if str(path) in groups and os.path.lexists(path) and _owned_public(path, witness):
        return 0
    parent = path.parent
    tombstone = f".nfc-retired-{manifest['job_id']}-{ordinal:06d}"
    parent_fd = _open_directory_nofollow(parent)
    try:
        pending = _entry(parent_fd, tombstone)
        current = _entry(parent_fd, path.name)
        if pending is not None:
            if not resume or current is not None:
                raise PublishingConflict("untrusted old wrapper retirement workspace")
            if not stat.S_ISDIR(pending.st_mode) or [int(pending.st_dev), int(pending.st_ino)] != identity:
                raise PublishingConflict("old wrapper retirement identity changed")
        elif current is None:
            return 0
        else:
            if (not stat.S_ISDIR(current.st_mode)
                    or [int(current.st_dev), int(current.st_ino)] != identity):
                raise PublishingConflict("old classification wrapper identity changed")
            child_fd = _open_directory_nofollow(path)
            try:
                if [int(os.fstat(child_fd).st_dev), int(os.fstat(child_fd).st_ino)] != identity:
                    raise PublishingConflict("opened old wrapper binding changed")
                with os.scandir(child_fd) as entries:
                    if next(entries, None) is not None:
                        raise PublishingConflict("old wrapper not empty; foreign entry preserved")
            finally:
                os.close(child_fd)
            _check_unit(unit, manifest, fence)
            rename_noreplace_at(parent_fd, path.name, parent_fd, tombstone)
            os.fsync(parent_fd)
            pending = _entry(parent_fd, tombstone)
            if (pending is None or not stat.S_ISDIR(pending.st_mode)
                    or [int(pending.st_dev), int(pending.st_ino)] != identity):
                raise PublishingConflict("old wrapper identity changed during retirement")
        _check_unit(unit, manifest, fence)
        os.rmdir(tombstone, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return 1
    finally:
        os.close(parent_fd)


def _retire_wrappers(unit: Path, manifest: dict, witness: bytes,
                     fence: Callable[[], None], resume: bool) -> int:
    retired = 0
    # Children go first. Include frozen old buckets with already-correct
    # labels when they are also sources; never trust a matching name alone.
    retired_paths = sorted(
        manifest["wrapper_identities"],
        key=lambda p: (-len(Path(p).parts), p),
    )
    for i, literal in enumerate(retired_paths):
        retired += _retire_one_wrapper(Path(literal), unit=unit, manifest=manifest,
                                       ordinal=i, witness=witness, fence=fence,
                                       resume=resume)
    return retired


def _verify_group_parent_posix_permissions(
    unit_fd: int, manifest: dict, *, namespace_custody=None,
) -> None:
    """Check mode-specific directory ownership without weakening strict custody.

    A live frozen-manifest-bound maintenance session permits mixed NAS owners
    and shared ancestors, but only while the Worker really has write access.
    The operator, not the kernel, must exclude all other writers in this mode.
    A manifest field alone never authorizes this weaker policy.
    """
    maintenance = manifest.get("execution_mode") == "maintenance_window"
    maintenance_session = maintenance and is_maintenance_session(namespace_custody)
    if maintenance and not maintenance_session:
        raise PublishingConflict("maintenance publication requires a live maintenance session")
    info = os.fstat(unit_fd)
    if (not stat.S_ISDIR(info.st_mode)
            or (int(info.st_dev), int(info.st_ino)) != (
                manifest["unit_dev"], manifest["unit_ino"])):
        raise PublishingConflict("public unit directory identity changed")
    if maintenance_session:
        # Check the lock, pinned unit identity, approved frozen manifest,
        # non-root Worker identity and live effective POSIX permissions.
        assert_operation_authorized(
            namespace_custody, (Path(manifest["unit"]),), manifest=manifest,
        )
        if (os.fstatvfs(unit_fd).f_flag & os.ST_RDONLY
                or not os.access(".", os.W_OK | os.X_OK,
                                 dir_fd=unit_fd, effective_ids=True)):
            raise PublishingConflict("maintenance public unit is not writable by the Worker")
    elif (int(info.st_uid) != os.geteuid()
          or stat.S_IMODE(info.st_mode) & 0o022):
        raise PublishingConflict(
            "public unit owner or writable permissions are unsafe"
        )

    # Verify the entire ancestor chain by pinned directory FDs. A writable
    # grandparent could rename/rebind the unit's immediate parent even when
    # that immediate parent itself is private.
    unit = Path(manifest["unit"])
    child_path = unit
    child_info = info
    trusted_owners = {0, os.geteuid()}
    while True:
        parent_path = child_path.parent
        if parent_path == child_path:
            break
        parent_fd = _open_directory_nofollow(parent_path)
        try:
            parent = os.fstat(parent_fd)
            named = _entry(parent_fd, child_path.name)
            if (not stat.S_ISDIR(parent.st_mode)
                    or named is None or not stat.S_ISDIR(named.st_mode)
                    or (int(named.st_dev), int(named.st_ino)) != (
                        int(child_info.st_dev), int(child_info.st_ino))):
                raise PublishingConflict("public unit ancestor binding changed")
            mode = stat.S_IMODE(parent.st_mode)
            if not maintenance_session and int(parent.st_uid) not in trusted_owners:
                raise PublishingConflict(
                    "public unit ancestor owner is not trusted"
                )
            if not maintenance_session and mode & 0o022:
                # A sticky shared parent (for example /tmp) protects a child
                # owned by this Worker or root from other users' rename/unlink.
                if not (mode & stat.S_ISVTX
                        and int(named.st_uid) in trusted_owners):
                    raise PublishingConflict(
                        "public unit ancestor writable permissions are unsafe"
                    )
            child_info = parent
        finally:
            os.close(parent_fd)
        child_path = parent_path


def _create_public_group_direct(
    unit: Path, name: str, manifest: dict, witness: bytes,
    fence: Callable[[], None], *, frozen_manifest_path: Path,
    namespace_custody=None,
) -> None:
    """Provision a no-overwrite public group without SOURCE-directory rename.

    This primitive removes SEC-12's private pending-name rename path, but it
    does NOT by itself prove custody against same-UID/root writers able to
    replace the public basename between mkdirat and openat. In maintenance
    mode the operator must exclude these writers. No error branch deletes
    an entry.
    """
    if os.geteuid() == 0 and not is_nas_compat_root_worker(maintenance_session_settings(namespace_custody)):
        raise PublishingConflict(
            "grouped publication requires a non-root Worker or the explicit NAS 0:10000 profile"
        )
    names = [row["name"] for row in manifest.get("groups", [])]
    if name not in names or Path(name).name != name or name in (".", ".."):
        raise PublishingConflict("group is not present in the frozen plan")
    ordinal = names.index(name) + 1
    stage = unit / manifest["stage_directory"]
    _check_unit(unit, manifest, fence)
    stage_fd = _open_directory_nofollow(stage)
    unit_fd = _open_directory_nofollow(unit)
    group_fd = None
    try:
        stage_info = _assert_private_stage_fd(stage_fd)
        if (int(stage_info.st_dev) != manifest["unit_dev"]
                or not _read_marker(stage_fd, ".nfc-stage-authority", witness)
                or not _read_marker(stage_fd, ".nfc-stage-complete", witness)):
            raise PublishingConflict("private stage ownership or completion is missing")
        _verify_group_parent_posix_permissions(
            unit_fd, manifest, namespace_custody=namespace_custody,
        )
        if _entry(unit_fd, name) is not None:
            raise PublishingConflict("foreign public group already occupied")
        fence()
        # A permissive chmod between preflight and the mutation boundary
        # must fail closed. This check does not replace an OS-enforced
        # exclusive namespace boundary for same-UID/root actors.
        _verify_group_parent_posix_permissions(
            unit_fd, manifest, namespace_custody=namespace_custody,
        )
        try:
            os.mkdir(name, mode=0o700, dir_fd=unit_fd)
        except FileExistsError as exc:
            raise PublishingConflict("public group raced with exclusive creation") from exc
        os.fsync(unit_fd)

        # Revalidate operation authority after mkdir and before openat.
        # Leave a changed binding untouched for manual reconciliation.
        # In maintenance mode another writer could still race the open.
        fence()

        # A created-but-not-yet-witnessed directory is intentionally left for
        # manual reconciliation after a crash. Do not adopt unknown folders.
        group_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY |
                           os.O_NOFOLLOW, dir_fd=unit_fd)
        created = os.fstat(group_fd)
        fence()
        bound = _entry(unit_fd, name)
        if (bound is None or not stat.S_ISDIR(bound.st_mode)
                or (int(bound.st_dev), int(bound.st_ino)) != (
                    int(created.st_dev), int(created.st_ino))
                or int(created.st_dev) != manifest["unit_dev"]
                or int(created.st_uid) != os.geteuid()
                or stat.S_IMODE(created.st_mode) & 0o077):
            raise PublishingConflict("new public group inode/owner/mode untrusted")
        with os.scandir(group_fd) as entries:
            if next(entries, None) is not None:
                raise PublishingConflict("new public group is not empty")
        # Do not create an owner witness or receipt unless the pinned FD is
        # still the directory named by the public parent under live custody.
        fence()
        _assert_named_directory(
            unit / name, group_fd,
            (int(created.st_dev), int(created.st_ino)),
        )
        shared_gid = shared_config_gid()
        if shared_gid is not None:
            # Only this newly created, still-pinned inode receives API read
            # access. Original directories and payload file modes are untouched.
            fence()
            _assert_named_directory(unit / name, group_fd,
                                    (int(created.st_dev), int(created.st_ino)))
            if int(created.st_gid) != shared_gid:
                os.fchown(group_fd, -1, shared_gid)
            fence()
            _assert_named_directory(unit / name, group_fd,
                                    (int(created.st_dev), int(created.st_ino)))
            os.fchmod(group_fd, 0o750)
            readable = os.fstat(group_fd)
            if (readable.st_uid != os.geteuid() or readable.st_gid != shared_gid
                    or stat.S_IMODE(readable.st_mode) != 0o750):
                raise PublishingConflict("new public group read-only sharing failed")
        _write_marker(group_fd, _PUBLIC_OWNER, witness)
        os.fsync(group_fd)
        identity = (int(created.st_dev), int(created.st_ino))
        _write_group_receipt(
            _group_receipt_path(frozen_manifest_path, ordinal),
            manifest, name, ordinal, identity,
        )
        _assert_public_group_binding(unit, unit / name, group_fd, witness, identity)
        os.fsync(group_fd)
        os.fsync(unit_fd)
    finally:
        if group_fd is not None:
            os.close(group_fd)
        os.close(unit_fd)
        os.close(stage_fd)


def _create_public_group(unit: Path, name: str, manifest: dict, witness: bytes,
                         fence: Callable[[], None], *, resume: bool = False,
                         frozen_manifest_path: Path) -> None:
    """Prepare group in private stage, then promote via atomic NOREPLACE.

    No public directory name is ever created as an unwitnessed empty folder.
    A crash before promotion leaves a frozen, witnessed private directory
    that is recognizable only by this exact manifest and lease.
    """
    names = [group["name"] for group in manifest["groups"]]
    if name not in names:
        raise PublishingConflict("public group not present in frozen plan")
    ordinal = names.index(name) + 1
    pending_name = f".nfc-publish-pending-{ordinal:06d}"
    stage = unit / manifest["stage_directory"]
    _check_unit(unit, manifest, fence)
    stage_fd = _open_directory_nofollow(stage)
    unit_fd = _open_directory_nofollow(unit)
    try:
        if (int(os.fstat(stage_fd).st_dev) != manifest["unit_dev"] or
                not _read_marker(stage_fd, ".nfc-stage-authority", witness) or
                not _read_marker(stage_fd, ".nfc-stage-complete", witness)):
            raise PublishingConflict("private stage ownership or completion is missing")
        existing = _entry(stage_fd, pending_name)
        if existing is not None and not resume:
            raise PublishingConflict("unexpected private publication workspace")
        if existing is None:
            fence()
            os.mkdir(pending_name, mode=0o700, dir_fd=stage_fd)
            os.fsync(stage_fd)

        pending_fd = os.open(pending_name, os.O_RDONLY | os.O_DIRECTORY |
                             os.O_NOFOLLOW, dir_fd=stage_fd)
        try:
            info = os.fstat(pending_fd)
            bound = _entry(stage_fd, pending_name)
            if (bound is None or not stat.S_ISDIR(bound.st_mode)
                    or (int(info.st_dev), int(info.st_ino)) !=
                    (int(bound.st_dev), int(bound.st_ino)) or
                    int(info.st_dev) != manifest["unit_dev"]):
                raise PublishingConflict("private group replaced before publication")
            if existing is None:
                with os.scandir(pending_fd) as entries:
                    if next(entries, None) is not None:
                        raise PublishingConflict("foreign entry in new private group")
                _check_unit(unit, manifest, fence)
                _write_marker(pending_fd, _PUBLIC_OWNER, witness)
            elif not _read_marker(pending_fd, _PUBLIC_OWNER, witness):
                raise PublishingConflict("private publication owner witness missing")
            with os.scandir(pending_fd) as entries:
                if {entry.name for entry in entries} != {_PUBLIC_OWNER}:
                    raise PublishingConflict("foreign entry in private publication workspace")
            os.fsync(pending_fd)
            os.fsync(stage_fd)
            original_identity = (int(info.st_dev), int(info.st_ino))
            receipt_path = _group_receipt_path(frozen_manifest_path, ordinal)
            if existing is not None:
                # An existing pending directory is never adopted solely
                # because its marker matches. The private receipt must
                # already prove this exact inode before this attempt.
                if _read_group_receipt(
                    receipt_path, manifest, name, ordinal,
                ) != original_identity:
                    raise PublishingConflict("private group directory identity replaced")
            else:
                _write_group_receipt(
                    receipt_path, manifest, name, ordinal, original_identity,
                )
            if _entry(unit_fd, name) is not None:
                raise PublishingConflict("foreign public group occupied before promotion")
            _check_unit(unit, manifest, fence)
            if not _read_marker(pending_fd, _PUBLIC_OWNER, witness):
                raise PublishingConflict("private group owner witness changed")
            if _entry(stage_fd, pending_name) is None:
                raise PublishingConflict("private publication directory disappeared")
            try:
                rename_noreplace_at(stage_fd, pending_name, unit_fd, name)
            except FileExistsError as exc:
                raise PublishingConflict("foreign public group raced with no-replace promotion") from exc
            except OSError as exc:
                if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
                    raise PublishingConflict("foreign group occupied at promotion") from exc
                raise
            os.fsync(stage_fd)
            os.fsync(unit_fd)
            promoted = _entry(unit_fd, name)
            if (promoted is None or not stat.S_ISDIR(promoted.st_mode)
                    or (int(promoted.st_dev), int(promoted.st_ino)) !=
                    (int(info.st_dev), int(info.st_ino))):
                raise PublishingConflict("public group changed after atomic promotion")
        finally:
            os.close(pending_fd)
    finally:
        os.close(unit_fd)
        os.close(stage_fd)


def _assert_public_group_binding(unit: Path, group: Path, group_fd: int,
                                 witness: bytes,
                                 expected_identity: tuple[int, int]) -> None:
    """Require our witness and current unit-child identity before public IO."""
    if not _read_marker(group_fd, _PUBLIC_OWNER, witness):
        raise PublishingConflict("foreign public group has no owner witness")
    parent_fd = _open_directory_nofollow(unit)
    try:
        named = _entry(parent_fd, group.name)
        opened = os.fstat(group_fd)
        if (named is None or not stat.S_ISDIR(named.st_mode)
                or (int(named.st_dev), int(named.st_ino)) !=
                (int(opened.st_dev), int(opened.st_ino))
                or (int(opened.st_dev), int(opened.st_ino)) != expected_identity):
            raise PublishingConflict("public group directory identity or binding replaced")
    finally:
        os.close(parent_fd)


def _link_one(row: dict, *, stage: Path, unit: Path, witness: bytes,
              manifest: dict, fence: Callable[[], None], resume: bool,
              group_bindings: dict[str, tuple[int, int]]) -> bool:
    """Link the frozen OPEN staged inode; never resolve its raced source basename."""
    source_name = Path(row["target"]).name
    dest = Path(row["final"])
    stage_fd = _open_directory_nofollow(stage)
    target_fd = _open_directory_nofollow(dest.parent)
    source_file_fd = None
    try:
        stage_info = _assert_private_stage_fd(stage_fd)
        if (int(stage_info.st_dev) != manifest["unit_dev"]
                or int(os.fstat(target_fd).st_dev) != manifest["unit_dev"]):
            raise PublishingConflict("cross-device publication forbidden")
        if not _read_marker(stage_fd, ".nfc-stage-authority", witness):
            raise PublishingConflict("stage owner witness disappeared")
        if dest.parent != unit:
            _assert_public_group_binding(
                unit, dest.parent, target_fd, witness,
                group_bindings[dest.parent.name],
            )
        source_stat = _entry(stage_fd, source_name)
        _check_identity(source_stat, row["identity"], stage / source_name)
        # Open and verify the actual file FD before the LAST basename check.
        # A raced FIFO must not block before fstat rejects it.
        source_file_fd = os.open(
            source_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
            getattr(os, "O_CLOEXEC", 0), dir_fd=stage_fd,
        )
        opened = os.fstat(source_file_fd)
        if (not stat.S_ISREG(opened.st_mode) or
                [int(opened.st_dev), int(opened.st_ino),
                 int(opened.st_size), int(opened.st_mtime_ns)] != row["identity"]):
            raise PublishingConflict("opened staged inode changed since freeze")
        already = _entry(target_fd, dest.name)
        if already is not None:
            if not resume:
                raise PublishingConflict("foreign or unexpected public target occupied")
            _check_identity(already, row["identity"], dest)
            return False
        _check_unit(unit, manifest, fence)
        if dest.parent != unit:
            _assert_public_group_binding(
                unit, dest.parent, target_fd, witness,
                group_bindings[dest.parent.name],
            )
        _assert_private_stage_fd(stage_fd)
        _check_identity(_entry(stage_fd, source_name), row["identity"], stage / source_name)
        try:
            # Linux linkat(AT_EMPTY_PATH) is exclusive and source-fd bound.
            # No os.link(source_name) fallback can operate on a replacement.
            link_pinned_inode_noreplace(source_file_fd, target_fd, dest.name)
        except FileExistsError as exc:
            raise PublishingConflict("foreign public target raced with publication") from exc
        _check_identity(_entry(target_fd, dest.name), row["identity"], dest)
        _check_identity(_entry(stage_fd, source_name), row["identity"], stage / source_name)
        if dest.parent != unit:
            _assert_public_group_binding(
                unit, dest.parent, target_fd, witness,
                group_bindings[dest.parent.name],
            )
        os.fsync(target_fd)
        return True
    finally:
        if source_file_fd is not None:
            os.close(source_file_fd)
        os.close(target_fd)
        os.close(stage_fd)


def _mark_completed(directory: Path, part: list[dict], witness: bytes,
                    fence: Callable[[], None],
                    expected_identity: tuple[int, int]) -> None:
    fd = _open_directory_nofollow(directory)
    try:
        _assert_public_group_binding(directory.parent, directory, fd, witness,
                                     expected_identity)
        for row in part:
            dest = Path(row["final"])
            _check_identity(_entry(fd, dest.name), row["identity"], dest)
        if not _read_marker(fd, _PUBLIC_COMPLETE, witness):
            fence()
            _write_marker(fd, _PUBLIC_COMPLETE, witness)
    finally:
        os.close(fd)


def _assert_named_directory(directory: Path, fd: int,
                            identity: tuple[int, int]) -> None:
    opened = os.fstat(fd)
    parent_fd = _open_directory_nofollow(directory.parent)
    try:
        named = _entry(parent_fd, directory.name)
        if (not stat.S_ISDIR(opened.st_mode)
                or (int(opened.st_dev), int(opened.st_ino)) != identity
                or named is None or not stat.S_ISDIR(named.st_mode)
                or (int(named.st_dev), int(named.st_ino)) != identity):
            raise PublishingConflict("frozen input/public directory binding changed")
    finally:
        os.close(parent_fd)


def _original_children(manifest: dict, directory: Path) -> dict:
    result = {
        Path(row["source"]).name: ("file", row["identity"])
        for row in manifest["moves"] if Path(row["source"]).parent == directory
    }
    for literal, identity in manifest["wrapper_identities"].items():
        path = Path(literal)
        if path.parent == directory:
            if path.name in result:
                raise PublishingConflict("frozen file/directory roles overlap")
            result[path.name] = ("directory", identity)
    return result


def _check_role_entry(info, kind: str, identity: list[int], path: Path) -> None:
    if kind == "file":
        _check_identity(info, identity, path)
    elif (info is None or not stat.S_ISDIR(info.st_mode)
          or [int(info.st_dev), int(info.st_ino)] != identity):
        raise PublishingConflict("frozen nested wrapper identity changed")


def _inspect_original_wrapper(manifest: dict, directory: Path, identity: list[int]) -> None:
    expected = _original_children(manifest, directory)
    fd = _open_directory_nofollow(directory)
    try:
        _assert_named_directory(directory, fd, tuple(identity))
        with os.scandir(fd) as entries:
            observed = set()
            for entry in entries:
                if entry.name not in expected:
                    raise PublishingConflict("foreign entry in retained source wrapper")
                observed.add(entry.name)
                _check_role_entry(entry.stat(follow_symlinks=False),
                                  *expected[entry.name], directory / entry.name)
        if observed != set(expected):
            raise PublishingConflict("retained source wrapper inventory changed")
        _assert_named_directory(directory, fd, tuple(identity))
    finally:
        os.close(fd)


def _inspect_role_group(
    manifest: dict, directory: Path, part: list[dict], roles: dict,
    witness: bytes, identity: tuple[int, int], *, phase: str,
) -> None:
    """Check exact original/final roles, never treating a matching name as ownership.

    Input groups have only their frozen original entries. A witnessed resume
    may have a subset of nonconflicting finals. Prepared groups have all such
    finals, while deferred destinations still retain their original occupants.
    """
    if phase not in ("input", "resume", "prepared"):
        raise PublishingConflict("invalid prepared publication phase")
    expected = _original_children(manifest, directory)
    required = set(expected)
    deferred = {row["final"] for row in roles["deferred_rows"]}
    final_names = set()
    partial = any(row["final"] in deferred for row in part)
    if phase != "input":
        for row in part:
            if row["final"] in deferred:
                continue
            name = Path(row["final"]).name
            entry = ("file", row["identity"])
            if name in expected and expected[name] != entry:
                raise PublishingConflict("prepared final overlaps a different original role")
            expected[name] = entry
            final_names.add(name)
        if phase == "prepared":
            required.update(final_names)
    markers = set() if phase == "input" else {_PUBLIC_OWNER}
    if phase != "input" and not partial:
        markers.add(_PUBLIC_COMPLETE)
    fd = _open_directory_nofollow(directory)
    try:
        _assert_named_directory(directory, fd, identity)
        observed = set()
        with os.scandir(fd) as entries:
            for entry in entries:
                observed.add(entry.name)
                info = entry.stat(follow_symlinks=False)
                if entry.name in expected:
                    _check_role_entry(info, *expected[entry.name], directory / entry.name)
                elif entry.name in markers:
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or stat.S_IMODE(info.st_mode) != 0o600
                            or int(info.st_uid) != os.geteuid()):
                        raise PublishingConflict("unsafe prepared group witness")
                    if not _read_marker(fd, entry.name, witness):
                        raise PublishingConflict("prepared group witness disappeared")
                else:
                    raise PublishingConflict("foreign entry in prepared public group")
        if not required.issubset(observed):
            raise PublishingConflict("prepared original or final inventory incomplete")
        if phase != "input" and _PUBLIC_OWNER not in observed:
            raise PublishingConflict("prepared group owner witness missing")
        if _PUBLIC_COMPLETE in observed and not final_names.issubset(observed):
            raise PublishingConflict("prepared group completion witness is inconsistent")
        if phase == "prepared" and not partial and _PUBLIC_COMPLETE not in observed:
            raise PublishingConflict("prepared group completion witness missing")
        _assert_named_directory(directory, fd, identity)
    finally:
        os.close(fd)


def _source_identities_by_name(rows: list[dict]) -> dict[str, list[list[int]]]:
    result: dict[str, list[list[int]]] = {}
    for row in rows:
        result.setdefault(row["source"].casefold(), []).append(row["identity"])
    return result


def _check_deferred_occupant(row: dict, source_identities: dict) -> None:
    """A deferred final is vacant or aliases a still-retained frozen source."""
    target = Path(row["final"])
    try:
        parent_fd = _open_directory_nofollow(target.parent)
    except FileNotFoundError:
        return
    try:
        found = _entry(parent_fd, target.name)
        if found is None:
            return
        candidates = source_identities.get(row["final"].casefold(), [])
        if not any(stat.S_ISREG(found.st_mode) and [
                int(found.st_dev), int(found.st_ino), int(found.st_size),
                int(found.st_mtime_ns)] == identity for identity in candidates):
            raise PublishingConflict("deferred final is occupied by a foreign inode")
    finally:
        os.close(parent_fd)


def verify_prepared_publication(manifest: dict, *, frozen_manifest_path: Path) -> dict:
    """Read-only verification of every original, stage and prepared final role.

    Deferred final names are not advertised as published. This is inventory
    evidence only; it neither issues namespace custody nor authorizes cleanup.
    """
    try:
        if not uses_path_roles(manifest):
            raise PublishingConflict("explicit prepared publication policy required")
        unit = Path(manifest["unit"])
        frozen = Path(frozen_manifest_path)
        if load_frozen_preview_manifest(frozen, job_id=manifest["job_id"], unit=unit) != manifest:
            raise PublishingConflict("prepared frozen manifest changed")
        rows, group_rows = _validate_shape(manifest, unit)
        roles = classify_path_roles(manifest)
        _check_unit(unit, manifest, lambda: None)
        deferred = {row["final"] for row in roles["deferred_rows"]}
        source_identities = _source_identities_by_name(rows)
        witness = _authority(manifest)
        for row in rows:
            for field in ("source", "target", "final"):
                if field == "final" and row["final"] in deferred:
                    _check_deferred_occupant(row, source_identities)
                    continue
                path = Path(row[field])
                fd = _open_directory_nofollow(path.parent)
                try:
                    _check_identity(_entry(fd, path.name), row["identity"], path)
                finally:
                    os.close(fd)
        stage = unit / manifest["stage_directory"]
        stage_fd = _open_directory_nofollow(stage)
        try:
            _assert_private_stage_fd(stage_fd)
            if not _inspect_stage(stage_fd, stage, rows, witness, groups=manifest["groups"]):
                raise PublishingConflict("prepared stage is incomplete")
            with os.scandir(stage_fd) as entries:
                actual = {entry.name for entry in entries}
            if actual != {Path(row["target"]).name for row in rows} | {
                    ".nfc-stage-authority", ".nfc-stage-complete"}:
                raise PublishingConflict("foreign prepared stage entry")
        finally:
            os.close(stage_fd)
        bindings = _group_receipts(manifest, frozen)
        for name, part in group_rows.items():
            original = roles["retained_groups"].get(str(unit / name))
            if original is not None and tuple(original) != bindings[name]:
                raise PublishingConflict("retained group receipt differs from frozen input")
            _inspect_role_group(manifest, unit / name, part, roles, witness,
                                bindings[name], phase="prepared")
        for name, identity in roles["removed_wrappers"].items():
            _inspect_original_wrapper(manifest, Path(name), identity)
        expected_root = {manifest["stage_directory"]} | set(group_rows)
        for row in rows:
            for key in ("source", "final"):
                if key == "final" and row["final"] in deferred:
                    continue
                expected_root.add(Path(row[key]).relative_to(unit).parts[0])
        root_fd = _open_directory_nofollow(unit)
        try:
            with os.scandir(root_fd) as entries:
                for entry in entries:
                    if entry.name not in expected_root and not stat.S_ISDIR(
                            entry.stat(follow_symlinks=False).st_mode):
                        raise PublishingConflict("foreign root entry in prepared inventory")
        finally:
            os.close(root_fd)
        _check_unit(unit, manifest, lambda: None)
        return {
            "file_count": len(rows), "retained_files": len(roles["retained_sources"]),
            "deferred_files": len(deferred), "publication_complete": not deferred,
            "verified_source_links": len(rows), "verified_stage_links": len(rows),
            "verified_final_links": len(rows) - len(deferred),
            "verified_wrapper_count": len(manifest["wrapper_identities"]),
            "verified_group_count": len(group_rows),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, PublishingConflict):
            raise
        raise PublishingConflict(f"prepared publication inventory unsafe: {exc}") from exc


def _publish_with_path_roles(
    manifest: dict, frozen: Path, *, fence: Callable[[], None], resume: bool,
    namespace_custody,
) -> dict:
    """Publish only unoccupied/self finals; release no original source name."""
    unit = Path(manifest["unit"])
    rows, group_rows = _validate_shape(manifest, unit)
    roles = classify_path_roles(manifest)
    witness = _authority(manifest)
    deferred = {row["final"] for row in roles["deferred_rows"]}
    source_identities = _source_identities_by_name(rows)
    retained = {row["source"] for row in roles["retained_sources"]}
    parents = {unit}
    for row in rows:
        parents.update(Path(row[key]).parent for key in ("source", "target", "final"))

    def guard() -> None:
        fence()
        # Public directory creation is the SEC-12 grouped namespace boundary.
        # A pure flat plan creates no group directory and only publishes
        # inode-pinned files with linkat no-replace while retaining originals.
        # Grouped plans additionally require a scoped operation authority.
        if group_rows:
            assert_operation_authorized(namespace_custody, sorted(parents))

    guard()
    # Validate every prospective group before creating any receipt or marker.
    for ordinal, (name, part) in enumerate(group_rows.items(), 1):
        group = unit / name
        receipt = _group_receipt_path(frozen, ordinal)
        original = roles["retained_groups"].get(str(group))
        if original is not None:
            has_receipt = os.path.lexists(receipt)
            if has_receipt and not resume:
                raise PublishingConflict("unexpected retained group receipt requires recovery")
            if has_receipt and _read_group_receipt(receipt, manifest, name, ordinal) != tuple(original):
                raise PublishingConflict("retained group receipt differs from frozen input")
            fd = _open_directory_nofollow(group)
            try:
                _assert_named_directory(group, fd, tuple(original))
                owned = _entry(fd, _PUBLIC_OWNER) is not None
            finally:
                os.close(fd)
            if owned and not has_receipt:
                raise PublishingConflict("foreign owner marker lacks original group receipt")
            _inspect_role_group(manifest, group, part, roles, witness, tuple(original),
                                phase="resume" if owned else "input")
        elif os.path.lexists(group):
            if not resume:
                raise PublishingConflict("foreign public group folder occupied")
            identity = _read_group_receipt(receipt, manifest, name, ordinal)
            _inspect_role_group(manifest, group, part, roles, witness, identity, phase="resume")
        elif os.path.lexists(receipt):
            raise PublishingConflict("public group disappeared after its private receipt")
    for literal, identity in roles["removed_wrappers"].items():
        _inspect_original_wrapper(manifest, Path(literal), identity)
    for row in rows:
        if row["final"] in deferred:
            _check_deferred_occupant(row, source_identities)
            continue
        final = Path(row["final"])
        if os.path.lexists(final):
            if row["source"] not in retained and not resume:
                raise PublishingConflict("foreign prepared final target occupied")
            _check_identity(os.lstat(final), row["identity"], final)

    for ordinal, (name, part) in enumerate(group_rows.items(), 1):
        group = unit / name
        original = roles["retained_groups"].get(str(group))
        if original is not None:
            receipt = _group_receipt_path(frozen, ordinal)
            fd = _open_directory_nofollow(group)
            try:
                _assert_named_directory(group, fd, tuple(original))
                if not os.path.lexists(receipt):
                    _inspect_role_group(manifest, group, part, roles, witness,
                                        tuple(original), phase="input")
                    guard()
                    _assert_named_directory(group, fd, tuple(original))
                    _write_group_receipt(receipt, manifest, name, ordinal, tuple(original))
                if _entry(fd, _PUBLIC_OWNER) is None:
                    _inspect_role_group(manifest, group, part, roles, witness,
                                        tuple(original), phase="input")
                    guard()
                    _assert_named_directory(group, fd, tuple(original))
                    _write_marker(fd, _PUBLIC_OWNER, witness)
                _assert_public_group_binding(unit, group, fd, witness, tuple(original))
            finally:
                os.close(fd)
        elif not os.path.lexists(group):
            guard()
            _create_public_group_direct(unit, name, manifest, witness, guard,
                                        frozen_manifest_path=frozen,
                                        namespace_custody=namespace_custody)
    bindings = _group_receipts(manifest, frozen)
    stage = unit / manifest["stage_directory"]
    published = reconciled = 0
    for row in rows:
        if row["final"] in deferred:
            continue
        guard()
        if _link_one(row, stage=stage, unit=unit, witness=witness,
                     manifest=manifest, fence=guard,
                     resume=resume or row["source"] in retained,
                     group_bindings=bindings):
            published += 1
        else:
            reconciled += 1
    for name, part in group_rows.items():
        if not any(row["final"] in deferred for row in part):
            guard()
            _mark_completed(unit / name, part, witness, guard, bindings[name])
    verified = verify_prepared_publication(manifest, frozen_manifest_path=frozen)
    guard()
    return {
        **verified, "unit": str(unit), "published_files": published,
        "reconciled_files": reconciled, "retired_wrappers": 0,
        "ready_for_retirement": not deferred, "prepared_for_cleanup": True,
    }


def publish_frozen_stage(
    manifest: dict, *, frozen_manifest_path: Path, allowed_roots: list[Path],
    lease_fence: Callable[[], None], quarantine_root: Path | None = None,
    resume: bool = False, defer_directory_cleanup: bool = False,
    namespace_custody=None,
) -> dict:
    """Publish a verified stage, retaining all staging/recovery witnesses.

    On a crash the caller must use resume=True with the SAME frozen manifest.
    Existing foreign names are never removed or overwritten. This does NOT
    retire the stage, public witness files, or authorize real NAS execution.
    """
    if not callable(lease_fence):
        raise PublishingConflict("active Worker lease fence is required")
    try:
        if not isinstance(manifest, dict):
            raise PublishingConflict("invalid frozen manifest")
        unit = Path(manifest.get("unit", ""))
        if not unit.is_absolute():
            raise PublishingConflict("unit must be absolute")
        approved = load_frozen_preview_manifest(
            Path(frozen_manifest_path), job_id=manifest["job_id"], unit=unit)
        if approved != manifest:
            raise PublishingConflict("frozen manifest content changed")
        if manifest.get("cleanup_policy") == "deferred" and not defer_directory_cleanup:
            raise PublishingConflict(
                "deferred cleanup manifest prohibits automatic wrapper retirement"
            )
        _check_scope(unit, [Path(p) for p in allowed_roots],
                     Path(quarantine_root) if quarantine_root is not None else None)
        rows, group_rows = _validate_shape(manifest, unit)
        lease_fence = publication_fence(manifest, namespace_custody, lease_fence)
        _check_unit(unit, manifest, lease_fence)
        if defer_directory_cleanup:
            # Do not call the unsafe source-name rename/rmdir path. This
            # mode is the only path used by the dedicated V1.6 Worker.
            from app.batch.media_organizer_deferred_cleanup import validate_deferred_publication
            validate_deferred_publication(
                manifest, namespace_custody=namespace_custody,
            )
        stage = unit / manifest["stage_directory"]
        if not os.path.lexists(stage):
            raise PublishingConflict("verified stage missing; cannot publish")
        # Resume is also the stage-custody consistency check. It may finish a
        # partially staged, checksum-authorized source before publication.
        stage_frozen_sources(
            manifest, frozen_manifest_path=Path(frozen_manifest_path),
            allowed_roots=[Path(p) for p in allowed_roots],
            quarantine_root=quarantine_root, lease_fence=lease_fence,
            resume=True,
        )
        if uses_path_roles(manifest):
            return _publish_with_path_roles(
                manifest, Path(frozen_manifest_path), fence=lease_fence,
                resume=resume, namespace_custody=namespace_custody,
            )
        witness = _authority(manifest)
        _foreign_preflight(
            unit, manifest, group_rows, rows, witness, resume,
            Path(frozen_manifest_path),
        )
        retired = 0 if defer_directory_cleanup else _retire_wrappers(
            unit, manifest, witness, lease_fence, resume,
        )
        for name, part in group_rows.items():
            folder = unit / name
            if os.path.lexists(folder):
                if not resume:
                    raise PublishingConflict("foreign group cannot be adopted without resume")
                _inspect_existing_group(folder, part, witness, require_owner=True)
            else:
                if defer_directory_cleanup:
                    # No SOURCE directory rename. This branch runs only when
                    # operation authority is checked for this unit.
                    assert_operation_authorized(namespace_custody, (unit,))
                    _create_public_group_direct(
                        unit, name, manifest, witness, lease_fence,
                        frozen_manifest_path=Path(frozen_manifest_path),
                        namespace_custody=namespace_custody,
                    )
                else:
                    # Historical non-deferred synthetic library path only.
                    _create_public_group(
                        unit, name, manifest, witness, lease_fence,
                        resume=resume,
                        frozen_manifest_path=Path(frozen_manifest_path),
                    )
        group_bindings = _group_receipts(manifest, Path(frozen_manifest_path))
        published = reconciled = 0
        for row in rows:
            if group_rows and defer_directory_cleanup:
                assert_operation_authorized(
                    namespace_custody, (stage, Path(row["final"]).parent),
                )
            if _link_one(row, stage=stage, unit=unit, witness=witness,
                         manifest=manifest, fence=lease_fence, resume=resume,
                         group_bindings=group_bindings):
                published += 1
            else:
                reconciled += 1
        for name, part in group_rows.items():
            _mark_completed(unit / name, part, witness, lease_fence,
                            group_bindings[name])
            if not _inspect_existing_group(unit / name, part, witness, require_owner=True):
                raise PublishingConflict("public completion witness is missing")
        for row in rows:
            dest = Path(row["final"])
            parent_fd = _open_directory_nofollow(dest.parent)
            try:
                _check_identity(_entry(parent_fd, dest.name), row["identity"], dest)
            finally:
                os.close(parent_fd)
        return {
            "published_files": published, "reconciled_files": reconciled,
            "retired_wrappers": retired, "file_count": len(rows),
            "ready_for_retirement": True, "unit": str(unit),
        }
    except (StagingConflict, FrozenPreviewError, OSError, ValueError,
            TypeError, KeyError) as exc:
        if isinstance(exc, PublishingConflict):
            raise
        raise PublishingConflict(f"frozen publication unsafe: {exc}") from exc
