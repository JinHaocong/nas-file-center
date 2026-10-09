from pathlib import Path

import pytest

from app.batch.directory_rename import preview_immediate_directory_renames


def preview(parent: Path, mode: str, *, find: str = "", value: str = "", quarantine_root=None):
    return preview_immediate_directory_renames(
        parent,
        mode=mode,
        find=find,
        value=value,
        allowed_roots=[parent.parent],
        quarantine_root=quarantine_root,
    )


@pytest.mark.parametrize(
    ("mode", "find", "value", "source", "target"),
    [
        ("replace_name", "abc", "X", "abc-abc", "X-X"),
        ("replace_name", ".", "_", "a.b.c", "a_b_c"),
        ("replace_suffix", "_old", "_new", "album_old", "album_new"),
        ("replace_suffix", ".webp", ".jpg", "album.webp", "album.jpg"),
        ("replace_suffix", "_old", "", "album_old", "album"),
        ("add_prefix", "", "2026_", "album", "2026_album"),
        ("add_suffix", "", "_done", "album", "album_done"),
    ],
)
def test_literal_modes(tmp_path, mode, find, value, source, target):
    root = tmp_path / "library"
    root.mkdir()
    (root / source).mkdir()

    result = preview(root, mode, find=find, value=value)

    assert len(result) == 1
    assert result[0]["source"] == str(root / source)
    assert result[0]["target"] == str(root / target)
    assert result[0]["conflict"] is False
    assert (root / source).is_dir()  # Preview must not mutate.


def test_one_level_only_skips_files_nested_directories_and_symlinks(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "old-parent").mkdir()
    (root / "old-parent" / "old-nested").mkdir()
    (root / "old-file.txt").write_text("do not rename")
    (root / "old-link").symlink_to(root / "old-parent", target_is_directory=True)

    result = preview(root, "replace_name", find="old", value="new")

    assert [(Path(item["source"]).name, Path(item["target"]).name)
            for item in result] == [("old-parent", "new-parent")]
    assert (root / "old-parent" / "old-nested").is_dir()
    assert (root / "old-file.txt").exists()
    assert (root / "old-link").is_symlink()


def test_suffix_only_matches_end(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "old_middle_name").mkdir()
    (root / "ending_old").mkdir()

    result = preview(root, "replace_suffix", find="old", value="new")

    assert [Path(item["source"]).name for item in result] == ["ending_old"]


def test_collision_with_existing_directory_does_not_allow_clobber(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "old").mkdir()
    (root / "new").mkdir()

    result = preview(root, "replace_name", find="old", value="new")

    assert len(result) == 1
    assert result[0]["conflict"] is True
    assert "already exists" in result[0]["conflict_reason"]


def test_conflicting_new_names_detected(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "xx").mkdir()
    (root / "x").mkdir()
    # "xx" -> "" after replacement, invalid; "x" -> "" too
    result = preview(root, "replace_name", find="x", value="")

    assert len(result) == 2
    assert all(item["conflict"] for item in result)



def test_literal_whitespace_replacement(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "hello world").mkdir()

    result = preview(root, "replace_name", find=" ", value="_")

    assert result[0]["target"] == str(root / "hello_world")
    assert result[0]["conflict"] is False


def test_casefold_output_collision_detected_conservatively(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "Foo-A").mkdir()
    (root / "foo-A").mkdir()

    result = preview(root, "replace_suffix", find="-A", value="")

    assert len(result) == 2
    assert sum(item["conflict"] for item in result) == 1



def test_quarantine_and_file_ignored(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    trash = root / ".trash"
    trash.mkdir()
    (root / "media").mkdir()
    (root / "file").write_text("x")

    result = preview(root, "add_prefix", value="NEW-", quarantine_root=trash)

    assert len(result) == 1
    assert Path(result[0]["source"]).name == "media"


@pytest.mark.parametrize("mode,find,value", [
    ("replace_name", "", "x"),
    ("replace_suffix", "", "x"),
    ("add_prefix", "", ""),
    ("add_suffix", "", ""),
    ("regex", "x", "y"),
])
def test_invalid_rules_rejected(tmp_path, mode, find, value):
    root = tmp_path / "library"
    root.mkdir()
    with pytest.raises(ValueError):
        preview(root, mode, find=find, value=value)


def test_directory_escape_disallowed_and_visible_as_conflict(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "album").mkdir()
    result = preview(root, "add_suffix", value="/escape")
    assert result[0]["conflict"]
    assert (root / "album").is_dir()


def test_reserved_parent_rejected(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    trash = root / ".trash"
    trash.mkdir()
    with pytest.raises(ValueError):
        preview(trash, "add_prefix", value="new", quarantine_root=trash)


def test_api_preview_and_plan_draft_do_not_mutate_directories(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    (data / "old-A").mkdir()
    (data / "old-A" / "old-nested").mkdir()
    (data / "old-B").mkdir()
    (data / "old-file").write_text("not a directory")

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
        client.headers.update({"Origin": "http://testserver"})
        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-password-123"},
        ).status_code == 200
        response = client.post("/api/rename/directories/preview", json={
            "parent": str(data), "mode": "replace_name",
            "find": "old", "value": "new",
        })
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 2
        assert all(item["conflict"] is False for item in items)
        assert {Path(item["target"]).name for item in items} == {"new-A", "new-B"}
        assert (data / "old-A" / "old-nested").exists()
        assert (data / "old-file").exists()

        plan = client.post("/api/plans", json={
            "name": "one-level directory rename",
            "kind": "rename",
            "items": [
                {"operation": "rename", "source": row["source"], "target": row["target"]}
                for row in items
            ],
        })
        assert plan.status_code == 200, plan.text
        assert plan.json()["expected_changes"] == 2
        assert (data / "old-A").is_dir()  # Draft does not rename.


def test_api_rejects_outside_root(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    data.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(tmp_path / "config"),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
        response = client.post("/api/rename/directories/preview", json={
            "parent": str(outside), "mode": "add_prefix", "value": "safe-",
        })
        assert response.status_code == 400
