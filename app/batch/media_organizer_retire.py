"""Finalize fully verified public media without deleting original payload bytes.

An audited retirement marker is persisted BEFORE unlinking any staged hardlink.
Every public inode and group is rechecked and fsynced. A partial retirement
can resume only with the original frozen manifest and custody witnesses.
This remains an isolated library function; no production execute route exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Callable

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_manifest import (
    FrozenPreviewError, load_frozen_preview_manifest, _checksum,
)
from app.batch.media_organizer_planner import _check_scope, preview_semantic_unit
from app.batch.media_organizer_stage import (
    StagingConflict, _authority, _check_identity, _read_marker, _write_marker,
)
from app.batch.media_organizer_publish import (
    PublishingConflict, _PUBLIC_OWNER, _PUBLIC_COMPLETE,
    _check_unit, _entry, _inspect_existing_group, _validate_shape,
)

_RETIRE = ".nfc-retirement-authority"
_STAGE_OWNER = ".nfc-stage-authority"
_STAGE_COMPLETE = ".nfc-stage-complete"


class RetirementConflict(ValueError):
    """The published outputs or retained stage cannot safely be retired."""


def _verify_public(unit: Path, manifest: dict, rows: list[dict],
                   groups: dict[str, list[dict]], witness: bytes,
                   *, require_witness: bool) -> None:
    for name, group_rows in groups.items():
        directory = unit / name
        if not os.path.lexists(directory):
            raise RetirementConflict("missing public group")
        complete = _inspect_existing_group(
            directory, group_rows, witness, require_owner=require_witness,
        )
        if require_witness and not complete:
            raise RetirementConflict("public group completion witness missing")
    for row in rows:
        target = Path(row["final"])
        fd = _open_directory_nofollow(target.parent)
        try:
            info = _entry(fd, target.name)
            _check_identity(info, row["identity"], target)
        finally:
            os.close(fd)


def _stage_entries(stage_fd: int, stage: Path, rows: list[dict],
                   witness: bytes, *, retirement_started: bool) -> int:
    expected = {Path(row["target"]).name: row for row in rows}
    if len(expected) != len(rows):
        raise RetirementConflict("duplicate frozen staged filenames")
    allowable = set(expected) | {_STAGE_OWNER, _STAGE_COMPLETE, _RETIRE}
    seen = set()
    with os.scandir(stage_fd) as entries:
        for entry in entries:
            if entry.name not in allowable:
                raise RetirementConflict("foreign stage entry blocks retirement")
            seen.add(entry.name)
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise RetirementConflict("special file in staged retirement")
            if entry.name in expected:
                _check_identity(info, expected[entry.name]["identity"], stage / entry.name)
    if not retirement_started and not set(expected).issubset(seen):
        raise RetirementConflict("staged file missing without retirement authority")
    return sum(name in seen for name in expected)


def _retire_stage_link(row: dict, stage_fd: int, *,
                       witness: bytes, lease_fence: Callable[[], None]) -> bool:
    """Unlink only a frozen stage inode that has an exact, verified public link."""
    stage_name = Path(row["target"]).name
    public = Path(row["final"])
    public_fd = _open_directory_nofollow(public.parent)
    try:
        _check_identity(_entry(public_fd, public.name), row["identity"], public)
        existing = _entry(stage_fd, stage_name)
        if existing is None:
            return False
        _check_identity(existing, row["identity"], Path(row["target"]))
        lease_fence()
        _check_identity(_entry(public_fd, public.name), row["identity"], public)
        _check_identity(_entry(stage_fd, stage_name), row["identity"],
                        Path(row["target"]))
        os.unlink(stage_name, dir_fd=stage_fd)
        os.fsync(stage_fd)
        return True
    finally:
        os.close(public_fd)


def _unlink_witness(fd: int, name: str, witness: bytes,
                    fence: Callable[[], None]) -> bool:
    if not _read_marker(fd, name, witness):
        return False
    fence()
    if not _read_marker(fd, name, witness):
        raise RetirementConflict("custody witness disappeared")
    os.unlink(name, dir_fd=fd)
    os.fsync(fd)
    return True



def _retirement_receipt_path(manifest_path: Path) -> Path:
    return Path(manifest_path).with_name(Path(manifest_path).name + ".retirement-receipt.json")


def _receipt_data(manifest: dict, stage_stat: os.stat_result) -> dict:
    return {
        "schema_version": 1,
        "job_id": manifest["job_id"],
        "unit": manifest["unit"],
        "stage_directory": manifest["stage_directory"],
        "stage_dev": int(stage_stat.st_dev),
        "stage_ino": int(stage_stat.st_ino),
        "manifest_checksum": _checksum(manifest),
        "files": len(manifest["moves"]),
    }


def _receipt_digest(data: dict) -> str:
    content = json.dumps(data, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _read_retirement_receipt(path: Path, manifest: dict,
                             stage_stat: os.stat_result) -> None:
    """An unwitnessed EMPTY stage requires independent durable private proof."""
    expected = _receipt_data(manifest, stage_stat)
    directory_fd = _open_directory_nofollow(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or
                    (info.st_mode & 0o077) != 0 or
                    info.st_size > 4096 or info.st_size == 0):
                raise RetirementConflict("invalid private retirement receipt attributes")
            raw = stream.read(4097)
    except (OSError, ValueError) as exc:
        raise RetirementConflict("retirement receipt missing or inaccessible") from exc
    finally:
        os.close(directory_fd)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RetirementConflict("retirement receipt data is invalid") from exc
    if (not isinstance(payload, dict)
            or payload.get("record") != expected
            or payload.get("sha256") != _receipt_digest(expected)):
        raise RetirementConflict("retirement receipt checksum or stage identity changed")


def _write_retirement_receipt(path: Path, manifest: dict,
                              stage_stat: os.stat_result) -> None:
    """Durably commit outside the stage BEFORE its last internal marker goes."""
    expected = _receipt_data(manifest, stage_stat)
    encoded = json.dumps(
        {"record": expected, "sha256": _receipt_digest(expected)},
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    fd = _open_directory_nofollow(path.parent)
    try:
        try:
            target_fd = os.open(
                path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                os.O_NOFOLLOW, 0o600, dir_fd=fd,
            )
        except FileExistsError:
            _read_retirement_receipt(path, manifest, stage_stat)
            return
        with os.fdopen(target_fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(fd)
    finally:
        os.close(fd)


def _rmdir_bound_empty_stage(unit: Path, stage: Path, manifest: dict,
                              stage_stat: os.stat_result,
                              fence: Callable[[], None]) -> None:
    root_fd = _open_directory_nofollow(unit)
    try:
        binding = _entry(root_fd, stage.name)
        if (binding is None or not stat.S_ISDIR(binding.st_mode)
                or [int(binding.st_dev), int(binding.st_ino)]
                != [int(stage_stat.st_dev), int(stage_stat.st_ino)]):
            raise RetirementConflict("retired stage binding replaced")
        _check_unit(unit, manifest, fence)
        os.rmdir(stage.name, dir_fd=root_fd)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


def _retire_stage_directory(unit: Path, stage: Path, manifest: dict, rows: list[dict],
                            witness: bytes, fence: Callable[[], None],
                            resume: bool) -> tuple[int, int]:
    stage_fd = _open_directory_nofollow(stage)
    try:
        if int(os.fstat(stage_fd).st_dev) != manifest["unit_dev"]:
            raise RetirementConflict("staging mount changed")
        started = _read_marker(stage_fd, _RETIRE, witness)
        owner = _read_marker(stage_fd, _STAGE_OWNER, witness)
        complete = _read_marker(stage_fd, _STAGE_COMPLETE, witness)
        if not started and (not owner or not complete):
            raise RetirementConflict("staging ownership or completion witness missing")
        if started and not resume:
            raise RetirementConflict("retirement already started; explicit recovery required")
        if started and not owner and not resume:
            raise RetirementConflict("stage owner missing without recovery permission")
        found = _stage_entries(stage_fd, stage, rows, witness,
                               retirement_started=started)
        if not started:
            _check_unit(unit, manifest, fence)
            _write_marker(stage_fd, _RETIRE, witness)
        retired = reconciled = 0
        for row in rows:
            _check_unit(unit, manifest, fence)
            if _retire_stage_link(row, stage_fd, witness=witness, lease_fence=fence):
                retired += 1
            else:
                reconciled += 1
        # Keep the durable retirement authority until every staged payload
        # hardlink has been proven absent.
        _stage_entries(stage_fd, stage, rows, witness, retirement_started=True)
        if any(_entry(stage_fd, Path(row["target"]).name) is not None for row in rows):
            raise RetirementConflict("some staged hardlinks remain")
        for name in (_STAGE_COMPLETE, _STAGE_OWNER, _RETIRE):
            _unlink_witness(stage_fd, name, witness, fence)
        with os.scandir(stage_fd) as entries:
            if next(entries, None) is not None:
                raise RetirementConflict("foreign staged entry after marker cleanup")
        stage_stat = os.fstat(stage_fd)
    finally:
        os.close(stage_fd)
    root_fd = _open_directory_nofollow(unit)
    try:
        binding = _entry(root_fd, stage.name)
        if (binding is None or not stat.S_ISDIR(binding.st_mode)
                or [int(binding.st_dev), int(binding.st_ino)]
                != [int(stage_stat.st_dev), int(stage_stat.st_ino)]):
            raise RetirementConflict("retired stage binding replaced")
        _check_unit(unit, manifest, fence)
        os.rmdir(stage.name, dir_fd=root_fd)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    return retired, reconciled


def _remove_public_witnesses(unit: Path, manifest: dict,
                             groups: dict[str, list[dict]], witness: bytes,
                             fence: Callable[[], None]) -> None:
    for name, rows in groups.items():
        folder = unit / name
        fd = _open_directory_nofollow(folder)
        try:
            for row in rows:
                target = Path(row["final"])
                _check_identity(_entry(fd, target.name), row["identity"], target)
            for marker in (_PUBLIC_COMPLETE, _PUBLIC_OWNER):
                _unlink_witness(fd, marker, witness, fence)
        finally:
            os.close(fd)


def retire_published_stage(
    manifest: dict, *, frozen_manifest_path: Path, allowed_roots: list[Path],
    lease_fence: Callable[[], None], quarantine_root: Path | None = None,
    resume: bool = False,
) -> dict:
    """Retire only exact staged hardlinks after checking all frozen public files.

    This function refuses unknown files and incomplete publishing. A crash
    during the last marker/directory removal may require manual recovery; it
    never authorizes deleting an unknown or non-empty directory.
    """
    if not callable(lease_fence):
        raise RetirementConflict("active lease fence required")
    try:
        if not isinstance(manifest, dict):
            raise RetirementConflict("invalid frozen manifest")
        unit = Path(manifest.get("unit", ""))
        approved = load_frozen_preview_manifest(
            Path(frozen_manifest_path), job_id=manifest["job_id"], unit=unit,
        )
        if approved != manifest:
            raise RetirementConflict("frozen manifest changed")
        _check_scope(unit, [Path(p) for p in allowed_roots],
                     Path(quarantine_root) if quarantine_root is not None else None)
        _check_unit(unit, manifest, lease_fence)
        rows, groups = _validate_shape(manifest, unit)
        stage = unit / manifest["stage_directory"]
        has_stage = os.path.lexists(stage)
        witness = _authority(manifest)
        _verify_public(unit, manifest, rows, groups, witness,
                       require_witness=has_stage)
        if has_stage:
            retired, reconciled = _retire_stage_directory(
                unit, stage, manifest, rows, witness, lease_fence, resume,
            )
        else:
            if not resume:
                raise RetirementConflict("stage already retired; use explicit resume")
            retired, reconciled = 0, len(rows)
        _verify_public(unit, manifest, rows, groups, witness,
                       require_witness=False)
        _remove_public_witnesses(unit, manifest, groups, witness, lease_fence)
        status = preview_semantic_unit(
            unit, allowed_roots=[Path(p) for p in allowed_roots],
            quarantine_root=quarantine_root,
            exclude_dir_names=manifest.get("excluded_dir_names", []),
        )
        if status.get("status") != "already_organized" or status.get("needed_moves") != 0:
            raise RetirementConflict("final canonical rescan did not produce zero changes")
        return {
            "unit": str(unit), "finalized": True, "file_count": len(rows),
            "retired_stage_links": retired,
            "reconciled_stage_links": reconciled,
            "ready_for_new_scan": True,
        }
    except (StagingConflict, PublishingConflict, FrozenPreviewError,
            OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, RetirementConflict):
            raise
        raise RetirementConflict(f"unsafe retirement; preserve evidence: {exc}") from exc
