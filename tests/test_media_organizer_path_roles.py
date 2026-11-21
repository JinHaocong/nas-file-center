"""Pure path-role classification for explicitly confirmed media relayout."""
from __future__ import annotations

from copy import deepcopy
import importlib
import importlib.util
import os
from pathlib import Path

import pytest


POLICY = "confirmed_relayout_v1"


def _module():
    name = "app.batch.media_organizer_path_roles"
    assert importlib.util.find_spec(name) is not None, "frozen path-role classifier is required"
    return importlib.import_module(name)


def _manifest(unit="/media/unit", pairs=None):
    unit = Path(unit)
    stage = ".nfc-media-organizer-stage-41"
    if pairs is None:
        pairs = [("keep.jpg", "keep.jpg"), ("a.jpg", "b.jpg"),
                 ("b.jpg", "a.jpg"), ("ordinary.png", "001.png")]
    rows = []
    for index, (source, final) in enumerate(pairs, 1):
        rows.append({
            "source": str(unit / source), "final": str(unit / final),
            "target": str(unit / stage / f"{index:06d}{Path(source).suffix}"),
            "target_name": Path(final).name, "group": "P",
            "identity": [7, 100 + index, 10 + index, 1000 + index],
        })
    return {
        "schema_version": 1, "job_id": 41, "unit": str(unit),
        "unit_dev": 7, "unit_ino": 80, "stage_directory": stage,
        "cleanup_policy": "deferred", "moves": rows, "groups": [],
        "wrapper_identities": {}, "wrapper_cleanup": [],
    }


def test_roles_keep_exact_self_and_separate_collision_sources_from_other_cleanup():
    manifest = _manifest()
    before = deepcopy(manifest)
    rows = manifest["moves"]

    result = _module().classify_path_roles(manifest)

    assert result == {"retained_sources": [rows[0]], "deferred_rows": rows[1:3],
                      "released_sources": rows[1:3], "ordinary_sources": [rows[3]],
                      "retained_groups": {}, "removed_wrappers": {}}
    assert result["retained_sources"][0] is rows[0]
    assert result["deferred_rows"][0] is rows[1]
    assert manifest == before


def test_publication_deferral_and_source_release_are_independent_roles():
    manifest = _manifest(pairs=[("a.jpg", "b.jpg"), ("b.jpg", "c.jpg"),
                                ("c.jpg", "free.jpg")])
    rows = manifest["moves"]

    result = _module().classify_path_roles(manifest)

    assert result["deferred_rows"] == rows[:2]
    assert result["released_sources"] == rows[1:]
    assert result["ordinary_sources"] == rows[:1]


def test_pure_plan_fields_record_retained_and_released_originals():
    fields = _module().cleanup_plan_path_role_fields(_manifest())

    assert fields["retained_original_links"] == [{
        "path": "/media/unit/keep.jpg", "identity": [7, 101, 11, 1001],
        "published_path": "/media/unit/keep.jpg",
    }]
    assert fields["deferred_publications"][0] == {
        "path": "/media/unit/b.jpg", "identity": [7, 102, 12, 1002],
        "source_path": "/media/unit/a.jpg",
        "stage_path": "/media/unit/.nfc-media-organizer-stage-41/000002.jpg",
    }
    assert fields["released_original_links"][0] == {
        "path": "/media/unit/a.jpg", "identity": [7, 102, 12, 1002],
        "published_path": "/media/unit/b.jpg",
        "stage_path": "/media/unit/.nfc-media-organizer-stage-41/000002.jpg",
    }
    assert [entry["path"] for entry in fields["original_links"]] == [
        "/media/unit/a.jpg", "/media/unit/b.jpg", "/media/unit/ordinary.png",
    ]
    assert len(fields["staged_links"]) == 4


def test_case_only_remap_requires_release_and_distinct_source_spellings_are_allowed():
    manifest = _manifest(pairs=[("Photo.JPG", "photo.jpg"),
                                ("Other.jpg", "001.jpg"), ("other.jpg", "002.jpg")])
    rows = manifest["moves"]

    result = _module().classify_path_roles(manifest)

    assert result["retained_sources"] == []
    assert result["deferred_rows"] == [rows[0]]
    assert result["released_sources"] == [rows[0]]
    assert result["ordinary_sources"] == rows[1:]


def test_retained_group_requires_exact_frozen_directory_spelling():
    manifest = _manifest(pairs=[("P [1 11B]/001.jpg", "P [1 11B]/001.jpg")])
    manifest["groups"] = [{"name": "P [1 11B]", "kind": "P", "count": 1,
                           "bytes": 11, "destination": "/media/unit/P [1 11B]"}]
    manifest["wrapper_identities"] = {
        "/media/unit/P [1 11B]": [7, 301],
        "/media/unit/p [1 11b]": [7, 302],
        "/media/unit/P1": [7, 303],
    }

    result = _module().classify_path_roles(manifest)

    assert result["retained_groups"] == {"/media/unit/P [1 11B]": [7, 301]}
    assert result["removed_wrappers"] == {
        "/media/unit/p [1 11b]": [7, 302], "/media/unit/P1": [7, 303],
    }


def test_classifier_requires_no_filesystem_reads_or_opt_in(monkeypatch):
    manifest = _manifest()
    module = _module()

    def forbidden(*args, **kwargs):
        pytest.fail("path-role classification must not inspect current filesystem state")

    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", forbidden)
        patch.setattr(os, "lstat", forbidden)
        result = module.classify_path_roles(manifest)
    assert result["retained_sources"] == [manifest["moves"][0]]
    assert module.uses_path_roles(manifest) is False
    manifest["path_role_policy"] = POLICY
    assert module.uses_path_roles(manifest) is True


@pytest.mark.parametrize("policy", [None, False, True, "", "unknown", "confirmed_relayout_v2"])
def test_unknown_present_path_role_policy_is_refused(policy):
    manifest = _manifest()
    manifest["path_role_policy"] = policy
    with pytest.raises(ValueError):
        _module().uses_path_roles(manifest)


def test_path_roles_never_opt_in_automatic_cleanup():
    manifest = _manifest()
    manifest.update(path_role_policy=POLICY, cleanup_policy="automatic")
    with pytest.raises(ValueError):
        _module().uses_path_roles(manifest)


@pytest.mark.parametrize("damage", [
    "relative_unit", "traversal_unit", "empty_moves", "non_dict_row",
    "duplicate_source", "duplicate_final_casefold", "outside_source",
    "noncanonical_source", "outside_target", "outside_final", "unit_as_source",
    "source_in_stage", "bad_identity", "boolean_identity", "duplicate_stage",
    "outside_wrapper", "bad_wrapper_identity", "bad_group_destination",
])
def test_invalid_frozen_path_roles_are_refused(damage):
    manifest = _manifest()
    rows = manifest["moves"]
    if damage == "relative_unit":
        manifest["unit"] = "media/unit"
    elif damage == "traversal_unit":
        manifest["unit"] = "/media/elsewhere/../unit"
    elif damage == "empty_moves":
        manifest["moves"] = []
    elif damage == "non_dict_row":
        rows[0] = []
    elif damage == "duplicate_source":
        rows[1]["source"] = rows[0]["source"]
    elif damage == "duplicate_final_casefold":
        rows[1]["final"] = "/media/unit/KEEP.JPG"
        rows[1]["target_name"] = "KEEP.JPG"
    elif damage == "outside_source":
        rows[0]["source"] = "/media/foreign/keep.jpg"
    elif damage == "noncanonical_source":
        rows[0]["source"] = "/media/unit/P1/../keep.jpg"
    elif damage == "outside_target":
        rows[0]["target"] = "/media/unit/not-stage.jpg"
    elif damage == "outside_final":
        rows[0]["final"] = "/media/foreign/keep.jpg"
    elif damage == "unit_as_source":
        rows[0]["source"] = manifest["unit"]
    elif damage == "source_in_stage":
        rows[0]["source"] = rows[0]["target"]
    elif damage == "bad_identity":
        rows[0]["identity"] = [7, 123]
    elif damage == "boolean_identity":
        rows[0]["identity"][1] = True
    elif damage == "duplicate_stage":
        rows[1]["target"] = rows[0]["target"]
    elif damage == "outside_wrapper":
        manifest["wrapper_identities"] = {"/media/foreign/P1": [7, 123]}
    elif damage == "bad_wrapper_identity":
        manifest["wrapper_identities"] = {"/media/unit/P1": [7, False]}
    elif damage == "bad_group_destination":
        manifest["groups"] = [{"name": "P [1 11B]", "destination": "/media/foreign/P"}]
    with pytest.raises(ValueError):
        _module().classify_path_roles(manifest)
