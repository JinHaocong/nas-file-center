from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable

from app.path_safety import is_path_allowed, require_allowed_path, UnsafePathError


@dataclass(frozen=True)
class StaleItemDetail:
    item_id: int
    source_path: str
    reason: str
    expected: dict[str, Any]
    actual: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source_path": self.source_path,
            "reason": self.reason,
            "expected": self.expected,
            "actual": self.actual,
        }


def capture_source_snapshot(
    path: Path | str,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None = None,
) -> dict[str, Any]:
    """
    Safely inspect and capture filesystem identity snapshot for a given source path.
    Raises ValueError or UnsafePathError if path is unsafe or does not exist.
    """
    p = Path(path)
    if p.is_symlink() or os.path.islink(p):
        raise ValueError(f"Source path is a symlink: {path}")

    roots = list(allowed_roots)
    if quarantine_root:
        roots.append(Path(quarantine_root))
    require_allowed_path(p, roots)

    st = os.lstat(p)
    obj_type = "directory" if stat.S_ISDIR(st.st_mode) else "file"
    mtime_ns = int(getattr(st, "st_mtime_ns", st.st_mtime * 1e9))
    ctime_ns = int(getattr(st, "st_ctime_ns", st.st_ctime * 1e9))

    return {
        "device": int(st.st_dev),
        "inode": int(st.st_ino),
        "size": int(st.st_size),
        "mtime_ns": mtime_ns,
        "ctime_ns": ctime_ns,
        "object_type": obj_type,
    }


def resolve_origin_path(
    path: Path,
    planned_producers: list[dict[str, Any]],
) -> tuple[Path | None, dict[str, Any] | None]:
    """
    Resolve a planned or chained path backwards through planned producers
    until an origin path that exists on disk at freeze time is found.
    Returns (matched_origin_path, direct_producer_dict).
    """
    curr = path
    direct_producer = None
    max_hops = 100
    hops = 0

    while hops < max_hops:
        hops += 1
        found_step = False
        for p in reversed(planned_producers):
            p_tgt = p["target_path"]
            try:
                if curr == p_tgt:
                    if direct_producer is None:
                        direct_producer = p
                    curr = p["origin_path"]
                    found_step = True
                    break
                elif curr.is_relative_to(p_tgt):
                    if direct_producer is None:
                        direct_producer = p
                    rel = curr.relative_to(p_tgt)
                    curr = p["origin_path"] / rel
                    found_step = True
                    break
            except Exception:
                pass

        if not found_step:
            break

        if curr.exists():
            return curr, direct_producer

    if curr.exists():
        return curr, direct_producer

    return None, direct_producer


def verify_item_freshness(
    *,
    item_id: int,
    source_path: str,
    operation: str = "",
    expected_device: int = 0,
    expected_inode: int = 0,
    expected_size: int = 0,
    expected_mtime_ns: int = 0,
    expected_hash: str | None = None,
    metadata_json: str | None = None,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None = None,
    check_hash: bool = True,
    allow_deferred_chained_missing: bool = False,
) -> tuple[bool, StaleItemDetail | None]:
    """
    Verify if a plan item's target file on disk matches its frozen snapshot.
    Returns (True, None) if fresh, or (False, StaleItemDetail) if stale.
    MUST be run outside SQLite write transactions.
    """
    if operation == "restore":
        return True, None

    p = Path(source_path)

    meta: dict[str, Any] = {}
    if metadata_json:
        try:
            meta = json.loads(metadata_json)
        except Exception:
            meta = {}

    # Gate6-A2 has its own stronger pathname-scoped freshness authority. Once a
    # frozen unlink_v1 manifest is bound to the selected entry, the public view
    # may legitimately disappear before a restarted worker reaches generic
    # preflight. The journaled unlink engine revalidates the exact frozen
    # manifest and per-path durable intent before any further mutation.
    if operation == "quarantine_unlink_purge":
        raw_qid = meta.get("quarantine_entry_id")
        manifest = meta.get("unlink_manifest")
        if (
            isinstance(raw_qid, int)
            and not isinstance(raw_qid, bool)
            and raw_qid > 0
            and meta.get("purge_semantics") == "unlink_v1"
            and isinstance(manifest, dict)
            and manifest.get("purge_semantics") == "unlink_v1"
            and manifest.get("selected_entry_id") == raw_qid
            and manifest.get("blockers") == []
        ):
            return True, None

    # Gate6-A purge recovery authority transfers to the transactional purge
    # engine only after Worker Phase-1 intent has been durably persisted.  At
    # that point the original source path may legitimately be absent because it
    # has already been captured into the exclusive purge generation.  The purge
    # engine revalidates the frozen manifest, generation, private slots, payload
    # identity/hash, and worker lease before any further destructive mutation.
    if operation == "quarantine_purge":
        execution = meta.get("execution")
        if (
            isinstance(execution, dict)
            and execution.get("phase") == "intent"
            and meta.get("quarantine_entry_id")
            and isinstance(meta.get("purge_topology_manifest"), dict)
        ):
            return True, None

    snapshot: dict[str, Any] = meta.get("snapshot", {})
    is_chained = bool(meta.get("chained_target"))

    expected_dict: dict[str, Any] = {
        "device": expected_device or snapshot.get("device", 0),
        "inode": expected_inode or snapshot.get("inode", 0),
        "size": snapshot.get("size") if "size" in snapshot else (expected_size or 0),
        "mtime_ns": (snapshot.get("mtime_ns", 0) if operation == "touch" else (expected_mtime_ns or snapshot.get("mtime_ns", 0))),
    }
    if snapshot.get("object_type"):
        expected_dict["object_type"] = snapshot["object_type"]
    if expected_hash:
        expected_dict["hash"] = expected_hash

    roots = list(allowed_roots)
    if quarantine_root:
        roots.append(Path(quarantine_root))

    # Gate6-B Single-Child Wrapper Collapse compiles MOVE with an explicit target
    # that must remain absent from Preview/Generate through Validate and the
    # Execute preflight.  This is intentionally scoped to the Utility action so
    # historical file/organizer MOVE semantics remain unchanged.  The executor
    # still uses RENAME_NOREPLACE as the final race-safe no-overwrite fence.
    if operation == "move" and meta.get("utility_action") == "single_child_wrapper_collapse":
        raw_target = meta.get("target_path")
        expected_dict["target_must_be_absent"] = True
        if not isinstance(raw_target, str) or not raw_target.strip():
            return False, StaleItemDetail(
                item_id=item_id,
                source_path=source_path,
                reason="target_binding_missing",
                expected=expected_dict,
                actual=None,
            )

        target = Path(raw_target)
        expected_dict["target_path"] = str(target)

        if os.path.lexists(target):
            actual_target: dict[str, Any] = {
                "target_path": str(target),
                "exists": True,
            }
            try:
                target_st = os.lstat(target)
                if stat.S_ISLNK(target_st.st_mode):
                    target_type = "symlink"
                elif stat.S_ISDIR(target_st.st_mode):
                    target_type = "directory"
                elif stat.S_ISREG(target_st.st_mode):
                    target_type = "file"
                else:
                    target_type = "special"
                actual_target.update({
                    "device": int(target_st.st_dev),
                    "inode": int(target_st.st_ino),
                    "object_type": target_type,
                })
            except OSError:
                pass
            return False, StaleItemDetail(
                item_id=item_id,
                source_path=source_path,
                reason="target_appeared",
                expected=expected_dict,
                actual=actual_target,
            )

        try:
            require_allowed_path(target, allowed_roots)
        except (UnsafePathError, OSError, ValueError):
            return False, StaleItemDetail(
                item_id=item_id,
                source_path=source_path,
                reason="target_path_unsafe",
                expected=expected_dict,
                actual={"target_path": str(target), "exists": False},
            )

    # 1. Symlink check
    if p.is_symlink() or os.path.islink(source_path):
        actual_dict = None
        try:
            st = os.lstat(source_path)
            actual_dict = {
                "device": int(st.st_dev),
                "inode": int(st.st_ino),
                "size": int(st.st_size),
                "mtime_ns": int(getattr(st, "st_mtime_ns", st.st_mtime * 1e9)),
                "object_type": "symlink",
            }
        except OSError:
            pass

        try:
            require_allowed_path(p, roots)
            reason = "symlink_replaced"
        except UnsafePathError:
            reason = "symlink_escape"
        except Exception:
            reason = "symlink_replaced"

        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason=reason,
            expected=expected_dict,
            actual=actual_dict,
        )

    # 2. Existence check
    if not os.path.lexists(source_path):
        if is_chained and allow_deferred_chained_missing:
            return True, None
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="source_not_found",
            expected=expected_dict,
            actual=None,
        )

    # 3. Stat check
    try:
        st = os.lstat(source_path)
    except OSError:
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="source_not_found",
            expected=expected_dict,
            actual=None,
        )

    actual_dev = int(st.st_dev)
    actual_ino = int(st.st_ino)
    actual_size = int(st.st_size)
    actual_mtime_ns = int(getattr(st, "st_mtime_ns", st.st_mtime * 1e9))
    actual_ctime_ns = int(getattr(st, "st_ctime_ns", st.st_ctime * 1e9))
    actual_obj_type = "directory" if stat.S_ISDIR(st.st_mode) else "file"

    actual_dict = {
        "device": actual_dev,
        "inode": actual_ino,
        "size": actual_size,
        "mtime_ns": actual_mtime_ns,
        "object_type": actual_obj_type,
    }

    # 4. PathGuard check
    try:
        require_allowed_path(p, roots)
    except UnsafePathError:
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="symlink_escape",
            expected=expected_dict,
            actual=actual_dict,
        )

    # 5. Object type check
    exp_obj_type = snapshot.get("object_type")
    if exp_obj_type and actual_obj_type != exp_obj_type:
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="filesystem_identity_changed",
            expected=expected_dict,
            actual=actual_dict,
        )

    # 6. Device & Inode identity check
    exp_dev = expected_dict.get("device")
    exp_ino = expected_dict.get("inode")
    if (exp_dev and actual_dev != exp_dev) or (exp_ino and actual_ino != exp_ino):
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="filesystem_identity_changed",
            expected=expected_dict,
            actual=actual_dict,
        )

    # 7. Size check
    exp_size = None
    if "size" in snapshot:
        exp_size = snapshot["size"]
    elif expected_size and expected_size > 0:
        exp_size = expected_size

    if exp_size is not None and not stat.S_ISDIR(st.st_mode) and actual_size != exp_size:
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="size_changed",
            expected=expected_dict,
            actual=actual_dict,
        )

    # 8. Mtime check (files only, directory mtimes change upon child mutations)
    exp_mtime_ns = expected_dict.get("mtime_ns")
    if exp_mtime_ns and not stat.S_ISDIR(st.st_mode) and actual_mtime_ns != exp_mtime_ns:
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="mtime_changed",
            expected=expected_dict,
            actual=actual_dict,
        )

    # 9. Hash check. ctime is deliberately excluded from the read-stability
    # authority: zfuse can advance ctime as a side effect of O_RDONLY reads.
    # dev/inode/size/mtime plus the frozen SHA256 remain authoritative.
    if check_hash and expected_hash and not stat.S_ISDIR(st.st_mode):
        try:
            st_before = os.lstat(source_path)
            h = hashlib.sha256()
            with open(source_path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    h.update(chunk)
            st_after = os.lstat(source_path)
            if (
                getattr(st_before, "st_dev", 0) != getattr(st_after, "st_dev", 0)
                or getattr(st_before, "st_ino", 0) != getattr(st_after, "st_ino", 0)
                or st_before.st_size != st_after.st_size
                or getattr(st_before, "st_mtime_ns", 0) != getattr(st_after, "st_mtime_ns", 0)
            ):
                return False, StaleItemDetail(
                    item_id=item_id,
                    source_path=source_path,
                    reason="hash_changed",
                    expected=expected_dict,
                    actual=actual_dict,
                )
            actual_hash = h.hexdigest()
            actual_dict["hash"] = actual_hash
            if actual_hash.lower() != expected_hash.lower():
                return False, StaleItemDetail(
                    item_id=item_id,
                    source_path=source_path,
                    reason="hash_changed",
                    expected=expected_dict,
                    actual=actual_dict,
                )
        except Exception:
            return False, StaleItemDetail(
                item_id=item_id,
                source_path=source_path,
                reason="hash_changed",
                expected=expected_dict,
                actual=actual_dict,
            )

    # 10. Ctime remains a stale guard only for regular-file items that do not
    # have an authoritative frozen SHA256.  Hashed regular files intentionally
    # ignore ctime because zfuse reads can advance it without content mutation.
    exp_ctime_ns = snapshot.get("ctime_ns")
    if (
        not expected_hash
        and not is_chained
        and exp_ctime_ns
        and not stat.S_ISDIR(st.st_mode)
        and actual_ctime_ns != exp_ctime_ns
    ):
        return False, StaleItemDetail(
            item_id=item_id,
            source_path=source_path,
            reason="ctime_changed",
            expected=expected_dict,
            actual=actual_dict,
        )

    return True, None
