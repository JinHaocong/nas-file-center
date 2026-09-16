from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Sequence

from app.planning import recursive_protection
from app.planning.dedupe_engine import (
    directory_ancestors_to_scan_root,
    normalize_dedupe_path,
)


_RECURSIVE_SELECTION_MODE = "recursive_directory_balanced_by_bytes"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecursiveProtectionAuthorityError(ValueError):
    """Raised when persisted recursive-protection authority is malformed or unsafe."""


@dataclass(frozen=True)
class RecursiveProtectionAuthority:
    schema_version: int
    selection_mode: str
    scan_job_id: int
    scan_root_index: int
    scan_root_path: str
    source_path: str
    protected_ancestors: tuple[str, ...]
    group_provenance_id: str | int
    group_decision_fingerprint: str
    preview_source_snapshot_digest: str
    preview_db_lineage_digest: str
    scope_digest: str


def _fail(message: str) -> RecursiveProtectionAuthorityError:
    return RecursiveProtectionAuthorityError(message)


def _strict_non_negative_int(value: object, *, field: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise _fail(f"{field} must be a non-negative integer")
    return value


def _non_empty_string(value: object, *, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise _fail(f"{field} must be a non-empty string")
    return value


def _sha256_string(value: object, *, field: str) -> str:
    text = _non_empty_string(value, field=field)
    if _SHA256_RE.fullmatch(text) is None:
        raise _fail(f"{field} must be a lowercase SHA256 hex digest")
    return text


def _canonical_absolute_path(value: object, *, field: str) -> str:
    text = _non_empty_string(value, field=field)
    normalized = normalize_dedupe_path(text)
    if not text.startswith("/") or not normalized.startswith("/"):
        raise _fail(f"{field} must be an absolute path")
    if text != normalized:
        raise _fail(f"{field} must be lexically canonical")
    return text


def _is_contained(path: str, root: str) -> bool:
    normalized_path = normalize_dedupe_path(path)
    normalized_root = normalize_dedupe_path(root)
    if normalized_root == "/":
        return normalized_path.startswith("/")
    return normalized_path == normalized_root or normalized_path.startswith(normalized_root + "/")


def _normalize_allowed_roots(allowed_roots: Sequence[Path | str]) -> tuple[str, ...]:
    if not isinstance(allowed_roots, (list, tuple)) or not allowed_roots:
        raise _fail("allowed_roots must be a non-empty sequence")

    normalized: list[str] = []
    for index, root in enumerate(allowed_roots):
        root_text = str(root)
        root_norm = normalize_dedupe_path(root_text)
        if not root_text.startswith("/") or not root_norm.startswith("/"):
            raise _fail(f"allowed_roots[{index}] must be absolute")
        normalized.append(root_norm)
    return tuple(normalized)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_recursive_protection_authority(
    metadata_json: str,
    *,
    expected_source_path: str,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str | None,
) -> RecursiveProtectionAuthority | None:
    """Parse and reconstruct immutable Gate6-B recursive Last-File authority.

    This is intentionally a pure lexical/parser layer. It does not inspect or mutate
    the filesystem. Descriptor-bound live sampling belongs to the shared recursive
    protection reader used by Freeze, Validate, and Execute preflight.
    """

    if type(metadata_json) is not str:
        raise _fail("metadata_json must be a JSON string")
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise _fail("metadata_json is not valid JSON") from exc
    if not isinstance(metadata, dict):
        raise _fail("metadata_json must decode to an object")

    raw_authority = metadata.get("recursive_protection")
    if raw_authority is None:
        return None
    if not isinstance(raw_authority, dict):
        raise _fail("recursive_protection must be an object")

    schema_version = raw_authority.get("schema_version")
    if schema_version != 1 or isinstance(schema_version, bool):
        raise _fail("recursive_protection.schema_version must equal 1")

    selection_mode = raw_authority.get("selection_mode")
    if selection_mode != _RECURSIVE_SELECTION_MODE:
        raise _fail("recursive_protection.selection_mode is invalid")

    scan_job_id = _strict_non_negative_int(
        raw_authority.get("scan_job_id"),
        field="recursive_protection.scan_job_id",
    )
    scan_root_index = _strict_non_negative_int(
        raw_authority.get("scan_root_index"),
        field="recursive_protection.scan_root_index",
    )
    scan_root_path = _canonical_absolute_path(
        raw_authority.get("scan_root_path"),
        field="recursive_protection.scan_root_path",
    )
    source_path = _canonical_absolute_path(
        raw_authority.get("source_path"),
        field="recursive_protection.source_path",
    )

    if type(expected_source_path) is not str or source_path != expected_source_path:
        raise _fail("recursive_protection.source_path does not match BatchPlanItem.source_path")

    raw_ancestors = raw_authority.get("protected_ancestors")
    if not isinstance(raw_ancestors, (list, tuple)) or not raw_ancestors:
        raise _fail("recursive_protection.protected_ancestors must be a non-empty sequence")
    ancestors = tuple(
        _canonical_absolute_path(
            value,
            field=f"recursive_protection.protected_ancestors[{index}]",
        )
        for index, value in enumerate(raw_ancestors)
    )
    if len(set(ancestors)) != len(ancestors):
        raise _fail("recursive_protection.protected_ancestors contains duplicates")

    try:
        expected_ancestors = directory_ancestors_to_scan_root(source_path, scan_root_path)
    except ValueError as exc:
        raise _fail("recursive_protection source/root ancestry is invalid") from exc
    if ancestors != expected_ancestors:
        raise _fail("recursive_protection.protected_ancestors does not match exact source ancestry")

    group_provenance_id = raw_authority.get("group_provenance_id")
    if type(group_provenance_id) is str:
        if not group_provenance_id.strip():
            raise _fail("recursive_protection.group_provenance_id must not be blank")
    elif type(group_provenance_id) is int and not isinstance(group_provenance_id, bool):
        if group_provenance_id < 0:
            raise _fail("recursive_protection.group_provenance_id integer must be non-negative")
    else:
        raise _fail("recursive_protection.group_provenance_id must be a string or integer")

    group_decision_fingerprint = _sha256_string(
        raw_authority.get("group_decision_fingerprint"),
        field="recursive_protection.group_decision_fingerprint",
    )
    preview_source_snapshot_digest = _sha256_string(
        raw_authority.get("preview_source_snapshot_digest"),
        field="recursive_protection.preview_source_snapshot_digest",
    )
    preview_db_lineage_digest = _sha256_string(
        raw_authority.get("preview_db_lineage_digest"),
        field="recursive_protection.preview_db_lineage_digest",
    )

    roots = _normalize_allowed_roots(allowed_roots)
    scoped_paths = (scan_root_path, source_path, *ancestors)
    for path in scoped_paths:
        if not any(_is_contained(path, root) for root in roots):
            raise _fail("recursive protection scope escaped configured allowed roots")

    if quarantine_root is not None:
        quarantine_text = str(quarantine_root)
        quarantine_norm = normalize_dedupe_path(quarantine_text)
        if not quarantine_text.startswith("/") or not quarantine_norm.startswith("/"):
            raise _fail("quarantine_root must be absolute")
        if any(_is_contained(path, quarantine_norm) for path in scoped_paths):
            raise _fail("recursive protection scope entered reserved quarantine storage")

    scope_payload = {
        "schema_version": 1,
        "selection_mode": selection_mode,
        "scan_job_id": scan_job_id,
        "scan_root_index": scan_root_index,
        "scan_root_path": scan_root_path,
        "source_path": source_path,
        "protected_ancestors": list(ancestors),
        "group_provenance_id": group_provenance_id,
        "group_decision_fingerprint": group_decision_fingerprint,
        "preview_source_snapshot_digest": preview_source_snapshot_digest,
        "preview_db_lineage_digest": preview_db_lineage_digest,
    }
    scope_digest = hashlib.sha256(_canonical_json(scope_payload).encode("utf-8")).hexdigest()

    return RecursiveProtectionAuthority(
        schema_version=1,
        selection_mode=selection_mode,
        scan_job_id=scan_job_id,
        scan_root_index=scan_root_index,
        scan_root_path=scan_root_path,
        source_path=source_path,
        protected_ancestors=ancestors,
        group_provenance_id=group_provenance_id,
        group_decision_fingerprint=group_decision_fingerprint,
        preview_source_snapshot_digest=preview_source_snapshot_digest,
        preview_db_lineage_digest=preview_db_lineage_digest,
        scope_digest=scope_digest,
    )


def build_frozen_recursive_protection(
    metadata_json: str,
    *,
    expected_source_path: str,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str | None,
) -> dict[str, object] | None:
    """Parse authority and capture Freeze-time live samples for every exact ancestor.

    The samples are audit/evidence for the frozen authority. They are not the later
    Validate/Execute mutation authority required by Architecture Amendment A.
    """

    authority = parse_recursive_protection_authority(
        metadata_json,
        expected_source_path=expected_source_path,
        allowed_roots=allowed_roots,
        quarantine_root=quarantine_root,
    )
    if authority is None:
        return None

    frozen_ancestors: dict[str, dict[str, object]] = {}
    for ancestor in authority.protected_ancestors:
        sample = recursive_protection.snapshot_recursive_regular_files(ancestor)
        if (
            not sample.stable
            or sample.device is None
            or sample.inode is None
            or not sample.tree_identity_digest
        ):
            raise _fail(f"RECURSIVE_PROTECTION_UNSTABLE: {ancestor}")
        if sample.count - 1 < 1:
            raise _fail(f"RECURSIVE_PROTECT_LAST_FILE: {ancestor}")

        frozen_ancestors[ancestor] = {
            "count": int(sample.count),
            "device": int(sample.device),
            "inode": int(sample.inode),
            "tree_identity_digest": str(sample.tree_identity_digest),
        }

    return {
        "schema_version": 1,
        "scope_digest": authority.scope_digest,
        "frozen_ancestors": frozen_ancestors,
    }
