"""Pure frozen-path roles for separately confirmed, deferred media relayout.

These classifications describe the immutable plan. They grant no filesystem
authority and never inspect, resolve, or modify the current namespace.
"""
from __future__ import annotations

from pathlib import Path


POLICY = "confirmed_relayout_v1"


class PathRoleConflict(ValueError):
    """The frozen path roles or their explicit policy are not trustworthy."""


def uses_path_roles(manifest: dict) -> bool:
    """Keep policy-free manifests legacy; reject unrecognized opt-ins."""
    if not isinstance(manifest, dict):
        raise PathRoleConflict("frozen path-role manifest must be an object")
    if "path_role_policy" not in manifest:
        return False
    if (manifest["path_role_policy"] != POLICY
            or manifest.get("cleanup_policy") != "deferred"):
        raise PathRoleConflict("unsupported or non-deferred frozen path-role policy")
    return True


def _absolute_path(value, *, unit: Path | None = None) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise PathRoleConflict("frozen path must be an absolute string")
    path = Path(value)
    if (not path.is_absolute() or str(path) != value or ".." in path.parts
            or value.startswith("//")):
        raise PathRoleConflict("frozen path must be canonical and absolute")
    if unit is not None and (path == unit or not path.is_relative_to(unit)):
        raise PathRoleConflict("frozen path escaped organizing unit")
    return path


def _identity(value, *, length: int, device: int) -> None:
    if (not isinstance(value, list) or len(value) != length
            or any(type(part) is not int for part in value)
            or value[0] != device or value[1] <= 0
            or (length == 4 and value[2] < 0)):
        raise PathRoleConflict("invalid frozen path identity")


def classify_path_roles(manifest: dict) -> dict:
    """Partition original names and identify deferred publications, read-only.

    Classification does not require policy opt-in: a new execution can inspect
    these roles before freezing that explicit policy. Row lists preserve both
    manifest order and the original row objects. Source spellings remain exact
    identities, while final-name collision checks deliberately use casefold.
    """
    if not isinstance(manifest, dict):
        raise PathRoleConflict("frozen path-role manifest must be an object")
    unit = _absolute_path(manifest.get("unit"))
    device = manifest.get("unit_dev")
    if type(device) is not int or device < 0:
        raise PathRoleConflict("invalid frozen organizing-unit device")
    stage_name = manifest.get("stage_directory")
    if (not isinstance(stage_name, str) or not stage_name
            or Path(stage_name).name != stage_name or stage_name in (".", "..")
            or "\0" in stage_name):
        raise PathRoleConflict("invalid frozen stage directory")
    stage = unit / stage_name
    rows = manifest.get("moves")
    wrappers = manifest.get("wrapper_identities")
    groups = manifest.get("groups")
    if (not isinstance(rows, list) or not rows or not isinstance(wrappers, dict)
            or not isinstance(groups, list)):
        raise PathRoleConflict("invalid frozen source, wrapper or group inventory")

    source_names: set[str] = set()
    final_names: set[str] = set()
    staged_names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PathRoleConflict("invalid frozen source row")
        source, target, final = (
            _absolute_path(row.get(field), unit=unit)
            for field in ("source", "target", "final")
        )
        if (target.parent != stage or source.is_relative_to(stage)
                or final.is_relative_to(stage)
                or row.get("target_name") != final.name
                or row.get("group") not in ("P", "V", "Other")):
            raise PathRoleConflict("invalid frozen stage or public path binding")
        if (str(source) in source_names or str(final).casefold() in final_names
                or str(target) in staged_names):
            raise PathRoleConflict("duplicate frozen source, final or staged path")
        _identity(row.get("identity"), length=4, device=device)
        source_names.add(str(source))
        final_names.add(str(final).casefold())
        staged_names.add(str(target))

    for literal, identity in wrappers.items():
        wrapper = _absolute_path(literal, unit=unit)
        if wrapper.is_relative_to(stage) or literal in source_names:
            raise PathRoleConflict("invalid frozen wrapper path binding")
        _identity(identity, length=2, device=device)
    destinations: set[str] = set()
    group_names: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise PathRoleConflict("invalid frozen public group")
        name = group.get("name")
        if (not isinstance(name, str) or not name or Path(name).name != name
                or name in (".", "..") or "\0" in name
                or name.casefold() in group_names):
            raise PathRoleConflict("invalid or duplicate frozen public group name")
        destination = _absolute_path(group.get("destination"), unit=unit)
        if destination != unit / name or destination == stage:
            raise PathRoleConflict("frozen public group escaped its exact target")
        destinations.add(str(destination))
        group_names.add(name.casefold())

    source_folds = {source.casefold() for source in source_names}
    retained = [row for row in rows if row["source"] == row["final"]]
    deferred = [row for row in rows if row["source"] != row["final"]
                and row["final"].casefold() in source_folds]
    deferred_folds = {row["final"].casefold() for row in deferred}
    released = [row for row in rows if row["source"].casefold() in deferred_folds]
    ordinary = [row for row in rows if row["source"] != row["final"]
                and row["source"].casefold() not in deferred_folds]
    return {
        "retained_sources": retained,
        "deferred_rows": deferred,
        "released_sources": released,
        "ordinary_sources": ordinary,
        "retained_groups": {path: identity for path, identity in wrappers.items()
                            if path in destinations},
        "removed_wrappers": {path: identity for path, identity in wrappers.items()
                             if path not in destinations},
    }


def cleanup_plan_path_role_fields(manifest: dict) -> dict:
    """Derive exact schema-2 plan lists without consulting live stage inodes."""
    roles = classify_path_roles(manifest)

    def original(row: dict) -> dict:
        return {"path": row["source"], "identity": list(row["identity"]),
                "published_path": row["final"]}

    def directories(bindings: dict) -> list[dict]:
        return [{"path": path, "identity": list(identity)}
                for path, identity in sorted(
                    bindings.items(), key=lambda pair: (-len(Path(pair[0]).parts), pair[0]),
                )]

    return {
        "original_links": [original(row) for row in manifest["moves"]
                           if row["source"] != row["final"]],
        "staged_links": [{"path": row["target"], "identity": list(row["identity"]),
                          "published_path": row["final"]} for row in manifest["moves"]],
        "wrapper_directories": directories(roles["removed_wrappers"]),
        "retained_original_links": [original(row) for row in roles["retained_sources"]],
        "retained_wrapper_directories": directories(roles["retained_groups"]),
        "deferred_publications": [{"path": row["final"], "stage_path": row["target"],
                                   "identity": list(row["identity"]),
                                   "source_path": row["source"]}
                                  for row in roles["deferred_rows"]],
        "released_original_links": [{**original(row), "stage_path": row["target"]}
                                    for row in roles["released_sources"]],
    }
