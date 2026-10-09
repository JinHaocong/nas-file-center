from pathlib import Path

import pytest

from app.batch import filename_audit
from app.batch.filename_audit import audit_immediate_filenames, _inspect_name


def run_audit(folder: Path, *, roots=None, quarantine=None):
    return audit_immediate_filenames(
        folder, allowed_roots=roots if roots is not None else [folder.parent],
        quarantine_root=quarantine,
    )


def audit_map(report):
    return {row["name"]: row for row in report["items"]}


@pytest.mark.parametrize("name,code", [
    (" leading.txt", "edge_whitespace"),
    ("trailing.txt ", "edge_whitespace"),
    ("period.txt.", "windows_trailing_dot_space"),
    ("con.txt", "windows_reserved_device"),
    ("NUL", "windows_reserved_device"),
    ("photo?.jpg", "windows_invalid_character"),
    ("file\u200bhidden.txt", "invisible_or_control"),
    ("photo.jpg.jpg", "repeated_extension"),
    ("invoice.pdf.exe", "suspicious_double_extension"),
    ("e\u0301.txt", "unicode_non_nfc"),
    ("x" * 241, "long_name"),
])
def test_detects_filename_issue_categories(name, code):
    assert code in _inspect_name(name)


@pytest.mark.parametrize("name", [
    "normal-file.txt", "archive.tar.gz", "photo.jpg", ".env",
    "album.2026.jpg", "my-file_name.txt",
])
def test_ordinary_filenames_not_flagged(name):
    assert _inspect_name(name) == []


def test_read_only_scan_suggests_only_unambiguous_ascii_trim(tmp_path):
    folder = tmp_path / "root"
    folder.mkdir()
    (folder / " a.txt ").write_text("contents")
    (folder / "normal.jpg").write_text("normal")
    (folder / " x\u200by.txt ").write_text("hidden")
    report = run_audit(folder)
    rows = audit_map(report)
    assert report["scanned"] == 3
    assert report["checked_regular_files"] == 3
    assert report["total"] == 2
    assert rows[" a.txt "]["suggested_target"] == str(folder / "a.txt")
    assert "edge_whitespace" in rows[" a.txt "]["issues"]
    assert rows[" x\u200by.txt "]["suggested_target"] is None
    assert rows[" x\u200by.txt "]["suggestion_block_reason"]
    assert (folder / " a.txt ").read_text() == "contents"
    assert not (folder / "a.txt").exists()


def test_existing_target_file_directory_symlink_and_casefold_block_proposals(tmp_path):
    folder = tmp_path / "root"
    folder.mkdir()
    (folder / " file.txt ").write_text("source")
    (folder / "file.txt").mkdir()
    (folder / " Foo.txt ").write_text("source2")
    (folder / "foo.txt").write_text("existing")
    (folder / " link.txt ").write_text("source3")
    (folder / "link.txt").symlink_to(folder / "foo.txt")
    rows = audit_map(run_audit(folder))
    for name in (" file.txt ", " Foo.txt ", " link.txt "):
        assert rows[name]["suggested_target"] is None
        assert rows[name]["suggestion_block_reason"]


def test_two_trim_candidates_must_not_target_same_name(tmp_path):
    folder = tmp_path / "root"
    folder.mkdir()
    (folder / " x.txt").write_text("a")
    (folder / "x.txt ").write_text("b")
    rows = audit_map(run_audit(folder))
    suggestions = [row["suggested_target"] for row in rows.values()]
    assert sum(bool(value) for value in suggestions) == 1
    assert (folder / " x.txt").exists() and (folder / "x.txt ").exists()


def test_nonrecursive_and_no_symlink_follow(tmp_path):
    folder = tmp_path / "root"
    folder.mkdir()
    (folder / "folder").mkdir()
    (folder / "folder" / " nested.txt ").write_text("nested")
    (folder / " link.txt ").symlink_to(folder / "folder" / " nested.txt ")
    (folder / " file.txt ").write_text("a")
    result = run_audit(folder)
    assert result["total"] == 1
    assert result["items"][0]["name"] == " file.txt "
    assert result["ignored_entries"] == 2
    assert (folder / "folder" / " nested.txt ").exists()
    assert (folder / " link.txt ").is_symlink()


def test_quarantine_and_outside_root_rejected(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    other = tmp_path / "outside"
    other.mkdir()
    trash = root / ".trash"
    trash.mkdir()
    (trash / " hidden.txt ").write_text("secret")
    (root / " visible.txt ").write_text("visible")
    report = run_audit(root, roots=[root], quarantine=trash)
    assert report["total"] == 1
    assert report["items"][0]["name"] == " visible.txt "
    with pytest.raises(ValueError):
        run_audit(trash, roots=[root], quarantine=trash)
    with pytest.raises(ValueError):
        run_audit(other, roots=[root])
    with pytest.raises(ValueError):
        run_audit(Path("relative-directory"), roots=[root])
    (tmp_path / "alias").symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        run_audit(tmp_path / "alias", roots=[tmp_path])


def test_absolute_parent_with_symlink_component_rejected(tmp_path):
    folder = tmp_path / "real"
    folder.mkdir()
    (folder / " bad.txt ").write_text("bad")
    alias = tmp_path / "alias"
    alias.symlink_to(folder, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        run_audit(alias, roots=[tmp_path])


def test_limit_is_checked_before_returning_any_partial_result(tmp_path, monkeypatch):
    folder = tmp_path / "root"
    folder.mkdir()
    for name in ("a", "b", "c"):
        (folder / name).write_text("x")
    monkeypatch.setattr(filename_audit, "MAX_AUDIT_ENTRIES", 2)
    with pytest.raises(ValueError, match="Too many immediate entries"):
        run_audit(folder)


def test_no_automatic_suggestion_for_windows_or_double_extension(tmp_path):
    folder = tmp_path / "root"
    folder.mkdir()
    (folder / " invoice.pdf.exe ").write_text("not automatically repairable")
    (folder / " CON.txt ").write_text("device")
    rows = audit_map(run_audit(folder))
    assert rows[" invoice.pdf.exe "]["suggested_target"] is None
    assert rows[" CON.txt "]["suggested_target"] is None


def test_authenticated_preview_and_draft_do_not_modify_files(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    source = data / " old.txt "
    source.write_text("important content")
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
        url = "/api/filenames/audit/preview"
        payload = {"parent": str(data)}
        assert client.post(url, json=payload).status_code == 401
        client.headers.update({"Origin": "http://testserver"})
        login = client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        })
        assert login.status_code == 200, login.text
        scan = client.post(url, json=payload)
        assert scan.status_code == 200, scan.text
        result = scan.json()
        assert result["total"] == 1
        assert result["items"][0]["path"] == str(source)
        row = result["items"][0]
        assert row["suggested_target"] == str(data / "old.txt")
        draft = client.post("/api/plans", json={
            "name": "filename quality",
            "kind": "rename",
            "items": [{
                "operation": "rename",
                "source": row["path"],
                "target": row["suggested_target"],
            }],
        })
        assert draft.status_code == 200, draft.text
        assert draft.json()["expected_changes"] == 1
        assert source.read_text() == "important content"
        assert not (data / "old.txt").exists()
        assert client.post(url, json={"parent": str(tmp_path)}).status_code == 400
        assert client.post(url, json={**payload, "unexpected": True}).status_code == 422
