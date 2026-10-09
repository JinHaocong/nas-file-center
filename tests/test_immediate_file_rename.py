from pathlib import Path
import os

import pytest

from app.batch import file_rename
from app.batch.file_rename import preview_immediate_file_renames


def preview(parent: Path, mode: str, *, find="", value="", preserve_extension=True,
            quarantine_root=None, allowed_roots=None):
    return preview_immediate_file_renames(
        parent, mode=mode, find=find, value=value,
        preserve_extension=preserve_extension,
        allowed_roots=allowed_roots if allowed_roots is not None else [parent.parent],
        quarantine_root=quarantine_root,
    )


@pytest.mark.parametrize("mode,find,value,keep,initial,expected", [
    ("replace_name", "old", "new", True, "old-old.JPG", "new-new.JPG"),
    ("replace_suffix", "_old", "_new", True, "album_old.webp", "album_new.webp"),
    ("replace_suffix", ".jpg", ".png", False, "photo.jpg", "photo.png"),
    ("replace_name", ".jpg", ".png", True, "photo.jpg", None),
    ("replace_name", ".jpg", ".png", False, "photo.jpg", "photo.png"),
    ("add_prefix", "", "2026_", True, "x.tar.gz", "2026_x.tar.gz"),
    ("add_suffix", "", "_done", True, "x.tar.gz", "x.tar_done.gz"),
    ("add_suffix", "", "_done", False, "x.tar.gz", "x.tar.gz_done"),
    ("replace_name", "old", "new", True, ".old", ".new"),
    ("add_suffix", "", "_x", True, ".env", ".env_x"),
    ("replace_suffix", "_old", "", True, "a_old.txt", "a.txt"),
    ("replace_name", " ", "_", True, "a b.txt", "a_b.txt"),
])
def test_all_literal_modes_and_extension_behavior(
    tmp_path, mode, find, value, keep, initial, expected,
):
    parent = tmp_path / "files"
    parent.mkdir()
    (parent / initial).write_bytes(b"data")
    rows = preview(parent, mode, find=find, value=value, preserve_extension=keep)
    if expected is None:
        assert rows == []
    else:
        assert len(rows) == 1
        assert rows[0] == {
            "source": str(parent / initial),
            "target": str(parent / expected),
            "conflict": False,
            "conflict_reason": None,
        }
    assert (parent / initial).read_bytes() == b"data"


def test_nonrecursive_regular_files_only_and_symlink_exclusion(tmp_path):
    parent = tmp_path / "files"
    parent.mkdir()
    (parent / "old-file.txt").write_text("data")
    (parent / "old-folder").mkdir()
    (parent / "old-folder" / "old-nested.txt").write_text("nested")
    (parent / "old-link.txt").symlink_to(parent / "old-file.txt")
    (parent / "old-folder-link").symlink_to(parent / "old-folder", target_is_directory=True)

    rows = preview(parent, "replace_name", find="old", value="new")
    assert len(rows) == 1
    assert Path(rows[0]["source"]).name == "old-file.txt"
    assert (parent / "old-folder" / "old-nested.txt").exists()
    assert (parent / "old-link.txt").is_symlink()
    assert (parent / "old-folder-link").is_symlink()


@pytest.mark.parametrize("occupant", ["file", "directory", "symlink"])
def test_rejects_existing_target_even_when_type_differs(tmp_path, occupant):
    parent = tmp_path / "files"
    parent.mkdir()
    (parent / "old.txt").write_text("old")
    dest = parent / "new.txt"
    if occupant == "file":
        dest.write_text("new")
    elif occupant == "directory":
        dest.mkdir()
    else:
        dest.symlink_to(parent / "old.txt")
    rows = preview(parent, "replace_name", find="old", value="new")
    assert len(rows) == 1
    assert rows[0]["conflict"] is True
    assert ("collides" in rows[0]["conflict_reason"] or
            "symlink" in rows[0]["conflict_reason"])
    assert (parent / "old.txt").read_text() == "old"


def test_conflicting_proposals_block_plan_by_marking_at_least_one(tmp_path):
    parent = tmp_path / "files"
    parent.mkdir()
    (parent / "a1.txt").write_text("A")
    (parent / "a11.txt").write_text("B")
    rows = preview(parent, "replace_name", find="1", value="")
    # Both produce "a.txt" and the second is a collision.
    assert len(rows) == 2
    assert any(row["conflict"] for row in rows)


def test_conservative_case_insensitive_collision_and_case_only_rename(tmp_path):
    parent = tmp_path / "files"
    parent.mkdir()
    (parent / "old.txt").write_text("old")
    (parent / "NEW.txt").write_text("new")
    rows = preview(parent, "replace_name", find="old", value="new")
    assert len(rows) == 1 and rows[0]["conflict"]

    (parent / "NEW.txt").unlink()
    (parent / "Upper.txt").write_text("x")
    rows = preview(parent, "replace_name", find="Upper", value="upper")
    assert len(rows) == 1 and rows[0]["conflict"]


@pytest.mark.parametrize("mode,find,value", [
    ("replace_name", "", "value"),
    ("replace_suffix", "", "value"),
    ("add_prefix", "", ""),
    ("add_suffix", "", ""),
    ("unsupported", "x", "y"),
])
def test_invalid_rules_rejected(tmp_path, mode, find, value):
    parent = tmp_path / "files"
    parent.mkdir()
    with pytest.raises(ValueError):
        preview(parent, mode, find=find, value=value)


@pytest.mark.parametrize("value", ["x/y", "x\\y", "\x00", "x" * 250])
def test_unsafe_output_is_conflict_not_mutation(tmp_path, value):
    parent = tmp_path / "files"
    parent.mkdir()
    (parent / "a.txt").write_text("x")
    rows = preview(parent, "add_prefix", value=value)
    assert len(rows) == 1 and rows[0]["conflict"] is True
    assert (parent / "a.txt").exists()


def test_rejects_overlong_rule_input(tmp_path):
    parent = tmp_path / "files"
    parent.mkdir()
    (parent / "a.txt").write_text("x")
    # Request-schema limit applies to the rule value itself (not a row conflict).
    with pytest.raises(ValueError, match="at most 255 characters"):
        preview(parent, "add_prefix", value="x" * 260)
    assert (parent / "a.txt").read_text() == "x"


def test_parent_and_quarantine_guards(tmp_path):
    parent = tmp_path / "files"
    outside = tmp_path / "outside"
    parent.mkdir()
    outside.mkdir()
    trash = parent / ".trash"
    trash.mkdir()
    (trash / "file.txt").write_text("hidden")
    (parent / "old.txt").write_text("data")

    rows = preview(parent, "add_prefix", value="new-", quarantine_root=trash)
    assert len(rows) == 1
    assert "old.txt" in rows[0]["source"]

    with pytest.raises(ValueError):
        preview(trash, "add_prefix", value="new-", allowed_roots=[tmp_path],
                quarantine_root=trash)
    with pytest.raises(ValueError):
        preview(outside, "add_prefix", value="new-", allowed_roots=[parent])
    with pytest.raises(ValueError):
        preview("relative", "add_prefix", value="new-", allowed_roots=[tmp_path])
    (tmp_path / "alias").symlink_to(parent, target_is_directory=True)
    with pytest.raises(ValueError):
        preview(tmp_path / "alias", "add_prefix", value="new-")


def test_preview_bounded_by_all_directory_entries(tmp_path, monkeypatch):
    parent = tmp_path / "files"
    parent.mkdir()
    for n in ("first", "second", "third"):
        (parent / n).mkdir()
    (parent / "old.txt").write_text("x")
    monkeypatch.setattr(file_rename, "MAX_IMMEDIATE_ENTRIES", 2)
    with pytest.raises(ValueError, match="Too many immediate entries"):
        preview(parent, "add_prefix", value="n-")


def test_backend_api_is_authenticated_read_only_and_can_create_draft(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    (data / "old-1.jpg").write_text("photo")
    (data / "old-subdir").mkdir()
    (data / "old-subdir" / "old-nested.jpg").write_text("nested")
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False,
        ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        url = "/api/rename/files/preview"
        payload = {
            "parent": str(data), "mode": "replace_name",
            "find": "old", "value": "new", "preserve_extension": True,
        }
        assert client.post(url, json=payload).status_code == 401
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200

        response = client.post(url, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 1
        row = response.json()["items"][0]
        assert row["source"] == str(data / "old-1.jpg")
        assert row["target"] == str(data / "new-1.jpg")
        assert row["conflict"] is False

        plan = client.post("/api/plans", json={
            "name": "one-level file rename",
            "kind": "rename",
            "items": [{
                "operation": "rename", "source": row["source"], "target": row["target"],
            }],
        })
        assert plan.status_code == 200, plan.text
        assert plan.json()["expected_changes"] == 1
        assert (data / "old-1.jpg").exists()
        assert (data / "old-subdir" / "old-nested.jpg").exists()
        assert not (data / "new-1.jpg").exists()

        assert client.post(url, json={**payload, "mode": "regex"}).status_code == 422
        assert client.post(url, json={**payload, "extra": 1}).status_code == 422
        assert client.post(url, json={**payload, "parent": str(tmp_path)}).status_code == 400
