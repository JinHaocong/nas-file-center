"""Frozen, checksummed read-only semantic organizer plan authority.

A preview is NOT authority for filesystem mutation. The caller must rescan
and validate the source fingerprint, every group, and every path before
writing an immutable plan artifact. No source file operation occurs here.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_planner import preview_semantic_unit, _normalized_excluded_dir_names

MANIFEST_VERSION = 1
MAX_MANIFEST_BYTES = 256 * 1024 * 1024


class FrozenPreviewError(ValueError):
    """Preview is stale or artifact custody cannot be established."""


def build_frozen_preview_manifest(
    unit: Path, *, preview_record: dict, allowed_roots: list[Path],
    job_id: int, quarantine_root: Path | None = None,
    exclude_dir_names: list[str] | None = None,
) -> dict:
    """Build a deterministic full per-file manifest without moving any file."""
    unit = Path(unit)
    if not isinstance(job_id, int) or job_id < 1:
        raise FrozenPreviewError("invalid frozen job id")
    if (preview_record.get("status") != "ready"
            or preview_record.get("unit") != str(unit)):
        raise FrozenPreviewError("preview is not ready for freezing")
    names = sorted(_normalized_excluded_dir_names(exclude_dir_names))
    fresh = preview_semantic_unit(
        unit, allowed_roots=allowed_roots, quarantine_root=quarantine_root,
        exclude_dir_names=names,
    )
    expected_fields = ("status", "input_fingerprint", "operation", "groups",
                       "totals", "needed_moves", "renamed_count")
    if any(fresh.get(key) != preview_record.get(key) for key in expected_fields):
        raise FrozenPreviewError("organizing unit changed since preview")
    source = str(unit)
    stage = f".nfc-media-organizer-stage-{job_id}"
    planned = []
    sources = set()
    targets = set()
    files = fresh["items"]
    for index, item in enumerate(files, 1):
        src = Path(item["source"])
        dst = Path(item["target"])
        if not (src.is_relative_to(unit) and dst.is_relative_to(unit)
                and src != unit and dst != unit):
            raise FrozenPreviewError("planned path escaped organizing unit")
        if str(src) in sources or str(dst) in targets:
            raise FrozenPreviewError("duplicate file source or target")
        sources.add(str(src))
        targets.add(str(dst))
        if len(item["identity"]) != 4:
            raise FrozenPreviewError("source identity missing")
        planned.append({
            "source": str(src), "final": str(dst),
            "target_name": item["target_name"],
            "group": item["kind"],
            "identity": list(item["identity"]),
            # Keep existing staging-executor field names: target is the
            # private staged path; final is the reviewed public path.
            "target": str(unit / stage / f"{index:06d}{src.suffix}"),
        })
    if not planned:
        raise FrozenPreviewError("ready preview had no files")
    fd = _open_directory_nofollow(unit)
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise FrozenPreviewError("unit path is not a directory")
        base_dev, base_ino = int(st.st_dev), int(st.st_ino)
    finally:
        os.close(fd)
    if any(move["identity"][0] != base_dev for move in planned):
        raise FrozenPreviewError("cross-filesystem source identity")
    # Store the exact directory binding before moving any files. On publish,
    # only these source wrappers can be retired, and only while still empty.
    wrapper_identities = {}
    for literal in fresh.get("wrapper_cleanup", []):
        wrapper = Path(literal)
        if not wrapper.is_relative_to(unit) or wrapper == unit:
            raise FrozenPreviewError("classification wrapper escaped organizing unit")
        wrapper_fd = _open_directory_nofollow(wrapper)
        try:
            info = os.fstat(wrapper_fd)
            if not stat.S_ISDIR(info.st_mode) or int(info.st_dev) != base_dev:
                raise FrozenPreviewError("unsafe classification wrapper binding")
            wrapper_identities[str(wrapper)] = [int(info.st_dev), int(info.st_ino)]
        finally:
            os.close(wrapper_fd)
    # Correctly named buckets can still be source wrappers when another
    # media kind in the same unit requires changes. Capture those original
    # directory identities too; never adopt a same-named foreign folder.
    for group in fresh.get("groups", []):
        folder = Path(group["destination"])
        if str(folder) in wrapper_identities:
            continue
        if not any(Path(row["source"]).is_relative_to(folder) for row in files):
            continue
        folder_fd = _open_directory_nofollow(folder)
        try:
            info = os.fstat(folder_fd)
            if not stat.S_ISDIR(info.st_mode) or int(info.st_dev) != base_dev:
                raise FrozenPreviewError("unsafe already-named source group binding")
            wrapper_identities[str(folder)] = [int(info.st_dev), int(info.st_ino)]
        finally:
            os.close(folder_fd)
    return {
        "schema_version": MANIFEST_VERSION,
        "excluded_dir_names": names,
        "job_id": job_id,
        "unit": source,
        "unit_dev": base_dev,
        "unit_ino": base_ino,
        "stage_directory": stage,
        "input_fingerprint": fresh["input_fingerprint"],
        "operation": fresh["operation"],
        "groups": fresh["groups"],
        "moves": planned,
        "needed_moves": fresh["needed_moves"],
        "renamed_count": fresh["renamed_count"],
        "wrapper_cleanup": fresh["wrapper_cleanup"],
        "wrapper_identities": wrapper_identities,
    }


def _checksum(manifest: dict) -> str:
    serialized = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def save_frozen_preview_manifest(path: Path, manifest: dict) -> None:
    """Publish a checksum-protected 0600 plan without ever replacing one."""
    path = Path(path)
    if not path.is_absolute():
        raise FrozenPreviewError("manifest path must be absolute")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = _open_directory_nofollow(path.parent)
    tmpname = path.name + ".staging"
    body = json.dumps({"manifest": manifest, "checksum": _checksum(manifest)},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_MANIFEST_BYTES:
        os.close(fd)
        raise FrozenPreviewError("frozen manifest too large")
    try:
        if os.path.lexists(path) or os.path.lexists(path.with_name(tmpname)):
            raise FrozenPreviewError("frozen manifest already exists")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        file_fd = os.open(tmpname, flags, 0o600, dir_fd=fd)
        try:
            with os.fdopen(file_fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(tmpname, path.name, src_dir_fd=fd, dst_dir_fd=fd,
                    follow_symlinks=False)
            os.fsync(fd)
        finally:
            try:
                os.unlink(tmpname, dir_fd=fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(fd)


def load_frozen_preview_manifest(path: Path, *, job_id: int, unit: Path) -> dict:
    """Read frozen plan with no-follow file descriptor and verify checksum."""
    path = Path(path)
    try:
        fd = _open_directory_nofollow(path.parent)
        try:
            file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                st = os.fstat(file_fd)
                if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_MANIFEST_BYTES:
                    raise FrozenPreviewError("manifest is not a bounded regular file")
                with os.fdopen(file_fd, "r", encoding="utf-8") as stream:
                    file_fd = -1
                    body = json.load(stream)
            finally:
                if file_fd >= 0:
                    os.close(file_fd)
        finally:
            os.close(fd)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenPreviewError("frozen manifest unreadable or unsafe") from exc
    if (not isinstance(body, dict) or not isinstance(body.get("manifest"), dict)
            or not isinstance(body.get("checksum"), str)):
        raise FrozenPreviewError("frozen manifest checksum envelope invalid")
    manifest = body["manifest"]
    if body["checksum"] != _checksum(manifest):
        raise FrozenPreviewError("frozen manifest checksum mismatch")
    if (manifest.get("schema_version") != MANIFEST_VERSION
            or manifest.get("job_id") != job_id
            or manifest.get("unit") != str(unit)):
        raise FrozenPreviewError("frozen manifest authority mismatch")
    return manifest
