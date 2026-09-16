from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib.util
import json
from pathlib import Path

import pytest

from app.planning.dedupe_engine import directory_ancestors_to_scan_root


MODULE_NAME = "app.planning.recursive_protection_authority"


def _api():
    module = pytest.importorskip(MODULE_NAME)
    return (
        module.RecursiveProtectionAuthority,
        module.RecursiveProtectionAuthorityError,
        module.parse_recursive_protection_authority,
    )


def _hex(char: str) -> str:
    return char * 64


def _valid_metadata(root: Path, source: Path) -> dict:
    return {
        "scan_job_id": 1201,
        "group_provenance_id": "group-provenance-1201",
        "group_decision_fingerprint": _hex("a"),
        "scan_root_index": 0,
        "scan_root_path": str(root),
        "recursive_protection": {
            "schema_version": 1,
            "selection_mode": "recursive_directory_balanced_by_bytes",
            "scan_job_id": 1201,
            "scan_root_index": 0,
            "scan_root_path": str(root),
            "source_path": str(source),
            "protected_ancestors": list(directory_ancestors_to_scan_root(str(source), str(root))),
            "group_provenance_id": "group-provenance-1201",
            "group_decision_fingerprint": _hex("a"),
            "preview_source_snapshot_digest": _hex("b"),
            "preview_db_lineage_digest": _hex("c"),
        },
    }


def _fixture_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "data"
    source = root / "A" / "deep" / "dup.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"dup")
    quarantine = root / ".nas-file-center-trash"
    quarantine.mkdir()
    return root, source, quarantine


def test_recursive_protection_authority_public_api_exists():
    assert importlib.util.find_spec(MODULE_NAME) is not None


def test_parse_valid_recursive_authority_is_immutable_and_reconstructed_exactly(tmp_path: Path):
    authority_type, _error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)
    metadata = _valid_metadata(root, source)

    authority = parse(
        json.dumps(metadata),
        expected_source_path=str(source),
        allowed_roots=[root],
        quarantine_root=quarantine,
    )

    assert isinstance(authority, authority_type)
    assert authority.schema_version == 1
    assert authority.selection_mode == "recursive_directory_balanced_by_bytes"
    assert authority.scan_job_id == 1201
    assert authority.scan_root_index == 0
    assert authority.scan_root_path == str(root)
    assert authority.source_path == str(source)
    assert authority.protected_ancestors == directory_ancestors_to_scan_root(str(source), str(root))
    assert authority.group_provenance_id == "group-provenance-1201"
    assert authority.group_decision_fingerprint == _hex("a")
    assert authority.preview_source_snapshot_digest == _hex("b")
    assert authority.preview_db_lineage_digest == _hex("c")
    assert len(authority.scope_digest) == 64
    assert all(char in "0123456789abcdef" for char in authority.scope_digest)

    with pytest.raises(FrozenInstanceError):
        authority.scan_root_index = 99


def test_non_recursive_item_without_authority_returns_none(tmp_path: Path):
    _authority_type, _error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)

    assert parse(
        json.dumps({"scan_job_id": 1202, "selection_mode": "weighted"}),
        expected_source_path=str(source),
        allowed_roots=[root],
        quarantine_root=quarantine,
    ) is None


@pytest.mark.parametrize(
    "mutator",
    [
        lambda a: a.update(schema_version=2),
        lambda a: a.update(selection_mode="balanced_by_bytes"),
        lambda a: a.update(source_path=""),
        lambda a: a.update(scan_root_path="relative/root"),
        lambda a: a.update(scan_root_index=-1),
        lambda a: a.update(scan_root_index=True),
        lambda a: a.update(protected_ancestors=[]),
        lambda a: a.update(protected_ancestors=[a["protected_ancestors"][0]] * 2),
        lambda a: a.update(group_provenance_id=""),
        lambda a: a.update(group_decision_fingerprint=""),
        lambda a: a.update(preview_source_snapshot_digest="not-a-sha256"),
        lambda a: a.update(preview_db_lineage_digest="not-a-sha256"),
    ],
)
def test_malformed_recursive_authority_fails_closed(tmp_path: Path, mutator):
    _authority_type, error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)
    metadata = _valid_metadata(root, source)
    mutator(metadata["recursive_protection"])

    with pytest.raises(error_type):
        parse(
            json.dumps(metadata),
            expected_source_path=str(source),
            allowed_roots=[root],
            quarantine_root=quarantine,
        )


def test_source_path_must_match_batch_plan_item_source(tmp_path: Path):
    _authority_type, error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)
    metadata = _valid_metadata(root, source)
    other = source.with_name("other.bin")
    other.write_bytes(b"other")

    with pytest.raises(error_type):
        parse(
            json.dumps(metadata),
            expected_source_path=str(other),
            allowed_roots=[root],
            quarantine_root=quarantine,
        )


@pytest.mark.parametrize("mode", ["broader", "narrower", "reordered"])
def test_protected_ancestors_must_exactly_match_frozen_ancestry(tmp_path: Path, mode: str):
    _authority_type, error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)
    metadata = _valid_metadata(root, source)
    ancestors = metadata["recursive_protection"]["protected_ancestors"]

    if mode == "broader":
        ancestors.append(str(root.parent))
    elif mode == "narrower":
        ancestors.pop()
    else:
        ancestors[0], ancestors[-1] = ancestors[-1], ancestors[0]

    with pytest.raises(error_type):
        parse(
            json.dumps(metadata),
            expected_source_path=str(source),
            allowed_roots=[root],
            quarantine_root=quarantine,
        )


def test_scope_must_remain_inside_allowed_roots(tmp_path: Path):
    _authority_type, error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)
    metadata = _valid_metadata(root, source)
    different_allowed_root = tmp_path / "other-root"
    different_allowed_root.mkdir()

    with pytest.raises(error_type):
        parse(
            json.dumps(metadata),
            expected_source_path=str(source),
            allowed_roots=[different_allowed_root],
            quarantine_root=quarantine,
        )


def test_scope_must_not_enter_reserved_quarantine_storage(tmp_path: Path):
    _authority_type, error_type, parse = _api()
    root = tmp_path / "data"
    quarantine = root / ".nas-file-center-trash"
    source = quarantine / "A" / "dup.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"dup")
    metadata = _valid_metadata(quarantine, source)

    with pytest.raises(error_type):
        parse(
            json.dumps(metadata),
            expected_source_path=str(source),
            allowed_roots=[root],
            quarantine_root=quarantine,
        )


def test_scope_digest_is_deterministic_and_ignores_non_authority_runtime_fields(tmp_path: Path):
    _authority_type, _error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)
    first_metadata = _valid_metadata(root, source)
    second_metadata = _valid_metadata(root, source)
    second_metadata["runtime_live_count"] = 999
    second_metadata["ctime_ns"] = 123456789

    first = parse(
        json.dumps(first_metadata),
        expected_source_path=str(source),
        allowed_roots=[root],
        quarantine_root=quarantine,
    )
    second = parse(
        json.dumps(second_metadata),
        expected_source_path=str(source),
        allowed_roots=[root],
        quarantine_root=quarantine,
    )

    assert first is not None and second is not None
    assert first.scope_digest == second.scope_digest


def test_scope_digest_changes_when_immutable_authority_changes(tmp_path: Path):
    _authority_type, _error_type, parse = _api()
    root, source, quarantine = _fixture_paths(tmp_path)
    first_metadata = _valid_metadata(root, source)
    second_metadata = _valid_metadata(root, source)
    second_metadata["recursive_protection"]["group_decision_fingerprint"] = _hex("d")

    first = parse(
        json.dumps(first_metadata),
        expected_source_path=str(source),
        allowed_roots=[root],
        quarantine_root=quarantine,
    )
    second = parse(
        json.dumps(second_metadata),
        expected_source_path=str(source),
        allowed_roots=[root],
        quarantine_root=quarantine,
    )

    assert first is not None and second is not None
    assert first.scope_digest != second.scope_digest
